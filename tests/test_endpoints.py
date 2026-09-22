"""Карта доменов. Промах по домену стоит 404, а он списывается как 10 запросов."""

from __future__ import annotations

import pytest

from wbclient.endpoints import (
    SERVICE_TOKEN_CATEGORY,
    SERVICES,
    SandboxUnavailableError,
    UnknownServiceError,
    get_service,
    required_category,
)


def test_base_url_is_https():
    assert get_service("content").base_url() == "https://content-api.wildberries.ru"


def test_sandbox_host_used_when_asked():
    url = get_service("content").base_url(sandbox=True)
    assert url == "https://content-api-sandbox.wildberries.ru"


def test_sandbox_missing_raises_with_readable_message():
    with pytest.raises(SandboxUnavailableError) as exc:
        get_service("marketplace").base_url(sandbox=True)
    assert "песочниц" in str(exc.value)


def test_unknown_service_lists_known_ones():
    with pytest.raises(UnknownServiceError) as exc:
        get_service("warehouse")
    assert "content" in str(exc.value)


def test_every_service_has_token_category_entry():
    assert set(SERVICES) == set(SERVICE_TOKEN_CATEGORY)


def test_common_needs_no_category():
    assert required_category("common") is None


def test_service_category_matches_key():
    for key in SERVICES:
        if key == "common":
            continue
        assert required_category(key) == key


def test_hosts_are_unique():
    hosts = [s.host for s in SERVICES.values()]
    assert len(hosts) == len(set(hosts))


def test_unknown_service_category_is_none():
    assert required_category("нет такого") is None
