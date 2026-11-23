import json
import os
import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch
from zoneinfo import ZoneInfo

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")

import django

django.setup()

from main.modulbank import ModulbankAuthError, ModulbankClient, ModulbankError, verify_webhook_signature
from main.modulbank.client import SANDBOX_TOKEN, webhook_signature
from main import modulbank_sync_logic as sync

# Формы ответов взяты из примеров API Модульбанка (песочница).
OPERATION_IN = {
    "id": "a4b825ca-a6f8-4996-a1db-a5f3028bb68d",
    "companyId": "599ebe36-ed20-49c4-b802-a5ec0329ebce",
    "status": "Received",
    "category": "Debet",
    "contragentName": "Индивидуальный предприниматель Иванов Иван Иванович",
    "contragentInn": "1111111111",
    "contragentKpp": "",
    "contragentBankAccountNumber": "30101810000000000005",
    "contragentBankName": "МОСКОВСКИЙ ФИЛИАЛ",
    "contragentBankBic": "044583340",
    "currency": "RUR",
    "amount": 100000.0,
    "amountWithCommission": 100000.0,
    "bankAccountNumber": "40702810000000000001",
    "paymentPurpose": "Оплата по счету №4 от 01.04.2016 г. Без НДС",
    "executed": "2016-04-01T10:30:00",
    "created": "2016-04-01T00:00:00",
    "docNumber": "4",
}

ACCOUNT_INFO = [
    {
        "companyId": "599ebe36-ed20-49c4-b802-a5ec0329ebce",
        "companyName": "ИП Петров",
        "Inn": "2222222222",
        "bankAccounts": [
            {"id": "acc-checking", "number": "40702810000000000001", "category": "CheckingAccount", "status": "New", "balance": 10.5},
            {"id": "acc-transit", "number": "40702810000000000002", "category": "TransitAccount", "status": "New", "balance": 1},
            {"id": "acc-closed", "number": "40702810000000000003", "category": "CheckingAccount", "status": "Closed", "balance": 0},
            {"id": "acc-card", "number": "40817810000000000004", "category": "CardAccount", "status": "New", "balance": 2},
        ],
    }
]


def _response(status=200, body=None, text=None):
    r = Mock()
    r.status_code = status
    r.text = text if text is not None else json.dumps(body)
    r.json.side_effect = (lambda: body) if body is not None else ValueError("no json")
    return r


class ModulbankClientTest(unittest.TestCase):
    def _client(self, *responses, sandbox=False):
        session = Mock()
        session.post.side_effect = list(responses)
        return ModulbankClient("tok", sandbox=sandbox, session=session), session

    def test_account_info_sends_bearer_and_json(self):
        client, session = self._client(_response(body=ACCOUNT_INFO))
        self.assertEqual(client.get_account_info(), ACCOUNT_INFO)
        url = session.post.call_args.args[0]
        kwargs = session.post.call_args.kwargs
        self.assertEqual(url, "https://api.modulbank.ru/v1/account-info")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tok")
        self.assertNotIn("sandbox", kwargs["headers"])
        self.assertEqual(kwargs["json"], {})

    def test_sandbox_header_and_token(self):
        client = ModulbankClient.for_sandbox(session=Mock())
        self.assertEqual(client.token, SANDBOX_TOKEN)
        self.assertEqual(client._headers()["sandbox"], "on")

    def test_unauthorized_raises_auth_error(self):
        client, _ = self._client(_response(status=401, text="Unauthorized"))
        with self.assertRaises(ModulbankAuthError):
            client.get_account_info()

    def test_server_error_raises(self):
        client, _ = self._client(_response(status=500, text="oops"))
        with self.assertRaises(ModulbankError):
            client.get_account_info()

    def test_balance_is_decimal(self):
        client, session = self._client(_response(body=1234.56))
        self.assertEqual(str(client.get_balance("acc")), "1234.56")
        self.assertTrue(session.post.call_args.args[0].endswith("/account-info/balance/acc"))

    def test_iter_operations_pages_by_50(self):
        page1 = [{"id": str(i)} for i in range(50)]
        page2 = [{"id": "last"}]
        client, session = self._client(_response(body=page1), _response(body=page2))
        ops = list(client.iter_operations("acc", date_from=date(2026, 11, 1), date_till=date(2026, 11, 20)))
        self.assertEqual(len(ops), 51)
        first, second = [c.kwargs["json"] for c in session.post.call_args_list]
        self.assertEqual(first, {"skip": 0, "records": 50, "from": "2026-11-01", "till": "2026-11-20"})
        self.assertEqual(second["skip"], 50)
        self.assertTrue(session.post.call_args.args[0].endswith("/operation-history/acc"))


class WebhookSignatureTest(unittest.TestCase):
    def test_matches_bank_sample(self):
        # Подпись из примера уведомления Модульбанка для токена песочницы.
        self.assertEqual(
            webhook_signature(SANDBOX_TOKEN, OPERATION_IN["id"]),
            "c039243e64c11635afbc1bd99185e34313702d43",
        )
        self.assertTrue(verify_webhook_signature(SANDBOX_TOKEN, OPERATION_IN["id"], "C039243E64C11635AFBC1BD99185E34313702D43"))

    def test_rejects_wrong_or_missing(self):
        self.assertFalse(verify_webhook_signature(SANDBOX_TOKEN, OPERATION_IN["id"], "deadbeef"))
        self.assertFalse(verify_webhook_signature(SANDBOX_TOKEN, OPERATION_IN["id"], None))
        self.assertFalse(verify_webhook_signature("", OPERATION_IN["id"], "x"))


