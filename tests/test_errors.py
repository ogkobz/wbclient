"""Разбор ответов с ошибкой: тип исключения определяет, повторять ли запрос."""

from __future__ import annotations

import pytest

from wbclient.errors import (
    RETRYABLE,
    WBAuthError,
    WBError,
    WBForbiddenError,
    WBNotFoundError,
    WBPayloadTooLargeError,
    WBPaymentRequiredError,
    WBRateLimitError,
    WBServerError,
    WBValidationError,
    error_from_response,
)


@pytest.mark.parametrize(
    "status,expected",
    [
        (400, WBValidationError),
        (401, WBAuthError),
        (402, WBPaymentRequiredError),
        (403, WBForbiddenError),
        (404, WBNotFoundError),
        (409, WBValidationError),
        (413, WBPayloadTooLargeError),
        (422, WBValidationError),
        (429, WBRateLimitError),
        (500, WBServerError),
        (503, WBServerError),
    ],
)
def test_status_maps_to_exception(status, expected):
    error = error_from_response(status, None, {})
    assert isinstance(error, expected)
    assert error.status == status


def test_unmapped_status_falls_back_to_base_error():
    error = error_from_response(418, None, {})
    assert type(error) is WBError


def test_retryable_set():
    assert isinstance(error_from_response(429, None, {}), RETRYABLE)
    assert isinstance(error_from_response(503, None, {}), RETRYABLE)
    assert not isinstance(error_from_response(400, None, {}), RETRYABLE)
    assert not isinstance(error_from_response(403, None, {}), RETRYABLE)


def test_message_taken_from_body():
    error = error_from_response(
        400,
        {"title": "Неверный параметр", "detail": "nmID обязателен", "requestId": "req-1"},
        {},
    )
    assert "Неверный параметр" in str(error)
    assert "nmID обязателен" in str(error)
    assert error.request_id == "req-1"


def test_message_falls_back_to_status_when_body_empty():
    assert "HTTP 500" in str(error_from_response(500, {}, {}))


def test_rate_limit_reads_headers():
    error = error_from_response(
        429,
        {"title": "too many requests"},
        {"X-Ratelimit-Retry": "7", "X-Ratelimit-Reset": "20", "X-Ratelimit-Limit": "300"},
    )
    assert error.retry_after == 7.0
    assert error.reset_after == 20.0
    assert error.limit == 300


def test_rate_limit_headers_case_insensitive():
    error = error_from_response(429, None, {"x-ratelimit-retry": "3"})
    assert error.retry_after == 3.0


def test_rate_limit_without_headers_has_safe_default():
    error = error_from_response(429, None, {})
    assert error.retry_after == 1.0
    assert error.reset_after is None


def test_garbage_header_does_not_break_parsing():
    error = error_from_response(429, None, {"X-Ratelimit-Retry": "скоро"})
    assert error.retry_after == 1.0
