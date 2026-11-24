"""Платёжные ссылки Модульбанка в карточке сделки или лида.

Модульбанк не выдаёт готовую ссылку: оплата — это POST-форма на pay.modulbank.ru.
Поэтому ссылка ведёт на нашу страницу /api/modulbank/pay/<id>, которая сразу
отправляет подписанную форму в банк. Результат банк присылает на callback,
и дальше работает общий код ссылок Точки: таблица операций, сверка с выпиской,
поля CRM и уведомления.

Ответы эндпоинтов повторяют формат /api/tochka/acquiring/*, чтобы интерфейс
карточки сделки работал без изменений.
"""
from __future__ import annotations

import json
import logging
import uuid
from decimal import Decimal, InvalidOperation
from html import escape

from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from config import load_config

from .ledger import ACQUIRING_PAID_STATUS, ACQUIRING_REFUNDED
from .models import ModulbankCredentials, TochkaAcquiringOperation
from .modulbank import acquiring as mb_acq
from .utils import AuthorizedRequest
from .utils.decorators import auth_required, log_errors

config = load_config()
logger = logging.getLogger(__name__)

_ALLOWED_PAYMENT_KINDS = frozenset({"full", "remainder", "advance"})
_RETAILER_NAME = "Модульбанк"
_DEFAULT_MODES = ["card", "sbp"]


def _base_url() -> str:
    return (config.app_base_url or "").rstrip("/")


def _pay_url(op_id) -> str:
    return f"{_base_url()}/api/modulbank/pay/{op_id}"


def _creds(member_id: str) -> ModulbankCredentials | None:
    return ModulbankCredentials.objects.filter(member_id=member_id).first()


def _retailer(creds: ModulbankCredentials) -> dict:
    """Эквайринг Модульбанка в формате «торговой точки» Точки для интерфейса."""
    return {
        "name": _RETAILER_NAME,
        "merchantId": creds.acquiring_merchant_id,
        "isActive": "true",
        "status": "REG",
        "paymentModes": list(_DEFAULT_MODES),
        "testing": creds.acquiring_testing,
    }


# --- настройки ------------------------------------------------------------------


@xframe_options_exempt
@csrf_exempt
@require_http_methods(["GET", "POST"])
@log_errors("modulbank_acquiring_settings")
@auth_required
def modulbank_acquiring_settings(request: AuthorizedRequest):
    """GET — что сохранено (без секрета); POST {merchantId, secretKey, testing} — сохранить."""
    member_id = request.bitrix24_account.member_id
    if request.method == "POST":
        try:
            body = json.loads(request.body) if request.body else {}
        except json.JSONDecodeError:
            return JsonResponse({"error": "Некорректный JSON"}, status=400)
        merchant_id = str(body.get("merchantId") or "").strip()
        secret_key = str(body.get("secretKey") or "").strip()
        testing = bool(body.get("testing"))
        creds, _ = ModulbankCredentials.objects.get_or_create(member_id=member_id)
        if not merchant_id:
            return JsonResponse({"error": "Укажите Merchant ID из личного кабинета эквайринга"}, status=400)
        if not secret_key and not creds.acquiring_secret_key:
            return JsonResponse({"error": "Укажите секретный ключ из личного кабинета эквайринга"}, status=400)
        creds.acquiring_merchant_id = merchant_id[:64]
        if secret_key:
            creds.acquiring_secret_key = secret_key[:255]
        creds.acquiring_testing = testing
        creds.save()
    creds = _creds(member_id)
    return JsonResponse({
        "configured": bool(creds and creds.acquiring_configured),
        "merchantId": creds.acquiring_merchant_id if creds else "",
        "hasSecretKey": bool(creds and creds.acquiring_secret_key),
        "testing": bool(creds and creds.acquiring_testing),
        "callbackUrl": f"{_base_url()}/api/modulbank/acquiring/callback",
    })


@xframe_options_exempt
@require_GET
@log_errors("modulbank_acquiring_retailers")
@auth_required
def modulbank_acquiring_retailers(request: AuthorizedRequest):
    creds = _creds(request.bitrix24_account.member_id)
    retailers = [_retailer(creds)] if creds and creds.acquiring_configured else []
    return JsonResponse({"Data": {"Retailer": retailers}})


