"""Синхронизация операций Модульбанка в общую таблицу банковских платежей.

Операции Модульбанка ложатся в ту же таблицу ``tochka_payments``, что и выписка
Точки. Поэтому сопоставление со сделками и счетами, уведомления, вкладки и
карточки CRM работают без изменений: банк меняется только на входе.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo

from django.utils import timezone as dj_tz

from .datetime_utils import normalize_model_datetimes
from .models import ModulbankCredentials, TochkaPayment, TochkaPortalPreferences
from .modulbank import ModulbankClient
from .modulbank.client import CATEGORY_INCOMING
from .tochka_sync_logic import _extract_invoice_number, _extract_vat

MOSCOW = ZoneInfo("Europe/Moscow")

# Счета, по которым забираем выписку. Транзитный счёт пропускаем: деньги с него
# переходят на расчётный, и одно поступление посчиталось бы дважды.
SYNC_ACCOUNT_CATEGORIES = {"CheckingAccount", "CardAccount"}
INACTIVE_ACCOUNT_STATUSES = {"Deleted", "Closed"}

# Отклонённые и отменённые операции в CRM не заносим.
SKIPPED_OPERATION_STATUSES = {"RejectByBank", "Canceled"}

CURRENCY_MAP = {"RUR": "RUB"}


def get_modulbank_client(creds: ModulbankCredentials) -> ModulbankClient:
    return ModulbankClient(creds.api_token, sandbox=creds.sandbox)


def get_connected_credentials(member_id: str) -> ModulbankCredentials | None:
    return ModulbankCredentials.objects.filter(member_id=member_id, is_connected=True).first()


def parse_modulbank_datetime(value: str | None) -> datetime:
    """Время в API приходит без зоны (``2016-04-01T00:00:00``) — это московское время."""
    if not value:
        return dj_tz.now()
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return dj_tz.now()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=MOSCOW)
    return parsed


def iter_sync_accounts(account_info: Iterable[dict]) -> Iterable[tuple[dict, dict]]:
    """(компания, счёт) для счетов, по которым нужна выписка."""
    for company in account_info or []:
        for account in company.get("bankAccounts") or []:
            if not account.get("id"):
                continue
            if account.get("category") not in SYNC_ACCOUNT_CATEGORIES:
                continue
            if account.get("status") in INACTIVE_ACCOUNT_STATUSES:
                continue
            yield company, account


def operation_to_payment_fields(operation: dict, bank_account_id: str) -> dict:
    """Поля TochkaPayment из операции Модульбанка."""
    incoming = operation.get("category") == CATEGORY_INCOMING
    purpose = operation.get("paymentPurpose") or ""
    amount = operation.get("amount") or 0
    currency = operation.get("currency") or "RUR"
    return {
        "account_id": bank_account_id,
        "payment_slip_number": (str(operation.get("docNumber")).strip() or None) if operation.get("docNumber") else None,
        "amount": float(amount),
        "amount_nat": None,
        "currency": CURRENCY_MAP.get(currency, currency)[:3],
        # Как у Точки: credit — поступление на наш счёт, debit — списание.
        "credit_debit": "credit" if incoming else "debit",
        "counterparty_name": (operation.get("contragentName") or "")[:255],
        "counterparty_inn": (operation.get("contragentInn") or "")[:12],
        "counterparty_account": operation.get("contragentBankAccountNumber") or "",
        "counterparty_bik": (operation.get("contragentBankBic") or "")[:9],
        "purpose": purpose,
        "invoice_number": _extract_invoice_number(purpose),
        "vat_type": _extract_vat(purpose),
        "transaction_date": parse_modulbank_datetime(operation.get("executed") or operation.get("created")),
    }


def upsert_operation(member_id: str, operation: dict, bank_account_id: str) -> tuple[TochkaPayment | None, bool]:
    """Создать или обновить платёж по операции. Возвращает (платёж, создан ли)."""
    op_id = operation.get("id")
    if not op_id or operation.get("status") in SKIPPED_OPERATION_STATUSES:
        return None, False

    fields = operation_to_payment_fields(operation, bank_account_id)
    existing = TochkaPayment.objects.filter(member_id=member_id, transaction_id=op_id).first()
    if existing:
        TochkaPayment.objects.filter(pk=existing.pk).update(**fields)
        return existing, False

    payment = TochkaPayment(member_id=member_id, transaction_id=op_id, created_at=dj_tz.now(), **fields)
    normalize_model_datetimes(payment)
    payment.save(force_insert=True)
    return payment, True


def _period(days: int | None, start_date_calendar: str | None, end_date_calendar: str | None) -> tuple[date, date]:
    if start_date_calendar and end_date_calendar:
        try:
            d_start = datetime.strptime(str(start_date_calendar)[:10], "%Y-%m-%d").date()
            d_end = datetime.strptime(str(end_date_calendar)[:10], "%Y-%m-%d").date()
        except ValueError as e:
            raise ValueError("Некорректные startDate или endDate (ожидается YYYY-MM-DD)") from e
        if d_start > d_end:
            raise ValueError("startDate не может быть позже endDate")
        return d_start, d_end
    d = max(int(days) if days is not None else 30, 1)
    today = dj_tz.now().astimezone(MOSCOW).date()
    return today - timedelta(days=d), today


def run_modulbank_sync(
    member_id: str,
    *,
    days: int | None = None,
    start_date_calendar: str | None = None,
    end_date_calendar: str | None = None,
) -> dict:
    """Забрать операции по всем счетам портала и сохранить их как платежи.

    Возвращает тот же словарь, что run_tochka_sync, чтобы дальше отработала
    общая пост-обработка (run_post_sync_processing): сопоставление и уведомления.
    """
    creds = get_connected_credentials(member_id)
    if not creds:
        raise ValueError("Модульбанк не подключён")

    date_from, date_till = _period(days, start_date_calendar, end_date_calendar)
    client = get_modulbank_client(creds)

    total_synced = 0
    new_payment_ids: list = []
    for _company, account in iter_sync_accounts(client.get_account_info()):
        account_id = account["id"]
        for operation in client.iter_operations(account_id, date_from=date_from, date_till=date_till):
            payment, created = upsert_operation(member_id, operation, account_id)
            if payment is None:
                continue
            total_synced += 1
            if created and payment.credit_debit == "credit":
                new_payment_ids.append(payment.pk)

    last_sync_utc = dj_tz.now()
    TochkaPortalPreferences.objects.get_or_create(member_id=member_id)
    TochkaPortalPreferences.objects.filter(member_id=member_id).update(last_sync_at=last_sync_utc)

    return {
        "synced": total_synced,
        "lastSync": last_sync_utc.isoformat().replace("+00:00", "Z"),
        "new_payment_ids": new_payment_ids,
    }
