import base64
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")

import django

django.setup()

from main import bitrix_rest
from main import tochka_bot_avatar as av


class BotAvatarTest(unittest.TestCase):
    def test_uses_uploaded_picture(self):
        av.tochka_chat_bot_avatar_base64.cache_clear()
        raw = base64.b64decode(av.tochka_chat_bot_avatar_base64())
        self.assertEqual(raw, av.AVATAR_FILE.read_bytes())
        self.assertTrue(raw.startswith(b"\x89PNG"))

    def test_new_avatar_version_is_pushed_despite_daily_throttle(self):
        bitrix_rest._avatar_push_at.clear()
        with patch.object(bitrix_rest, "bitrix_rest_call", return_value={"result": True}) as call, \
                patch.object(bitrix_rest, "tochka_chat_bot_avatar_version", return_value="v1"):
            bitrix_rest.push_tochka_integration_chat_bot_avatar(object(), 5, "m1")
            bitrix_rest.push_tochka_integration_chat_bot_avatar(object(), 5, "m1")
            self.assertEqual(call.call_count, 1)
        with patch.object(bitrix_rest, "bitrix_rest_call", return_value={"result": True}) as call, \
                patch.object(bitrix_rest, "tochka_chat_bot_avatar_version", return_value="v2"):
            bitrix_rest.push_tochka_integration_chat_bot_avatar(object(), 5, "m1")
            self.assertEqual(call.call_count, 1)
            props = call.call_args[0][2]["fields"]["properties"]
            self.assertEqual(props["name"], "Модульбанк")
            self.assertIn("avatar", props)


if __name__ == "__main__":
    unittest.main()
