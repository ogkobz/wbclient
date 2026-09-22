"""Клиент целиком: домен, права, лимиты, повторы. Сети нет."""

from __future__ import annotations

import pytest

from conftest import FakeTransport, fail, make_token, ok
from wbclient.client import WBClient
from wbclient.endpoints import SandboxUnavailableError, UnknownServiceError
from wbclient.errors import (
    WBAuthError,
    WBForbiddenError,
    WBRateLimitError,
    WBServerError,
    WBValidationError,
)
from wbclient.ratelimit import RateLimiter


def build(responses, *, token=None, clock=None, **kwargs):
    transport = FakeTransport(responses)
    limiter = (
        RateLimiter(0.0, clock=clock, sleep=clock.sleep) if clock else RateLimiter(0.0)
    )
    client = WBClient(
        token or make_token(categories=("content", "prices")),
        transport=transport,
        limiter=limiter,
        sleep=clock.sleep if clock else (lambda _: None),
        **kwargs,
    )
    return client, transport


# --- маршрутизация -------------------------------------------------------


def test_request_goes_to_service_host():
    client, transport = build([ok({"cards": []})])
    result = client.get("content", "/content/v2/get/cards/list")

    assert result == {"cards": []}
    assert transport.calls[0]["url"] == (
        "https://content-api.wildberries.ru/content/v2/get/cards/list"
    )


def test_token_goes_into_authorization_header():
    token = make_token(categories=("content",))
    client, transport = build([ok()], token=token)
    client.get("content", "/ping")
    assert transport.calls[0]["headers"]["Authorization"] == token


def test_unknown_service_fails_before_network():
    client, transport = build([])
    with pytest.raises(UnknownServiceError):
        client.get("warehouse", "/ping")
    assert transport.calls == []


def test_test_token_switches_to_sandbox():
    token = make_token(categories=("content",), acc=2)
    client, transport = build([ok()], token=token)
    assert client.sandbox
    client.get("content", "/ping")
    assert "sandbox" in transport.calls[0]["url"]


def test_sandbox_unavailable_for_service():
    token = make_token(categories=("marketplace",), acc=2)
    client, _ = build([], token=token)
    with pytest.raises(SandboxUnavailableError):
        client.get("marketplace", "/ping")


def test_sandbox_flag_overrides_token_type():
    token = make_token(categories=("content",), acc=2)
    client, transport = build([ok()], token=token, sandbox=False)
    client.get("content", "/ping")
    assert "sandbox" not in transport.calls[0]["url"]


# --- проверка прав до запроса --------------------------------------------


def test_missing_category_blocked_locally():
    """403 списывается как десять запросов, поэтому отказываем локально."""
    client, transport = build([], token=make_token(categories=("content",)))
    with pytest.raises(WBForbiddenError) as exc:
        client.get("finance", "/ping")

    assert transport.calls == []
    assert "finance" in str(exc.value)
    assert "content" in str(exc.value)


def test_read_only_token_blocks_post():
    client, transport = build(
        [], token=make_token(categories=("prices",), read_only=True)
    )
    with pytest.raises(WBForbiddenError):
        client.post("prices", "/api/v2/upload/task", json={})
    assert transport.calls == []


def test_read_only_token_allows_get():
    client, _ = build(
        [ok({"data": 1})], token=make_token(categories=("prices",), read_only=True)
    )
    assert client.get("prices", "/api/v2/list/goods/filter") == {"data": 1}


def test_expired_token_blocked_locally():
    client, transport = build(
        [], token=make_token(categories=("content",), expires_in=-1)
    )
    with pytest.raises(WBForbiddenError) as exc:
        client.get("content", "/ping")
    assert transport.calls == []
    assert "истёк" in str(exc.value)


def test_common_available_to_any_token():
    client, _ = build([ok({"Status": "OK"})], token=make_token(categories=("advert",)))
    assert client.ping() == {"Status": "OK"}


