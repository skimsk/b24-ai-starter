"""Интернет-эквайринг Модульбанка (pay.modulbank.ru).

Протокол взят из официальных плагинов банка (github.com/modulbank-pay):
- оплата — POST-форма на https://pay.modulbank.ru/pay/ с полями заказа и подписью;
- банк присылает результат POST-формой на callback_url (state=COMPLETE — оплачено);
- статус транзакции: GET /api/v1/transaction/?transaction_id=…;
- возврат: POST /api/v1/refund.

Подпись: ключи по алфавиту, непустые значения кроме signature, «key=base64(value)»
через «&», затем дважды sha1(secret_key + data).
Доступы — Merchant ID и секретный ключ из ЛК эквайринга Модульбанка; это не ключ API
выписки, эквайринг подключается в банке отдельно.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import string
import time
from decimal import Decimal
from typing import Any, Mapping

import requests

from . import tls

PAY_HOST = "https://pay.modulbank.ru"
PAY_FORM_URL = f"{PAY_HOST}/pay/"
TRANSACTION_URL = f"{PAY_HOST}/api/v1/transaction/"
REFUND_URL = f"{PAY_HOST}/api/v1/refund"

# Способы оплаты на странице банка (show_payment_methods в официальном плагине).
SUPPORTED_PAYMENT_METHODS = ("card", "sbp", "applepay", "googlepay")

STATE_COMPLETE = "COMPLETE"
STATE_AUTHORIZED = "AUTHORIZED"
FAILED_STATES = {"FAILED", "REJECTED", "CANCELED", "CANCELLED"}

_SALT_ALPHABET = string.ascii_letters + string.digits


class ModulbankAcquiringError(Exception):
    pass


def _value_to_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (Decimal, float)):
        return format_amount(value)
    return str(value)


def format_amount(value: Any) -> str:
    return f"{Decimal(str(value)).quantize(Decimal('0.01'))}"


def signature(params: Mapping[str, Any], secret_key: str) -> str:
    chunks = []
    for key in sorted(params):
        if key == "signature":
            continue
        value = _value_to_str(params[key])
        if value == "":
            continue
        chunks.append(f"{key}={base64.b64encode(value.encode()).decode()}")
    data = "&".join(chunks)
    for _ in range(2):
        data = hashlib.sha1((secret_key + data).encode()).hexdigest()
    return data


def is_signature_correct(params: Mapping[str, Any], secret_key: str) -> bool:
    sent = params.get("signature")
    if not sent or not secret_key:
        return False
    return hmac.compare_digest(signature(params, secret_key), str(sent).lower())


def _salt(length: int = 32) -> str:
    return "".join(secrets.choice(_SALT_ALPHABET) for _ in range(length))


def compose_payment_form(
    *,
    merchant_id: str,
    secret_key: str,
    testing: bool,
    amount: Any,
    order_id: str,
    description: str,
    success_url: str,
    fail_url: str,
    callback_url: str,
    payment_methods: list[str] | None = None,
    client_email: str = "",
    client_phone: str = "",
    client_name: str = "",
    meta: str = "",
) -> dict[str, str]:
    """Поля формы оплаты с подписью. Метку времени и соль берём свежие на каждое открытие."""
    form: dict[str, str] = {
        "testing": "1" if testing else "0",
        "merchant": merchant_id,
        "unix_timestamp": str(int(time.time())),
        "salt": _salt(),
        "amount": format_amount(amount),
        "currency": "RUB",
        "description": description,
        "order_id": order_id,
        "client_email": client_email,
        "client_name": client_name,
        "client_phone": client_phone,
        "success_url": success_url,
        "fail_url": fail_url,
        "cancel_url": fail_url,
        "callback_url": callback_url,
        "meta": meta,
        "sysinfo": json.dumps({"json_enabled": True, "language": "Python", "plugin": "b24-modulbank-app"}),
    }
    methods = [m for m in (payment_methods or []) if m in SUPPORTED_PAYMENT_METHODS]
    if methods:
        form["show_payment_methods"] = json.dumps(methods)
    form["signature"] = signature(form, secret_key)
    return form


def get_transaction(merchant_id: str, secret_key: str, transaction_id: str, timeout: int = 20) -> dict | None:
    """Данные транзакции или None, если банк не вернул status=ok."""
    params = {
        "transaction_id": transaction_id,
        "merchant": merchant_id,
        "unix_timestamp": str(int(time.time())),
        "salt": _salt(),
    }
    params["signature"] = signature(params, secret_key)
    resp = requests.get(TRANSACTION_URL, params=params, timeout=timeout, verify=tls.ca_bundle_path())
    try:
        data = resp.json()
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("status") != "ok":
        return None
    tx = data.get("transaction")
    return tx if isinstance(tx, dict) else None


def refund(merchant_id: str, secret_key: str, transaction_id: str, amount: Any, timeout: int = 30) -> dict:
    data = {
        "transaction": transaction_id,
        "amount": format_amount(amount),
        "merchant": merchant_id,
        "salt": _salt(),
        "unix_timestamp": str(int(time.time())),
    }
    data["signature"] = signature(data, secret_key)
    resp = requests.post(REFUND_URL, data=data, timeout=timeout, verify=tls.ca_bundle_path())
    try:
        body = resp.json()
    except ValueError as e:
        raise ModulbankAcquiringError(f"Модульбанк вернул не JSON: {resp.text[:200]}") from e
    if not isinstance(body, dict) or body.get("status") != "ok":
        message = body.get("message") if isinstance(body, dict) else None
        raise ModulbankAcquiringError(message or "Модульбанк отклонил возврат")
    return body


def internal_status(state: str | None) -> str:
    """Статус операции в приложении по state банка."""
    raw = (state or "").upper()
    if raw == STATE_COMPLETE:
        return "paid"
    if raw == STATE_AUTHORIZED:
        return "authorized"
    if raw in FAILED_STATES:
        return "cancelled"
    return "pending"
