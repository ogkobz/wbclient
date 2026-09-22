"""Разбор токена. Цена ошибки — 403, который списывается как 10 запросов."""

from __future__ import annotations

import base64
import json
import time

import pytest

from conftest import make_token
from wbclient.token import InvalidTokenError, parse_token


def test_categories_from_mask():
    info = parse_token(make_token(categories=("content", "prices", "statistics")))
    assert info.categories == frozenset({"content", "prices", "statistics"})
    assert info.allows("content")
    assert not info.allows("finance")


def test_read_only_bit_blocks_write():
    info = parse_token(make_token(categories=("content",), read_only=True))
    assert info.read_only
    assert info.allows("content")
    assert not info.can_write("content")


def test_write_allowed_without_read_only_bit():
    info = parse_token(make_token(categories=("content",)))
    assert info.can_write("content")


@pytest.mark.parametrize(
    "acc,expected",
    [(1, "basic"), (2, "test"), (3, "personal"), (4, "service"), (99, "unknown")],
)
def test_token_types(acc, expected):
    assert parse_token(make_token(acc=acc)).token_type == expected


def test_test_token_means_sandbox():
    assert parse_token(make_token(acc=2)).is_sandbox
    assert not parse_token(make_token(acc=1)).is_sandbox


def test_flag_t_used_when_acc_unknown():
    info = parse_token(make_token(acc=99, extra={"t": True}))
    assert info.token_type == "test"
    assert info.is_sandbox


def test_expired_token():
    assert parse_token(make_token(expires_in=-10)).is_expired
    assert not parse_token(make_token(expires_in=3600)).is_expired


def test_seconds_left_never_negative():
    assert parse_token(make_token(expires_in=-100)).seconds_left == 0
    assert parse_token(make_token(expires_in=3600)).seconds_left <= 3600


def test_bearer_prefix_and_whitespace_are_tolerated():
    token = make_token(categories=("advert",))
    info = parse_token(f"  Bearer {token}  ")
    assert info.allows("advert")


def test_seller_id_and_token_id():
    info = parse_token(make_token(seller_id="sid-42"))
    assert info.seller_id == "sid-42"
    assert info.token_id == "token-id"


@pytest.mark.parametrize("bad", ["", "   ", "not-a-jwt", "a.b", "a.b.c.d"])
def test_malformed_tokens_rejected(bad):
    with pytest.raises(InvalidTokenError):
        parse_token(bad)


def test_payload_not_json():
    segment = base64.urlsafe_b64encode(b"not json").decode().rstrip("=")
    with pytest.raises(InvalidTokenError):
        parse_token(f"aGVhZGVy.{segment}.c2ln")


def test_payload_is_list_not_object():
    segment = base64.urlsafe_b64encode(json.dumps([1, 2]).encode()).decode().rstrip("=")
    with pytest.raises(InvalidTokenError):
        parse_token(f"aGVhZGVy.{segment}.c2ln")


def test_payload_without_mask_gives_empty_categories():
    payload = base64.urlsafe_b64encode(
        json.dumps({"acc": 1, "exp": int(time.time()) + 60}).encode()
    ).decode().rstrip("=")
    info = parse_token(f"aGVhZGVy.{payload}.c2ln")
    assert info.categories == frozenset()
    assert not info.read_only


def test_payload_without_exp_is_not_expired():
    payload = base64.urlsafe_b64encode(json.dumps({"acc": 1, "s": 2}).encode()).decode().rstrip("=")
    info = parse_token(f"aGVhZGVy.{payload}.c2ln")
    assert info.expires_at is None
    assert not info.is_expired
    assert info.seconds_left is None
