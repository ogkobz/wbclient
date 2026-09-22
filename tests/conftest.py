"""Общие заготовки для тестов.

Сети здесь нет ни в одном тесте: транспорт и часы подменяются.
"""

from __future__ import annotations

import base64
import json
import time

import pytest

from wbclient.client import Response
from wbclient.token import CATEGORY_BITS


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def make_token(
    *,
    categories=("content",),
    acc: int = 1,
    read_only: bool = False,
    expires_in: int = 180 * 24 * 3600,
    seller_id: str = "test-seller",
    extra: dict | None = None,
) -> str:
    """Собирает JWT-подобную строку с нужной маской доступа.

    Подпись фиктивная: клиент её не проверяет, ключ есть только у WB.
    """
    bit_by_name = {name: bit for bit, name in CATEGORY_BITS.items()}
    mask = 0
    for name in categories:
        mask |= 1 << bit_by_name[name]
    if read_only:
        mask |= 1 << 30

    payload = {
        "acc": acc,
        "s": mask,
        "exp": int(time.time()) + expires_in,
        "sid": seller_id,
        "id": "token-id",
    }
    payload.update(extra or {})

    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64url(json.dumps(payload).encode())
    return f"{header}.{body}.{_b64url(b'signature')}"


class FakeTransport:
    """Отдаёт заранее заданные ответы и запоминает вызовы."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, *, headers, params, json, timeout):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "params": params,
                "json": json,
                "timeout": timeout,
            }
        )
        if not self.responses:
            raise AssertionError(f"Лишний запрос: {method} {url}")
        item = self.responses.pop(0)
        return item() if callable(item) else item


def ok(json_body=None, headers=None) -> Response:
    return Response(status=200, headers=headers or {}, json=json_body)


def fail(status: int, json_body=None, headers=None) -> Response:
    return Response(status=status, headers=headers or {}, json=json_body)


class FakeClock:
    """Монотонные часы, которые двигает только тест."""

    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()