class OperationMappingTest(unittest.TestCase):
    def test_incoming_operation_maps_to_credit_payment(self):
        f = sync.operation_to_payment_fields(OPERATION_IN, "acc-checking")
        self.assertEqual(f["credit_debit"], "credit")
        self.assertEqual(f["currency"], "RUB")
        self.assertEqual(f["amount"], 100000.0)
        self.assertEqual(f["counterparty_inn"], "1111111111")
        self.assertEqual(f["counterparty_bik"], "044583340")
        self.assertEqual(f["payment_slip_number"], "4")
        self.assertEqual(f["invoice_number"], "4")
        self.assertEqual(f["vat_type"], "Без НДС")
        self.assertEqual(f["account_id"], "acc-checking")
        self.assertEqual(
            f["transaction_date"],
            datetime(2016, 4, 1, 10, 30, tzinfo=ZoneInfo("Europe/Moscow")),
        )

    def test_outgoing_operation_maps_to_debit(self):
        f = sync.operation_to_payment_fields({**OPERATION_IN, "category": "Credit"}, "acc")
        self.assertEqual(f["credit_debit"], "debit")

    def test_only_active_checking_and_card_accounts_are_synced(self):
        ids = [a["id"] for _c, a in sync.iter_sync_accounts(ACCOUNT_INFO)]
        self.assertEqual(ids, ["acc-checking", "acc-card"])

    def test_rejected_operations_are_skipped(self):
        with patch.object(sync, "TochkaPayment") as model:
            payment, created = sync.upsert_operation("m1", {**OPERATION_IN, "status": "RejectByBank"}, "acc")
        self.assertIsNone(payment)
        self.assertFalse(created)
        model.objects.filter.assert_not_called()

    def test_existing_operation_is_updated_not_duplicated(self):
        existing = SimpleNamespace(pk="p1", credit_debit="credit")
        with patch.object(sync, "TochkaPayment") as model:
            model.objects.filter.return_value.first.return_value = existing
            payment, created = sync.upsert_operation("m1", OPERATION_IN, "acc")
        self.assertIs(payment, existing)
        self.assertFalse(created)
        model.objects.filter.assert_any_call(pk="p1")


class RunSyncTest(unittest.TestCase):
    def test_sync_collects_new_incoming_payments(self):
        creds = SimpleNamespace(api_token="tok", sandbox=False)
        client = MagicMock()
        client.get_account_info.return_value = ACCOUNT_INFO
        client.iter_operations.side_effect = lambda account_id, **kw: (
            [OPERATION_IN, {**OPERATION_IN, "id": "out-1", "category": "Credit"}] if account_id == "acc-checking" else []
        )
        created_in = SimpleNamespace(pk="new-in", credit_debit="credit")
        created_out = SimpleNamespace(pk="new-out", credit_debit="debit")

        with patch.object(sync, "get_connected_credentials", return_value=creds), \
                patch.object(sync, "get_modulbank_client", return_value=client), \
                patch.object(sync, "upsert_operation", side_effect=[(created_in, True), (created_out, True)]), \
                patch.object(sync, "TochkaPortalPreferences"):
            result = sync.run_modulbank_sync("m1", start_date_calendar="2026-11-01", end_date_calendar="2026-11-20")

        self.assertEqual(result["synced"], 2)
        self.assertEqual(result["new_payment_ids"], ["new-in"])
        kwargs = client.iter_operations.call_args_list[0].kwargs
        self.assertEqual(kwargs["date_from"], date(2026, 11, 1))
        self.assertEqual(kwargs["date_till"], date(2026, 11, 20))
        self.assertEqual(client.iter_operations.call_count, 2)

    def test_sync_requires_connection(self):
        with patch.object(sync, "get_connected_credentials", return_value=None):
            with self.assertRaises(ValueError):
                sync.run_modulbank_sync("m1")

    def test_bad_period_rejected(self):
        with patch.object(sync, "get_connected_credentials", return_value=SimpleNamespace(api_token="t", sandbox=False)):
            with self.assertRaises(ValueError):
                sync.run_modulbank_sync("m1", start_date_calendar="2026-11-20", end_date_calendar="2026-11-01")


class WebhookViewTest(unittest.TestCase):
    def _post(self, payload, creds):
        from django.test import RequestFactory
        from main import views_modulbank as views

        request = RequestFactory().post(
            "/api/modulbank/webhook/key", data=json.dumps(payload), content_type="application/json",
        )
        with patch.object(views, "ModulbankCredentials") as model, \
                patch.object(views, "_account_id_for_number", return_value="acc-checking"), \
                patch.object(views, "upsert_operation", return_value=(SimpleNamespace(pk="p1", credit_debit="credit"), True)) as upsert, \
                patch.object(views, "run_post_sync_processing") as post:
            model.objects.filter.return_value.first.return_value = creds
            response = views.modulbank_webhook(request, "key")
        return response, upsert, post

    def test_valid_signature_imports_operation(self):
        creds = SimpleNamespace(api_token=SANDBOX_TOKEN, member_id="m1")
        payload = {"operation": OPERATION_IN, "SHA1Hash": "c039243e64c11635afbc1bd99185e34313702d43"}
        response, upsert, post = self._post(payload, creds)
        self.assertEqual(response.status_code, 200)
        upsert.assert_called_once_with("m1", OPERATION_IN, "acc-checking")
        post.assert_called_once_with("m1", {"new_payment_ids": ["p1"]})

    def test_bad_signature_rejected(self):
        creds = SimpleNamespace(api_token=SANDBOX_TOKEN, member_id="m1")
        response, upsert, _ = self._post({"operation": OPERATION_IN, "SHA1Hash": "bad"}, creds)
        self.assertEqual(response.status_code, 401)
        upsert.assert_not_called()

    def test_unknown_key_404(self):
        response, upsert, _ = self._post({"operation": OPERATION_IN}, None)
        self.assertEqual(response.status_code, 404)
        upsert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
