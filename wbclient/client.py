"""Клиент WB API.

Что он делает сверх обычного requests:

* сам выбирает домен по категории метода — промах даёт 404, а тот
  списывается из лимита как десять запросов;
* проверяет по токену, есть ли доступ к категории, ДО отправки запроса;
* держит паузы и повторы по заголовкам ответа, а не по догадкам;
* различает ошибки, которые лечатся повтором, и те, что не лечатся.

Сетевой слой абстрагирован (`transport`), поэтому клиент тестируется
без сети и без моков библиотеки requests.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .endpoints import get_service, required_category
from .errors import (
    RETRYABLE,
    WBError,
    WBForbiddenError,
    WBRateLimitError,
    error_from_response,
)
from .ratelimit import RateLimiter
from .token import TokenInfo, parse_token

log = logging.getLogger("wbclient")


@dataclass
class Response:
    """Ответ транспорта в независимом от библиотеки виде."""

    status: int
    headers: dict
    json: Any = None


class Transport(Protocol):
    """Минимум, который нужен клиенту от HTTP-слоя."""

    def request(self, method: str, url: str, *, headers: dict,
                params: dict | None, json: Any, timeout: float) -> Response:
        ...


class RequestsTransport:
    """Транспорт на requests. Импорт внутри, чтобы ядро не зависело от него."""

    def __init__(self, session=None):
        import requests  # noqa: PLC0415 — зависимость нужна только здесь

        self._session = session or requests.Session()

    def request(self, method, url, *, headers, params, json, timeout) -> Response:
        resp = self._session.request(
            method, url, headers=headers, params=params, json=json, timeout=timeout
        )
        try:
            body = resp.json() if resp.content else None
        except ValueError:
            # WB иногда отвечает текстом на 5XX — это не повод падать разбором.
            body = None
        return Response(status=resp.status_code, headers=dict(resp.headers), json=body)


class WBClient:
    """Клиент к WB API.

    >>> client = WBClient(token)                      # doctest: +SKIP
    >>> client.get("common", "/ping")                 # doctest: +SKIP
    {'TS': '...', 'Status': 'OK'}
    """

    def __init__(
        self,
        token: str,
        *,
        transport: Transport | None = None,
        limiter: RateLimiter | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        sandbox: bool | None = None,
        check_scopes: bool = True,
        sleep: Callable[[float], None] = time.sleep,
    ):
        """
        sandbox — если не указано, определяется по типу токена:
            тестовый токен работает только с песочницей.
        check_scopes — проверять доступ по токену до отправки запроса.
            Отключать стоит только если payload токена нестандартный.
        """
        self.token = token.strip()
        self.info: TokenInfo | None = None
        try:
            self.info = parse_token(self.token)
        except ValueError as exc:
            # Не падаем: токен может быть валиден для сервера и непривычен для нас.
            log.warning("Токен не удалось разобрать (%s). Проверки доступа отключены.", exc)
            check_scopes = False

        self.sandbox = sandbox if sandbox is not None else bool(
            self.info and self.info.is_sandbox
        )
        self.check_scopes = check_scopes and self.info is not None
        self.transport = transport or RequestsTransport()
        self.limiter = limiter or RateLimiter()
        self.timeout = timeout
        self.max_retries = max_retries
        self._sleep = sleep

    # --- публичные методы -------------------------------------------------

    def get(self, service: str, path: str, *, params: dict | None = None) -> Any:
        return self.request("GET", service, path, params=params)

    def post(self, service: str, path: str, *, json: Any = None,
             params: dict | None = None) -> Any:
        return self.request("POST", service, path, json=json, params=params)

    def put(self, service: str, path: str, *, json: Any = None) -> Any:
        return self.request("PUT", service, path, json=json)

    def delete(self, service: str, path: str, *, params: dict | None = None) -> Any:
        return self.request("DELETE", service, path, params=params)

    def ping(self, service: str = "common") -> Any:
        """Проверка связи и токена. Есть у каждого домена свой вариант."""
        return self.get(service, "/ping")

    def request(self, method: str, service: str, path: str, *,
                params: dict | None = None, json: Any = None) -> Any:
        """Выполняет запрос с учётом лимитов и повторов."""
        svc = get_service(service)
        self._ensure_access(service, method)

        url = svc.base_url(self.sandbox) + path
        headers = {
            "Authorization": self.token,
            "Accept": "application/json",
        }
        domain = svc.sandbox_host if self.sandbox else svc.host

        last_error: WBError | None = None
        for attempt in range(1, self.max_retries + 1):
            self.limiter.before_request(domain)
            resp = self.transport.request(
                method, url, headers=headers, params=params,
                json=json, timeout=self.timeout,
            )
            self.limiter.update_from_headers(domain, resp.headers)

            if 200 <= resp.status < 300:
                return resp.json

            error = error_from_response(resp.status, resp.json, resp.headers)

            if isinstance(error, WBRateLimitError):
                self.limiter.penalize(domain, error.retry_after)

            if not isinstance(error, RETRYABLE) or attempt == self.max_retries:
                raise error

            delay = (
                error.retry_after
                if isinstance(error, WBRateLimitError)
                else _backoff(attempt)
            )
            log.info(
                "%s %s -> %s. Повтор %s из %s через %.1f с",
                method, path, resp.status, attempt, self.max_retries, delay,
            )
            self._sleep(delay)
            last_error = error

        # Недостижимо: последняя попытка выбрасывает исключение выше.
        raise last_error or WBError("Запрос не выполнен")

    # --- внутреннее -------------------------------------------------------

    def _ensure_access(self, service: str, method: str) -> None:
        """Ловит заведомо провальные запросы до обращения к сети.

        Цена такого запроса на сервере — десять единиц лимита,
        поэтому дешевле отказать локально.
        """
        if not self.check_scopes or self.info is None:
            return

        if self.info.is_expired:
            raise WBForbiddenError(
                "Срок действия токена истёк. Создайте новый в личном кабинете."
            )

        category = required_category(service)
        if category is None:
            return  # common доступен с токеном любой категории

        if not self.info.allows(category):
            available = ", ".join(sorted(self.info.categories)) or "нет ни одной"
            raise WBForbiddenError(
                f"У токена нет доступа к категории «{category}». "
                f"Доступные категории: {available}."
            )

        if method.upper() != "GET" and self.info.read_only:
            raise WBForbiddenError(
                f"Токен создан только для чтения, метод {method} недоступен."
            )


def _backoff(attempt: int) -> float:
    """Экспоненциальная задержка для 5XX: 1, 2, 4 секунды."""
    return float(2 ** (attempt - 1))
