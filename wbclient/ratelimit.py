"""Соблюдение лимитов WB API.

WB использует token bucket и сам сообщает состояние корзины в заголовках
ответа. Поэтому клиент не угадывает паузы, а идёт за сервером:

    X-Ratelimit-Remaining — сколько запросов можно сделать прямо сейчас
    X-Ratelimit-Retry     — через сколько секунд повторить (только при 429)
    X-Ratelimit-Reset     — через сколько секунд корзина восстановится
    X-Ratelimit-Limit     — максимальный размер всплеска

Две детали, на которых ломаются наивные клиенты:

1. Ответ 4XX в некоторых категориях списывается как ДЕСЯТЬ запросов.
   Поток опечаток в параметрах выжигает бюджет в десять раз быстрее,
   чем ожидаешь по счётчику запросов.

2. Лимит действует на аккаунт продавца и отдельно для каждого домена.
   Общий счётчик на весь клиент занижал бы скорость, один на всех —
   приводил бы к 429. Поэтому корзина своя на каждый домен.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class BucketState:
    """Что известно про корзину конкретного домена."""

    remaining: int | None = None
    limit: int | None = None
    reset_after: float | None = None
    updated_at: float = 0.0
    next_allowed_at: float = 0.0


class RateLimiter:
    """Хранит состояние корзин и выдерживает интервалы между запросами.

    Потокобезопасен: один клиент может использоваться из нескольких потоков.
    """

    def __init__(self, min_interval: float = 0.2, *, clock=time.monotonic,
                 sleep=time.sleep):
        """
        min_interval — пауза между запросами к одному домену.
            По умолчанию 0.2 секунды: это интервал для лимита
            300 запросов в минуту, самый частый в документации WB.
        clock и sleep вынесены в параметры, чтобы тесты не ждали реального времени.
        """
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._buckets: dict[str, BucketState] = {}
        self._lock = threading.Lock()

    def bucket(self, domain: str) -> BucketState:
        with self._lock:
            return self._buckets.setdefault(domain, BucketState())

    def before_request(self, domain: str) -> float:
        """Выжидает свою очередь. Возвращает, сколько пришлось ждать."""
        with self._lock:
            state = self._buckets.setdefault(domain, BucketState())
            now = self._clock()
            wait = max(0.0, state.next_allowed_at - now)
            # Резервируем слот сразу, чтобы параллельные потоки не стартовали вместе.
            state.next_allowed_at = max(now, state.next_allowed_at) + self.min_interval

        if wait > 0:
            self._sleep(wait)
        return wait

    def update_from_headers(self, domain: str, headers) -> None:
        """Подтягивает состояние корзины из ответа."""
        remaining = _int_header(headers, "X-Ratelimit-Remaining")
        limit = _int_header(headers, "X-Ratelimit-Limit")
        reset_after = _float_header(headers, "X-Ratelimit-Reset")

        with self._lock:
            state = self._buckets.setdefault(domain, BucketState())
            if remaining is not None:
                state.remaining = remaining
            if limit is not None:
                state.limit = limit
            if reset_after is not None:
                state.reset_after = reset_after
            state.updated_at = self._clock()

            # Корзина пуста — дальше без паузы будет 429. Ждём восстановления,
            # а если сервер не сказал сколько — хотя бы один интервал.
            if remaining == 0:
                delay = reset_after if reset_after is not None else self.min_interval
                state.next_allowed_at = max(
                    state.next_allowed_at, self._clock() + delay
                )

    def penalize(self, domain: str, retry_after: float) -> None:
        """Отодвигает следующий запрос после 429 на указанное сервером время."""
        with self._lock:
            state = self._buckets.setdefault(domain, BucketState())
            state.remaining = 0
            state.next_allowed_at = max(
                state.next_allowed_at, self._clock() + retry_after
            )


def _int_header(headers, name: str) -> int | None:
    raw = _get_header(headers, name)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _float_header(headers, name: str) -> float | None:
    raw = _get_header(headers, name)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _get_header(headers, name: str):
    if hasattr(headers, "get"):
        value = headers.get(name)
        if value is not None:
            return value
    lowered = name.lower()
    for key, value in dict(headers).items():
        if str(key).lower() == lowered:
            return value
    return None
