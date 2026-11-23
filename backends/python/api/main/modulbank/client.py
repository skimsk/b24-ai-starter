"""Клиент API Модульбанка (https://api.modulbank.ru/v1).

Авторизация — Bearer-токен. Для старта используем ключ API, который клиент сам
генерирует в личном кабинете Модульбанка (права account-info и operation-history).
OAuth для Маркета появится после регистрации приложения в банке (api@modulbank.ru):
токен, полученный по OAuth, передаётся сюда же.

Песочница: заголовок ``sandbox: on`` и токен ``sandboxtoken``.
Все методы API — POST с JSON-телом.
"""
from __future__ import annotations

import hashlib
import hmac
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Iterator

import requests

SANDBOX_TOKEN = "sandboxtoken"

# Направление операции в API Модульбанка: Debet — поступление, Credit — списание.
CATEGORY_INCOMING = "Debet"
CATEGORY_OUTGOING = "Credit"

MAX_RECORDS_PER_PAGE = 50


class ModulbankError(Exception):
    """Ошибка ответа API Модульбанка."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ModulbankAuthError(ModulbankError):
    """Токен не принят (отозван, истёк или без нужных прав)."""


class ModulbankClient:
    BASE_URL = "https://api.modulbank.ru/v1"

    def __init__(self, token: str, sandbox: bool = False, timeout: int = 30, session: requests.Session | None = None):
        if not token:
            raise ValueError("Не задан токен Модульбанка")
        self.token = token
        self.sandbox = sandbox
        self.timeout = timeout
        self._http = session or requests.Session()

    @classmethod
    def for_sandbox(cls, **kwargs) -> "ModulbankClient":
        return cls(SANDBOX_TOKEN, sandbox=True, **kwargs)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        if self.sandbox:
            headers["sandbox"] = "on"
        return headers

    def _post(self, path: str, payload: dict | None = None) -> Any:
        response = self._http.post(
            f"{self.BASE_URL}/{path.lstrip('/')}",
            json=payload or {},
            headers=self._headers(),
            timeout=self.timeout,
        )
        if response.status_code in (401, 403):
            raise ModulbankAuthError(
                "Модульбанк не принял ключ API: проверьте, что он не отозван и выдан с нужными правами",
                status_code=response.status_code,
            )
        if response.status_code != 200:
            raise ModulbankError(
                f"Модульбанк вернул {response.status_code}: {response.text[:300]}",
                status_code=response.status_code,
            )
        try:
            return response.json()
        except ValueError as e:
            raise ModulbankError(f"Модульбанк вернул не JSON: {response.text[:300]}") from e

    def get_account_info(self) -> list[dict]:
        """Компании пользователя и их счета (POST /account-info)."""
        data = self._post("account-info")
        if not isinstance(data, list):
            raise ModulbankError("Неожиданный ответ account-info")
        return data

    def get_balance(self, bank_account_id: str) -> Decimal:
        """Остаток по счёту (POST /account-info/balance/{bankAccountId})."""
        data = self._post(f"account-info/balance/{bank_account_id}")
        try:
            return Decimal(str(data))
        except (InvalidOperation, ValueError) as e:
            raise ModulbankError(f"Неожиданный баланс: {data!r}") from e

    def get_operations_page(
        self,
        bank_account_id: str,
        *,
        date_from: date | None = None,
        date_till: date | None = None,
        category: str | None = None,
        skip: int = 0,
        records: int = MAX_RECORDS_PER_PAGE,
    ) -> list[dict]:
        """Одна страница истории операций (POST /operation-history/{bankAccountId})."""
        payload: dict[str, Any] = {"skip": int(skip), "records": min(int(records), MAX_RECORDS_PER_PAGE)}
        if date_from:
            payload["from"] = date_from.strftime("%Y-%m-%d")
        if date_till:
            payload["till"] = date_till.strftime("%Y-%m-%d")
        if category:
            payload["category"] = category
        data = self._post(f"operation-history/{bank_account_id}", payload)
        if not isinstance(data, list):
            raise ModulbankError("Неожиданный ответ operation-history")
        return data

    def iter_operations(
        self,
        bank_account_id: str,
        *,
        date_from: date | None = None,
        date_till: date | None = None,
        category: str | None = None,
        max_pages: int = 200,
    ) -> Iterator[dict]:
        """Все операции за период, страницами по 50."""
        skip = 0
        for _ in range(max_pages):
            page = self.get_operations_page(
                bank_account_id,
                date_from=date_from,
                date_till=date_till,
                category=category,
                skip=skip,
            )
            yield from page
            if len(page) < MAX_RECORDS_PER_PAGE:
                return
            skip += len(page)


def webhook_signature(token: str, operation_id: str) -> str:
    """Подпись уведомления: SHA1 от «первые 10 символов токена & id операции»."""
    return hashlib.sha1(f"{token[:10]}&{operation_id}".encode()).hexdigest()


def verify_webhook_signature(token: str, operation_id: str, signature: str | None) -> bool:
    if not token or not operation_id or not signature:
        return False
    return hmac.compare_digest(webhook_signature(token, operation_id), str(signature).lower())
