"""Исключения WB API.

Коды разделены по смыслу: на одни имеет смысл повторить запрос,
на другие — нет. Клиент принимает решение о ретрае по типу исключения,
а не по числовому коду.
"""

from __future__ import annotations


class WBError(Exception):
    """Базовая ошибка WB API."""

    def __init__(self, message: str, *, status: int | None = None,
                 detail: str | None = None, request_id: str | None = None):
        super().__init__(message)
        self.status = status
        self.detail = detail
        self.request_id = request_id

    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.detail:
            parts.append(f"detail: {self.detail}")
        if self.request_id:
            parts.append(f"requestId: {self.request_id}")
        return ". ".join(parts)


class WBAuthError(WBError):
    """401 — токен отсутствует, просрочен или некорректен. Повтор не поможет."""


class WBForbiddenError(WBError):
    """403 — категория токена не совпадает с категорией метода.

    Чаще всего означает, что токен создан без нужной категории доступа.
    Проверить состав категорий можно заранее: см. wbclient.token.
    """


class WBPaymentRequiredError(WBError):
    """402 — недостаточно средств на балансе сервиса."""


class WBNotFoundError(WBError):
    """404 — неверный URL метода."""


class WBValidationError(WBError):
    """400, 409, 422 — запрос не прошёл проверку. Повтор без правок бесполезен."""


class WBPayloadTooLargeError(WBError):
    """413 — слишком много объектов в запросе. Нужно уменьшить батч."""


class WBRateLimitError(WBError):
    """429 — превышена скорость запросов.

    WB присылает в заголовках, сколько ждать, поэтому клиенту не нужно
    угадывать задержку: retry_after берётся из X-Ratelimit-Retry.
    """

    def __init__(self, message: str, *, retry_after: float = 1.0,
                 reset_after: float | None = None, limit: int | None = None,
                 **kwargs):
        super().__init__(message, status=429, **kwargs)
        self.retry_after = retry_after
        self.reset_after = reset_after
        self.limit = limit


class WBServerError(WBError):
    """5XX — сбой на стороне WB. Имеет смысл повторить позже."""


# Коды, при которых повтор запроса осмыслен.
RETRYABLE = (WBRateLimitError, WBServerError)


def error_from_response(status: int, body: dict | None, headers: dict) -> WBError:
    """Собирает исключение по ответу WB.

    Поля title/detail/requestId WB отдаёт не всегда, поэтому их отсутствие
    не должно ломать разбор ошибки.
    """
    body = body or {}
    title = body.get("title") or body.get("message") or f"HTTP {status}"
    detail = body.get("detail") or body.get("details")
    request_id = body.get("requestId")

    common = {"status": status, "detail": detail, "request_id": request_id}

    if status == 401:
        return WBAuthError(title, **common)
    if status == 402:
        return WBPaymentRequiredError(title, **common)
    if status == 403:
        return WBForbiddenError(title, **common)
    if status == 404:
        return WBNotFoundError(title, **common)
    if status == 413:
        return WBPayloadTooLargeError(title, **common)
    if status in (400, 409, 422):
        return WBValidationError(title, **common)
    if status == 429:
        return WBRateLimitError(
            title,
            retry_after=_float_header(headers, "X-Ratelimit-Retry", 1.0),
            reset_after=_float_header(headers, "X-Ratelimit-Reset", None),
            limit=_int_header(headers, "X-Ratelimit-Limit"),
            detail=detail,
            request_id=request_id,
        )
    if status >= 500:
        return WBServerError(title, **common)
    return WBError(title, **common)


def _float_header(headers: dict, name: str, default: float | None) -> float | None:
    raw = _get_header(headers, name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _int_header(headers: dict, name: str) -> int | None:
    raw = _get_header(headers, name)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _get_header(headers: dict, name: str):
    """Заголовки регистронезависимы, а httpx и requests отдают их по-разному."""
    if hasattr(headers, "get"):
        value = headers.get(name)
        if value is not None:
            return value
    lowered = name.lower()
    for key, value in dict(headers).items():
        if str(key).lower() == lowered:
            return value
    return None
