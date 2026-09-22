"""Лимиты. Часы и sleep подменены, тесты не ждут реального времени."""

from __future__ import annotations

import pytest

from wbclient.ratelimit import RateLimiter


def limiter(clock, min_interval=0.2) -> RateLimiter:
    return RateLimiter(min_interval, clock=clock, sleep=clock.sleep)


def test_first_request_goes_without_waiting(clock):
    assert limiter(clock).before_request("content-api.wildberries.ru") == 0.0
    assert clock.slept == []


def test_second_request_waits_min_interval(clock):
    rl = limiter(clock)
    rl.before_request("host")
    assert rl.before_request("host") == pytest.approx(0.2)
    assert clock.slept == pytest.approx([0.2])


def test_domains_have_separate_buckets(clock):
    rl = limiter(clock)
    rl.before_request("content-api.wildberries.ru")
    # Лимит считается на домен: запрос к другому домену не должен ждать.
    assert rl.before_request("advert-api.wildberries.ru") == 0.0


def test_time_passed_means_no_wait(clock):
    rl = limiter(clock)
    rl.before_request("host")
    clock.now += 5
    assert rl.before_request("host") == 0.0


def test_headers_update_bucket_state(clock):
    rl = limiter(clock)
    rl.update_from_headers(
        "host",
        {"X-Ratelimit-Remaining": "42", "X-Ratelimit-Limit": "300", "X-Ratelimit-Reset": "12"},
    )
    state = rl.bucket("host")
    assert state.remaining == 42
    assert state.limit == 300
    assert state.reset_after == 12.0


def test_empty_bucket_waits_until_reset(clock):
    rl = limiter(clock)
    rl.update_from_headers("host", {"X-Ratelimit-Remaining": "0", "X-Ratelimit-Reset": "10"})
    assert rl.before_request("host") == 10.0


def test_empty_bucket_without_reset_waits_min_interval(clock):
    rl = limiter(clock)
    rl.update_from_headers("host", {"X-Ratelimit-Remaining": "0"})
    assert rl.before_request("host") == pytest.approx(0.2)


def test_penalize_pushes_next_request(clock):
    rl = limiter(clock)
    rl.penalize("host", 30.0)
    assert rl.bucket("host").remaining == 0
    assert rl.before_request("host") == 30.0


def test_penalize_never_shortens_existing_pause(clock):
    rl = limiter(clock)
    rl.penalize("host", 30.0)
    rl.penalize("host", 1.0)
    assert rl.before_request("host") == 30.0


def test_unreadable_headers_are_ignored(clock):
    rl = limiter(clock)
    rl.update_from_headers("host", {"X-Ratelimit-Remaining": "много", "X-Ratelimit-Limit": ""})
    state = rl.bucket("host")
    assert state.remaining is None
    assert state.limit is None


def test_headers_case_insensitive(clock):
    rl = limiter(clock)
    rl.update_from_headers("host", {"x-ratelimit-remaining": "5"})
    assert rl.bucket("host").remaining == 5


def test_slots_reserved_in_order(clock):
    """Резерв слота до сна: параллельные потоки не стартуют одновременно."""
    rl = limiter(clock)
    rl.before_request("host")
    first = rl.bucket("host").next_allowed_at
    rl.before_request("host")
    assert rl.bucket("host").next_allowed_at > first
