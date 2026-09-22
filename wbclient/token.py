"""Разбор токена WB API.

Токен — это JWT (RFC 7519). Полезная часть для нас — payload, где лежат
тип токена, срок жизни и битовая маска категорий доступа.

Смысл модуля простой: понять, что токен не подходит для метода, можно
до отправки запроса. Иначе цена ошибки — 403, а он списывается
из лимита как десять обычных запросов.

Подпись здесь НЕ проверяется: ключ известен только WB. Это разбор
собственного токена, а не аутентификация чужого.
"""

from __future__ import annotations

import base64
import binascii
import json
import time
from dataclasses import dataclass, field

# Позиции битов в поле `s` payload'а. Отсчёт от нуля, младший бит первый.
CATEGORY_BITS = {
    1: "content",
    2: "analytics",
    3: "prices",
    4: "marketplace",
    5: "statistics",
    6: "advert",
    7: "feedbacks",
    9: "chat",
    10: "supplies",
    11: "returns",
    12: "documents",
    13: "finance",
    16: "users",
}

READ_ONLY_BIT = 30

# acc → тип токена
TOKEN_TYPES = {
    1: "basic",
    2: "test",
    3: "personal",
    4: "service",
}


class InvalidTokenError(ValueError):
    """Строка не похожа на JWT или payload не читается."""


@dataclass(frozen=True)
class TokenInfo:
    """Что удалось прочитать из токена."""

    token_type: str
    categories: frozenset[str]
    read_only: bool
    expires_at: int | None
    seller_id: str | None = None
    token_id: str | None = None
    raw_payload: dict = field(default_factory=dict, repr=False)

    @property
    def is_sandbox(self) -> bool:
        """Тестовый токен работает только с песочницей."""
        return self.token_type == "test"

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() >= self.expires_at

    @property
    def seconds_left(self) -> int | None:
        if self.expires_at is None:
            return None
        return max(0, int(self.expires_at - time.time()))

    def allows(self, category: str) -> bool:
        """Есть ли у токена доступ к категории методов."""
        return category in self.categories

    def can_write(self, category: str) -> bool:
        return self.allows(category) and not self.read_only


def parse_token(token: str) -> TokenInfo:
    """Читает payload токена WB.

    Токен приходит от пользователя, поэтому любые искажения — обычная
    ситуация, а не исключительная: обрезали при копировании, добавили
    пробелы, скопировали не ту строку.
    """
    if not token or not isinstance(token, str):
        raise InvalidTokenError("Токен пустой")

    cleaned = token.strip()
    if cleaned.lower().startswith("bearer "):
        cleaned = cleaned[7:].strip()

    parts = cleaned.split(".")
    if len(parts) != 3:
        raise InvalidTokenError(
            f"Токен должен состоять из трёх частей через точку, получено {len(parts)}"
        )

    payload = _decode_segment(parts[1])

    mask = payload.get("s")
    categories = _categories_from_mask(mask) if isinstance(mask, int) else frozenset()
    read_only = bool(isinstance(mask, int) and mask >> READ_ONLY_BIT & 1)

    acc = payload.get("acc")
    token_type = TOKEN_TYPES.get(acc, "unknown")
    # Поле `t` дублирует признак песочницы; доверяем ему, если acc не распознан.
    if token_type == "unknown" and payload.get("t") is True:
        token_type = "test"

    exp = payload.get("exp")
    expires_at = int(exp) if isinstance(exp, (int, float)) else None

    return TokenInfo(
        token_type=token_type,
        categories=categories,
        read_only=read_only,
        expires_at=expires_at,
        seller_id=payload.get("sid"),
        token_id=payload.get("id"),
        raw_payload=payload,
    )


def _decode_segment(segment: str) -> dict:
    """base64url без паддинга — обычный формат JWT."""
    padding = "=" * (-len(segment) % 4)
    try:
        raw = base64.urlsafe_b64decode(segment + padding)
    except (binascii.Error, ValueError) as exc:
        raise InvalidTokenError(f"Не удалось раскодировать payload: {exc}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InvalidTokenError(f"Payload не является JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise InvalidTokenError("Payload должен быть объектом JSON")
    return payload


def _categories_from_mask(mask: int) -> frozenset[str]:
    return frozenset(
        name for bit, name in CATEGORY_BITS.items() if mask >> bit & 1
    )