def test_check_scopes_can_be_disabled():
    client, transport = build(
        [ok()], token=make_token(categories=("content",)), check_scopes=False
    )
    client.get("finance", "/ping")
    assert len(transport.calls) == 1


def test_unparsable_token_disables_checks_but_works():
    client, transport = build([ok({"ok": True})], token="не-jwt")
    assert not client.check_scopes
    assert client.get("finance", "/ping") == {"ok": True}
    assert transport.calls[0]["headers"]["Authorization"] == "не-jwt"


# --- ошибки и повторы ----------------------------------------------------


def test_validation_error_is_not_retried():
    client, transport = build([fail(400, {"title": "bad request"})])
    with pytest.raises(WBValidationError):
        client.get("content", "/ping")
    assert len(transport.calls) == 1


def test_auth_error_is_not_retried():
    client, transport = build([fail(401)])
    with pytest.raises(WBAuthError):
        client.get("content", "/ping")
    assert len(transport.calls) == 1


def test_server_error_is_retried_then_succeeds(clock):
    client, transport = build([fail(503), fail(503), ok({"ok": True})], clock=clock)
    assert client.get("content", "/ping") == {"ok": True}
    assert len(transport.calls) == 3
    assert clock.slept == [1.0, 2.0]  # экспоненциальная задержка


def test_retries_give_up_and_raise_last_error(clock):
    client, transport = build([fail(500)] * 3, clock=clock)
    with pytest.raises(WBServerError):
        client.get("content", "/ping")
    assert len(transport.calls) == 3


def test_max_retries_respected(clock):
    client, transport = build([fail(500)] * 5, clock=clock, max_retries=5)
    with pytest.raises(WBServerError):
        client.get("content", "/ping")
    assert len(transport.calls) == 5


def test_rate_limit_waits_exactly_as_server_says(clock):
    client, _ = build(
        [fail(429, None, {"X-Ratelimit-Retry": "7"}), ok({"ok": True})], clock=clock
    )
    assert client.get("content", "/ping") == {"ok": True}
    assert clock.slept[0] == 7.0


def test_rate_limit_marks_bucket_empty(clock):
    client, _ = build([fail(429, None, {"X-Ratelimit-Retry": "3"}), ok()], clock=clock)
    client.get("content", "/ping")
    assert client.limiter.bucket("content-api.wildberries.ru").remaining == 0


def test_rate_limit_raised_when_retries_exhausted(clock):
    client, _ = build([fail(429, None, {"X-Ratelimit-Retry": "1"})] * 3, clock=clock)
    with pytest.raises(WBRateLimitError) as exc:
        client.get("content", "/ping")
    assert exc.value.retry_after == 1.0


def test_successful_response_headers_update_bucket():
    client, _ = build(
        [ok({"ok": True}, {"X-Ratelimit-Remaining": "17", "X-Ratelimit-Limit": "300"})]
    )
    client.get("content", "/ping")
    state = client.limiter.bucket("content-api.wildberries.ru")
    assert state.remaining == 17
    assert state.limit == 300


# --- методы --------------------------------------------------------------


def test_post_sends_body():
    client, transport = build([ok({"ok": True})])
    client.post("content", "/content/v2/cards/update", json={"nmID": 1})
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["json"] == {"nmID": 1}


def test_get_passes_params():
    client, transport = build([ok()])
    client.get("content", "/list", params={"limit": 10})
    assert transport.calls[0]["params"] == {"limit": 10}


def test_put_and_delete():
    client, transport = build([ok(), ok()])
    client.put("content", "/x", json={"a": 1})
    client.delete("content", "/x", params={"id": 5})
    assert [c["method"] for c in transport.calls] == ["PUT", "DELETE"]


def test_timeout_is_passed_to_transport():
    client, transport = build([ok()], timeout=5.0)
    client.get("content", "/ping")
    assert transport.calls[0]["timeout"] == 5.0


def test_empty_body_returns_none():
    client, _ = build([ok(None)])
    assert client.get("content", "/ping") is None
