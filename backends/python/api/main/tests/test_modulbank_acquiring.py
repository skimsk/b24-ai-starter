import base64
import hashlib
import json
import os
import unittest
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")

import django

django.setup()

from django.test import RequestFactory

from main import views_modulbank_acquiring as views
from main.modulbank import acquiring as acq

SECRET = "secret-key"


def php_signature(params, secret):
    """Алгоритм get_signature из официального PHP-плагина Модульбанка, по шагам."""
    chunks = []
    for k in sorted(params):
        v = str(params[k])
        if v != "" and k != "signature":
            chunks.append(k + "=" + base64.b64encode(v.encode()).decode())
    data = "&".join(chunks)
    for _ in range(2):
        data = hashlib.sha1((secret + data).encode()).hexdigest()
    return data


class SignatureTest(unittest.TestCase):
    def test_matches_plugin_algorithm_and_skips_empty_and_signature(self):
        params = {"merchant": "m-1", "amount": "100.00", "order_id": "42", "client_email": "", "signature": "x",
                  "description": "Оплата сделки #7"}
        self.assertEqual(acq.signature(params, SECRET), php_signature(params, SECRET))
        without_empty = {k: v for k, v in params.items() if k not in ("client_email", "signature")}
        self.assertEqual(acq.signature(params, SECRET), acq.signature(without_empty, SECRET))

    def test_is_signature_correct(self):
        params = {"merchant": "m-1", "amount": "100.00", "order_id": "42", "state": "COMPLETE"}
        params["signature"] = acq.signature(params, SECRET)
        self.assertTrue(acq.is_signature_correct(params, SECRET))
        self.assertFalse(acq.is_signature_correct({**params, "amount": "1.00"}, SECRET))
        self.assertFalse(acq.is_signature_correct(params, "other"))

    def test_compose_form_is_signed_and_filters_methods(self):
        form = acq.compose_payment_form(
            merchant_id="m-1", secret_key=SECRET, testing=True, amount=Decimal("1500"), order_id="op-1",
            description="Оплата", success_url="https://a/s", fail_url="https://a/f", callback_url="https://a/c",
            payment_methods=["card", "sbp", "dolyame"],
        )
        self.assertEqual(form["amount"], "1500.00")
        self.assertEqual(form["testing"], "1")
        self.assertEqual(json.loads(form["show_payment_methods"]), ["card", "sbp"])
        self.assertTrue(acq.is_signature_correct(form, SECRET))

    def test_internal_status(self):
        self.assertEqual(acq.internal_status("COMPLETE"), "paid")
        self.assertEqual(acq.internal_status("AUTHORIZED"), "authorized")
        self.assertEqual(acq.internal_status("FAILED"), "cancelled")
        self.assertEqual(acq.internal_status("PROCESSING"), "pending")


def _op(status="pending", amount="1500.00"):
    op = MagicMock()
    op.id = uuid.UUID("11111111-2222-3333-4444-555555555555")
    op.pk = op.id
    op.member_id = "m1"
    op.amount = Decimal(amount)
    op.status = status
    op.purpose = "Оплата сделки #7"
    op.payment_modes_requested = ["card", "sbp"]
    return op


CREDS = SimpleNamespace(acquiring_merchant_id="m-1", acquiring_secret_key=SECRET, acquiring_testing=False,
                        acquiring_configured=True)


def _callback_data(op, **overrides):
    data = {"order_id": str(op.id), "merchant": "m-1", "amount": "1500.00", "currency": "RUB",
            "state": "COMPLETE", "transaction_id": "tx-9", "testing": "0"}
    data.update(overrides)
    data["signature"] = acq.signature(data, SECRET)
    return data


class CallbackTest(unittest.TestCase):
    def _post(self, data, op):
        request = RequestFactory().post("/api/modulbank/acquiring/callback", data=data)
        with patch.object(views, "TochkaAcquiringOperation") as model, \
                patch.object(views, "_creds", return_value=CREDS), \
                patch("main.views_acquiring._dedupe_bank_payment_for_acquiring") as dedupe, \
                patch("main.views_acquiring._push_uf_after_paid") as push, \
                patch.object(views.transaction, "atomic", MagicMock()):
            model.objects.select_for_update.return_value.filter.return_value.first.return_value = op
            response = views.modulbank_acquiring_callback(request)
        return response, dedupe, push

    def test_paid_callback_marks_operation_and_runs_crm_steps(self):
        op = _op()
        response, dedupe, push = self._post(_callback_data(op), op)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.decode().startswith("OK"))
        self.assertEqual(op.status, "paid")
        self.assertEqual(op.external_operation_id, "tx-9")
        dedupe.assert_called_once_with(op)
        push.assert_called_once_with(op)

    def test_bad_signature_rejected(self):
        op = _op()
        data = _callback_data(op)
        data["signature"] = "0" * 40
        response, dedupe, _ = self._post(data, op)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(op.status, "pending")
        dedupe.assert_not_called()

    def test_amount_mismatch_rejected(self):
        op = _op()
        response, dedupe, _ = self._post(_callback_data(op, amount="1.00"), op)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(op.status, "pending")
        dedupe.assert_not_called()

    def test_test_payment_rejected_on_live_settings(self):
        op = _op()
        response, _, _ = self._post(_callback_data(op, testing="1"), op)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(op.status, "pending")

    def test_late_failure_does_not_revert_paid(self):
        op = _op(status="paid")
        response, dedupe, _ = self._post(_callback_data(op, state="FAILED"), op)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(op.status, "paid")
        dedupe.assert_not_called()


class PayPageTest(unittest.TestCase):
    def _get(self, op):
        request = RequestFactory().get(f"/api/modulbank/pay/{op.id}")
        with patch.object(views, "TochkaAcquiringOperation") as model, patch.object(views, "_creds", return_value=CREDS):
            model.objects.filter.return_value.first.return_value = op
            return views.modulbank_pay_page(request, op.id)

    def test_pending_renders_signed_autosubmit_form(self):
        html = self._get(_op()).content.decode()
        self.assertIn('action="https://pay.modulbank.ru/pay/"', html)
        self.assertIn('name="signature"', html)
        self.assertIn('name="order_id" value="11111111-2222-3333-4444-555555555555"', html)
        self.assertIn('name="amount" value="1500.00"', html)

    def test_paid_link_does_not_charge_again(self):
        html = self._get(_op(status="paid")).content.decode()
        self.assertIn("Счёт уже оплачен", html)
        self.assertNotIn("pay.modulbank.ru", html)


if __name__ == "__main__":
    unittest.main()