# --- создание ссылки --------------------------------------------------------------


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("modulbank_acquiring_create_payment_link")
@auth_required
def modulbank_acquiring_create_payment_link(request: AuthorizedRequest):
    member_id = request.bitrix24_account.member_id
    creds = _creds(member_id)
    if not creds or not creds.acquiring_configured:
        return JsonResponse({
            "error": "Интернет-эквайринг Модульбанка не настроен: укажите Merchant ID и секретный ключ "
                     "в настройках приложения (Настройки → Эквайринг).",
        }, status=400)

    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Некорректный JSON"}, status=400)

    deal_id = body.get("dealId")
    lead_id = body.get("leadId")
    payment_kind = (body.get("paymentKind") or "").strip().lower()
    purpose = (body.get("purpose") or "").strip()
    modes = body.get("paymentModes") or list(_DEFAULT_MODES)

    try:
        amount = Decimal(str(body.get("amount")))
    except (InvalidOperation, ValueError):
        return JsonResponse({"error": "invalid amount"}, status=400)
    if amount <= 0:
        return JsonResponse({"error": "amount must be positive"}, status=400)
    has_deal = deal_id not in (None, "")
    has_lead = lead_id not in (None, "")
    if has_deal == has_lead:
        return JsonResponse({"error": "Specify exactly one of dealId, leadId"}, status=400)
    if payment_kind not in _ALLOWED_PAYMENT_KINDS:
        return JsonResponse({"error": "invalid paymentKind"}, status=400)
    try:
        deal_id_int = int(deal_id) if has_deal else None
        lead_id_int = int(lead_id) if has_lead else None
    except (TypeError, ValueError):
        return JsonResponse({"error": "invalid deal or lead id"}, status=400)

    requested = [str(m).lower() for m in modes] if isinstance(modes, list) else list(_DEFAULT_MODES)
    applied = [m for m in requested if m in _DEFAULT_MODES] or list(_DEFAULT_MODES)
    dropped = sorted(set(requested) - set(applied))

    op = TochkaAcquiringOperation(
        member_id=member_id,
        deal_id=deal_id_int,
        lead_id=lead_id_int,
        amount=amount.quantize(Decimal("0.01")),
        currency="RUB",
        customer_code=f"modulbank:{creds.acquiring_merchant_id}",
        merchant_id=creds.acquiring_merchant_id,
        payment_modes_requested=applied,
        payment_kind=payment_kind,
        purpose=purpose or (f"Оплата сделки #{deal_id_int}" if deal_id_int else f"Оплата лида #{lead_id_int}"),
        status="pending",
    )
    op.payment_url = _pay_url(op.id)
    op.save()

    return JsonResponse({
        "operationId": str(op.id),
        "paymentUrl": op.payment_url,
        "paymentModesRequested": requested,
        "paymentModesApplied": applied,
        "retailerPaymentModes": list(_DEFAULT_MODES),
        "paymentModesDropped": dropped,
    })


# --- страница оплаты (публичная) ----------------------------------------------------


