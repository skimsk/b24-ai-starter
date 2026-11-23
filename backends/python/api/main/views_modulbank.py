"""HTTP API подключения Модульбанка.

Подключение — по ключу API из личного кабинета Модульбанка. Дальше всё как у
Точки: выписка ложится в общую таблицу платежей, а сопоставление со сделками и
уведомления берёт на себя общая пост-обработка.
"""
from __future__ import annotations

import json
import logging

from django.http import JsonResponse
from django.utils import timezone as dj_tz
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from config import load_config

from .models import ModulbankCredentials, TochkaPortalPreferences
from .modulbank import ModulbankAuthError, ModulbankClient, ModulbankError, verify_webhook_signature
from .modulbank_sync_logic import (
    get_connected_credentials,
    get_modulbank_client,
    iter_sync_accounts,
    run_modulbank_sync,
    upsert_operation,
)
from .tochka_sync_logic import run_post_sync_processing
from .utils import AuthorizedRequest
from .utils.decorators import auth_required, log_errors

config = load_config()
logger = logging.getLogger(__name__)


def _webhook_url(creds: ModulbankCredentials) -> str:
    base_url = (config.app_base_url or "").rstrip("/")
    return f"{base_url}/api/modulbank/webhook/{creds.webhook_key}"


def _mark_token_rejected(creds: ModulbankCredentials) -> JsonResponse:
    ModulbankCredentials.objects.filter(pk=creds.pk).update(is_connected=False, updated_at=dj_tz.now())
    return JsonResponse(
        {"error": "Модульбанк не принял ключ API. Подключите банк заново.", "needReconnect": True},
        status=401,
    )


@xframe_options_exempt
@require_GET
@log_errors("modulbank_status")
@auth_required
def modulbank_status(request: AuthorizedRequest):
    member_id = request.bitrix24_account.member_id
    creds = ModulbankCredentials.objects.filter(member_id=member_id).first()
    prefs = TochkaPortalPreferences.objects.filter(member_id=member_id).first()
    last_sync_at = prefs.last_sync_at if prefs and prefs.last_sync_at else None
    return JsonResponse({
        "connected": bool(creds and creds.is_connected),
        "hasCredentials": bool(creds and creds.api_token),
        "sandbox": bool(creds and creds.sandbox),
        "companyName": creds.company_name if creds else None,
        "companyInn": creds.company_inn if creds else None,
        "webhookUrl": _webhook_url(creds) if creds and creds.is_connected else None,
        "lastSyncAt": last_sync_at.isoformat().replace("+00:00", "Z") if last_sync_at else None,
    })


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("modulbank_connect")
@auth_required
def modulbank_connect(request: AuthorizedRequest):
    """Проверить ключ API запросом account-info и сохранить подключение.

    Тело: {"apiToken": "..."} или {"sandbox": true} для песочницы банка.
    """
    member_id = request.bitrix24_account.member_id
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Некорректный JSON"}, status=400)

    sandbox = bool(body.get("sandbox"))
    token = str(body.get("apiToken") or "").strip()
    if sandbox:
        client = ModulbankClient.for_sandbox()
        token = client.token
    elif not token:
        return JsonResponse({"error": "Вставьте ключ API из личного кабинета Модульбанка"}, status=400)
    else:
        client = ModulbankClient(token)

    try:
        companies = client.get_account_info()
    except ModulbankAuthError:
        return JsonResponse({"error": "Модульбанк не принял ключ API. Проверьте ключ и права account-info и operation-history."}, status=400)
    except (ModulbankError, OSError) as e:
        return JsonResponse({"error": f"Не удалось связаться с Модульбанком: {e}"}, status=502)

    if not companies:
        return JsonResponse({"error": "По этому ключу в Модульбанке не нашлось ни одной компании"}, status=400)

    company = companies[0]
    creds, _ = ModulbankCredentials.objects.update_or_create(
        member_id=member_id,
        defaults={
            "api_token": token,
            "sandbox": sandbox,
            "is_connected": True,
            "company_id": company.get("companyId") or "",
            "company_name": (company.get("companyName") or "")[:255],
            "company_inn": (company.get("Inn") or company.get("inn") or "")[:12],
        },
    )
    return JsonResponse({
        "success": True,
        "companyName": creds.company_name,
        "companies": len(companies),
        "webhookUrl": _webhook_url(creds),
    })


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("modulbank_disconnect")
@auth_required
def modulbank_disconnect(request: AuthorizedRequest):
    member_id = request.bitrix24_account.member_id
    ModulbankCredentials.objects.filter(member_id=member_id).update(
        is_connected=False, api_token="", updated_at=dj_tz.now(),
    )
    return JsonResponse({"success": True})


