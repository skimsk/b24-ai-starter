"""PNG-аватар чат-бота: знак Модульбанка (сетка 5×5) на белом фоне.

Имена функций оставлены прежними: их вызывает общий код бота уведомлений.
"""

from __future__ import annotations

import base64
import io
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

AVATAR_SIZE = 256
# Знак занимает ~60% стороны: UI Битрикс обрезает квадрат по кругу.
MARK_FRACTION = 0.6
BACKGROUND = (255, 255, 255, 255)

_L, _N, _Y, _G, _B = "#5acef6", "#02245d", "#d0d501", "#5eb900", "#0299e5"
MODULBANK_MARK_GRID = (
    (_L, None, _N, _L, None),
    (_Y, _G, None, _B, _G),
    (None, _L, _Y, None, _L),
    (_N, _B, None, _Y, None),
    (_L, None, _G, None, _B),
)


def build_tochka_chat_bot_avatar_png_bytes() -> bytes | None:
    """Квадратный PNG со знаком Модульбанка для properties.avatar (Base64 в REST)."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        logger.warning("Pillow not installed; chat bot avatar skipped")
        return None

    canvas = Image.new("RGBA", (AVATAR_SIZE, AVATAR_SIZE), BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    cell = int(AVATAR_SIZE * MARK_FRACTION) // 5
    offset = (AVATAR_SIZE - cell * 5) // 2
    for y, row in enumerate(MODULBANK_MARK_GRID):
        for x, fill in enumerate(row):
            if fill:
                x0, y0 = offset + x * cell, offset + y * cell
                draw.rectangle((x0, y0, x0 + cell - 1, y0 + cell - 1), fill=fill)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


@lru_cache(maxsize=1)
def tochka_chat_bot_avatar_base64() -> str | None:
    """Base64 без префикса data: — как требует imbot.v2.Bot.register / Bot.update."""
    raw = build_tochka_chat_bot_avatar_png_bytes()
    if not raw:
        return None
    return base64.b64encode(raw).decode("ascii")
