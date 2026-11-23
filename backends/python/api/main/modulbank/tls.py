"""Доверенные сертификаты для запросов к Модульбанку.

api.modulbank.ru отдаёт цепочку от корневого сертификата НУЦ Минцифры
(Russian Trusted Root CA), которого нет в стандартном наборе certifi. Поэтому
проверку TLS не отключаем, а собираем бандл: certifi + сертификаты Минцифры
из ``certs/russian_trusted_ca.pem``. Путь к своему бандлу можно задать через
переменную окружения MODULBANK_CA_BUNDLE.
"""
from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from pathlib import Path

import certifi
import requests

RUSSIAN_CA_PATH = Path(__file__).with_name("certs") / "russian_trusted_ca.pem"


@lru_cache(maxsize=1)
def ca_bundle_path() -> str:
    override = os.environ.get("MODULBANK_CA_BUNDLE", "").strip()
    if override:
        return override
    data = Path(certifi.where()).read_text(encoding="utf-8") + "\n" + RUSSIAN_CA_PATH.read_text(encoding="utf-8")
    fd, path = tempfile.mkstemp(prefix="modulbank-ca-", suffix=".pem")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(data)
    return path


def session() -> requests.Session:
    """Сессия requests с бандлом, где есть сертификаты Минцифры."""
    s = requests.Session()
    s.verify = ca_bundle_path()
    return s