@xframe_options_exempt
@require_GET
@log_errors("modulbank_accounts")
@auth_required
def modulbank_accounts(request: AuthorizedRequest):
    """Счета по всем компаниям ключа с остатками (остаток приходит в account-info)."""
    creds = get_connected_credentials(request.bitrix24_account.member_id)
    if not creds:
        return JsonResponse({"error": "Модульбанк не подключён"}, status=400)
    try:
        companies = get_modulbank_client(creds).get_account_info()
    except ModulbankAuthError:
        return _mark_token_rejected(creds)
    except (ModulbankError, OSError) as e:
        return JsonResponse({"error": str(e)}, status=502)

    accounts = []
    for company in companies:
        for account in company.get("bankAccounts") or []:
            accounts.append({
                "accountId": account.get("id"),
                "number": account.get("number"),
                "name": account.get("accountName"),
                "category": account.get("category"),
                "currency": account.get("currency"),
                "status": account.get("status"),
                "balance": account.get("balance"),
                "bankName": account.get("bankName"),
                "bankBic": account.get("bankBic"),
                "companyId": company.get("companyId"),
                "companyName": company.get("companyName"),
            })
    return JsonResponse({"accounts": accounts})


@xframe_options_exempt
@csrf_exempt
@require_POST
@log_errors("modulbank_sync")
@auth_required
def modulbank_sync(request: AuthorizedRequest):
    """Забрать операции за период. Тело: {"days": 30} или {"startDate", "endDate"}."""
    member_id = request.bitrix24_account.member_id
    creds = get_connected_credentials(member_id)
    if not creds:
        return JsonResponse({"error": "Модульбанк не подключён"}, status=400)

    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Некорректный JSON"}, status=400)

    try:
        if body.get("startDate") and body.get("endDate"):
            result = run_modulbank_sync(
                member_id,
                start_date_calendar=str(body["startDate"]),
                end_date_calendar=str(body["endDate"]),
            )
        else:
            try:
                days = int(body.get("days", 30))
            except (TypeError, ValueError):
                days = 30
            result = run_modulbank_sync(member_id, days=days)
    except ValueError as e:
        return JsonResponse({"error": str(e)}, status=400)
    except ModulbankAuthError:
        return _mark_token_rejected(creds)
    except (ModulbankError, OSError) as e:
        return JsonResponse({"error": str(e)}, status=502)

    run_post_sync_processing(member_id, result)
    result.pop("new_payment_ids", None)
    return JsonResponse(result)


def _account_id_for_number(creds: ModulbankCredentials, account_number: str) -> str:
    """id счёта по номеру: в уведомлении есть только номер счёта."""
    if not account_number:
        return ""
    try:
        for _company, account in iter_sync_accounts(get_modulbank_client(creds).get_account_info()):
            if account.get("number") == account_number:
                return account["id"]
    except (ModulbankError, OSError) as e:
        logger.warning("modulbank_webhook: account lookup failed: %s", e)
    return account_number


@xframe_options_exempt
@csrf_exempt
@require_POST
def modulbank_webhook(request, webhook_key: str):
    """Уведомление Модульбанка о новой операции.

    Адрес у каждого портала свой (ключ в пути), подпись SHA1Hash проверяем
    по ключу API этого портала.
    """
    creds = ModulbankCredentials.objects.filter(webhook_key=webhook_key, is_connected=True).first()
    if not creds:
        return JsonResponse({"ok": False}, status=404)
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False}, status=400)

    operation = payload.get("operation") or {}
    if not verify_webhook_signature(creds.api_token, str(operation.get("id") or ""), payload.get("SHA1Hash")):
        return JsonResponse({"ok": False}, status=401)

    account_id = _account_id_for_number(creds, operation.get("bankAccountNumber") or "")
    payment, created = upsert_operation(creds.member_id, operation, account_id)
    if payment is not None:
        new_ids = [payment.pk] if created and payment.credit_debit == "credit" else []
        run_post_sync_processing(creds.member_id, {"new_payment_ids": new_ids})
    return JsonResponse({"ok": True})