def _page(title: str, text: str, status: int = 200, extra: str = "") -> HttpResponse:
    html = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>body{{font:16px system-ui,sans-serif;margin:0;min-height:100vh;display:flex;align-items:center;
justify-content:center;background:#f5f8fb;color:#02245d}}.box{{max-width:420px;padding:32px 24px;text-align:center}}
h1{{font-size:20px;margin:0 0 12px}}p{{color:#4b5563;line-height:1.5;margin:0 0 16px}}
button{{padding:12px 24px;border:0;border-radius:12px;background:#02245d;color:#fff;font:inherit;cursor:pointer}}</style>
</head><body><div class="box"><h1>{escape(title)}</h1><p>{escape(text)}</p>{extra}</div></body></html>"""
    return HttpResponse(html, status=status)


@xframe_options_exempt
@require_GET
def modulbank_pay_page(request, operation_id: uuid.UUID):
    """Открывается покупателем по ссылке: отправляет подписанную форму в банк."""
    op = TochkaAcquiringOperation.objects.filter(id=operation_id, customer_code__startswith="modulbank:").first()
    if not op:
        return _page("Ссылка на оплату не найдена", "Проверьте ссылку или запросите новую у продавца.", 404)
    if op.status in (ACQUIRING_PAID_STATUS, "authorized"):
        return _page("Счёт уже оплачен", "Спасибо! Повторно платить не нужно.")
    if op.status in ("cancelled", ACQUIRING_REFUNDED):
        return _page("Ссылка больше не действует", "Запросите новую ссылку на оплату у продавца.", 410)

    creds = _creds(op.member_id)
    if not creds or not creds.acquiring_configured:
        return _page("Оплата временно недоступна", "Продавец не завершил настройку приёма оплаты.", 503)

    done = f"{_pay_url(op.id)}/done"
    form = mb_acq.compose_payment_form(
        merchant_id=creds.acquiring_merchant_id,
        secret_key=creds.acquiring_secret_key,
        testing=creds.acquiring_testing,
        amount=op.amount,
        order_id=str(op.id),
        description=(op.purpose or "Оплата")[:250],
        success_url=f"{done}?result=success",
        fail_url=f"{done}?result=fail",
        callback_url=f"{_base_url()}/api/modulbank/acquiring/callback",
        payment_methods=list(op.payment_modes_requested or _DEFAULT_MODES),
    )
    inputs = "".join(
        f'<input type="hidden" name="{escape(k)}" value="{escape(v)}">' for k, v in form.items()
    )
    extra = (
        f'<form id="pay" method="post" action="{escape(mb_acq.PAY_FORM_URL)}">{inputs}'
        '<button type="submit">Перейти к оплате</button></form>'
        '<script>document.getElementById("pay").submit()</script>'
    )
    return _page(f"Оплата {mb_acq.format_amount(op.amount)} ₽", "Переходим на защищённую страницу Модульбанка…", extra=extra)


def _apply_bank_data(op: TochkaAcquiringOperation, creds: ModulbankCredentials, data: dict) -> str | None:
    """Проверить данные банка и обновить операцию. Возвращает ошибку или None.

    Вызывать внутри transaction.atomic() с op, взятой через select_for_update().
    """
    if str(data.get("order_id") or "") != str(op.id):
        return "order_id mismatch"
    if str(data.get("merchant") or creds.acquiring_merchant_id) != creds.acquiring_merchant_id:
        return "merchant mismatch"
    try:
        if Decimal(str(data.get("amount"))).quantize(Decimal("0.01")) != op.amount.quantize(Decimal("0.01")):
            return "amount mismatch"
    except (InvalidOperation, ValueError):
        return "amount mismatch"
    if data.get("currency") and str(data["currency"]).upper() not in ("RUB", "RUR"):
        return "currency mismatch"
    if str(data.get("testing", "0")) == "1" and not creds.acquiring_testing:
        return "test payment on live settings"

    prev_paid = op.status == ACQUIRING_PAID_STATUS
    new_status = mb_acq.internal_status(data.get("state"))
    if prev_paid and new_status != ACQUIRING_PAID_STATUS:
        return None  # не откатываем оплаченную операцию поздним уведомлением о неудаче
    op.webhook_raw = json.dumps({k: v for k, v in data.items() if k != "signature"}, ensure_ascii=False)
    if data.get("transaction_id"):
        op.external_operation_id = str(data["transaction_id"])
    if data.get("payment_method"):
        op.payment_mode_effective = str(data["payment_method"]).lower()[:32]
    op.status = new_status
    op.save()

    if op.status == ACQUIRING_PAID_STATUS and not prev_paid:
        from .views_acquiring import _dedupe_bank_payment_for_acquiring, _push_uf_after_paid

        _dedupe_bank_payment_for_acquiring(op)
        _push_uf_after_paid(op)
    return None


@xframe_options_exempt
@require_GET
def modulbank_pay_done(request, operation_id: uuid.UUID):
    """Возврат покупателя со страницы банка. Статус уточняем у банка по transaction_id."""
    op = TochkaAcquiringOperation.objects.filter(id=operation_id, customer_code__startswith="modulbank:").first()
    tx_id = request.GET.get("transaction_id")
    if op and tx_id and op.status != ACQUIRING_PAID_STATUS:
        creds = _creds(op.member_id)
        if creds and creds.acquiring_configured:
            try:
                data = mb_acq.get_transaction(creds.acquiring_merchant_id, creds.acquiring_secret_key, tx_id)
            except Exception as e:  # сеть банка — не ломаем страницу покупателю
                logger.warning("modulbank_pay_done: transaction lookup failed: %s", e)
                data = None
            if data:
                with transaction.atomic():
                    locked = TochkaAcquiringOperation.objects.select_for_update().get(pk=op.pk)
                    _apply_bank_data(locked, creds, data)
                op.refresh_from_db()

    if op and op.status == ACQUIRING_PAID_STATUS:
        return _page("Оплата прошла", "Спасибо! Продавец получит уведомление об оплате.")
    if request.GET.get("result") == "success":
        return _page("Платёж обрабатывается", "Банк подтверждает оплату. Обычно это занимает до минуты.")
    retry = f'<a href="{escape(_pay_url(operation_id))}"><button type="button">Попробовать ещё раз</button></a>' if op else ""
    return _page("Оплата не прошла", "Деньги не списаны. Можно попробовать ещё раз.", extra=retry)


@csrf_exempt
@require_POST
def modulbank_acquiring_callback(request):
    """Уведомление банка о результате оплаты (POST-форма с подписью)."""
    data = {k: v for k, v in request.POST.items()}
    order_id = data.get("order_id") or ""
    try:
        op_uuid = uuid.UUID(str(order_id))
    except ValueError:
        return HttpResponse("ERROR: Unknown order_id\n", status=400, content_type="text/plain")

    with transaction.atomic():
        op = (
            TochkaAcquiringOperation.objects.select_for_update()
            .filter(id=op_uuid, customer_code__startswith="modulbank:")
            .first()
        )
        if not op:
            return HttpResponse("ERROR: Unknown order_id\n", status=404, content_type="text/plain")
        creds = _creds(op.member_id)
        if not creds or not creds.acquiring_configured:
            return HttpResponse("ERROR: Acquiring not configured\n", status=400, content_type="text/plain")
        if not mb_acq.is_signature_correct(data, creds.acquiring_secret_key):
            return HttpResponse('ERROR: Incorrect "signature"\n', status=401, content_type="text/plain")
        error = _apply_bank_data(op, creds, data)

    if error:
        return HttpResponse(f"ERROR: {error}\n", status=400, content_type="text/plain")
    return HttpResponse(f"OK{order_id}\n", content_type="text/plain")


# --- статусы и возврат ------------------------------------------------------------


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("modulbank_acquiring_refresh_statuses")
@auth_required
def modulbank_acquiring_refresh_statuses(request: AuthorizedRequest):
    """Уточнить у банка статус неоплаченных операций, по которым уже есть транзакция."""
    member_id = request.bitrix24_account.member_id
    creds = _creds(member_id)
    if not creds or not creds.acquiring_configured:
        return JsonResponse({"updated": 0})
    pending = TochkaAcquiringOperation.objects.filter(
        member_id=member_id,
        customer_code__startswith="modulbank:",
        status__in=["pending", "authorized"],
    ).exclude(external_operation_id__isnull=True).exclude(external_operation_id="")

    updated = 0
    for op in pending[:50]:
        try:
            data = mb_acq.get_transaction(creds.acquiring_merchant_id, creds.acquiring_secret_key, op.external_operation_id)
        except Exception as e:
            logger.warning("modulbank refresh: %s", e)
            continue
        if not data:
            continue
        with transaction.atomic():
            locked = TochkaAcquiringOperation.objects.select_for_update().get(pk=op.pk)
            before = locked.status
            _apply_bank_data(locked, creds, data)
            if locked.status != before:
                updated += 1
    return JsonResponse({"updated": updated})


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("modulbank_acquiring_refund")
@auth_required
def modulbank_acquiring_refund(request: AuthorizedRequest, operation_id: uuid.UUID):
    member_id = request.bitrix24_account.member_id
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        body = {}

    op = TochkaAcquiringOperation.objects.filter(id=operation_id, member_id=member_id).first()
    if not op:
        return JsonResponse({"error": "Operation not found"}, status=404)
    if op.status == ACQUIRING_REFUNDED:
        return JsonResponse({"error": "Already refunded"}, status=400)
    if op.status != ACQUIRING_PAID_STATUS:
        return JsonResponse({"error": "Refund is only available for paid operations"}, status=400)
    if not op.external_operation_id:
        return JsonResponse({"error": "Нет номера транзакции Модульбанка для возврата"}, status=400)

    amount = op.amount
    if body.get("amount") not in (None, ""):
        try:
            amount = Decimal(str(body["amount"]))
        except (InvalidOperation, ValueError):
            return JsonResponse({"error": "Invalid amount"}, status=400)
        if amount <= 0 or amount > op.amount:
            return JsonResponse({"error": "Invalid amount"}, status=400)

    creds = _creds(member_id)
    if not creds or not creds.acquiring_configured:
        return JsonResponse({"error": "Интернет-эквайринг Модульбанка не настроен"}, status=400)
    try:
        resp = mb_acq.refund(creds.acquiring_merchant_id, creds.acquiring_secret_key, op.external_operation_id, amount)
    except Exception as e:
        return JsonResponse({"error": str(e), "code": "modulbank_error"}, status=400)

    op.status = ACQUIRING_REFUNDED
    op.save(update_fields=["status", "updated_at"])
    return JsonResponse({"success": True, "raw": resp})
