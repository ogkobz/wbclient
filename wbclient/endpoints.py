"""Карта доменов WB API.

У WB не один адрес, а тринадцать: у каждой категории методов свой хост.
Промахнуться легко — ответом будет 404, который в лимитах стоит
как десять запросов. Поэтому домен выбирается по категории, а не руками.

Песочница есть не у всех категорий. Если для категории тестового хоста нет,
работа с тестовым токеном по ней невозможна — лучше сказать об этом сразу,
чем получить невнятную ошибку.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Service:
    """Категория методов WB API."""

    key: str
    host: str
    sandbox_host: str | None = None
    title: str = ""

    def base_url(self, sandbox: bool = False) -> str:
        if sandbox:
            if not self.sandbox_host:
                raise SandboxUnavailableError(
                    f"У категории «{self.title or self.key}» нет песочницы. "
                    f"Тестовый токен с ней работать не будет."
                )
            return f"https://{self.sandbox_host}"
        return f"https://{self.host}"


class SandboxUnavailableError(RuntimeError):
    """Для категории нет тестового контура."""


class UnknownServiceError(KeyError):
    """Категория не найдена."""


SERVICES: dict[str, Service] = {
    s.key: s
    for s in (
        Service("common", "common-api.wildberries.ru",
                title="Общее, новости, продавец, тарифы"),
        Service("content", "content-api.wildberries.ru",
                "content-api-sandbox.wildberries.ru", "Контент"),
        Service("analytics", "seller-analytics-api.wildberries.ru",
                title="Аналитика и данные"),
        Service("prices", "discounts-prices-api.wildberries.ru",
                "discounts-prices-api-sandbox.wildberries.ru", "Цены и скидки"),
        Service("marketplace", "marketplace-api.wildberries.ru",
                title="Маркетплейс: склады и заказы"),
        Service("statistics", "statistics-api.wildberries.ru",
                "statistics-api-sandbox.wildberries.ru", "Статистика"),
        Service("advert", "advert-api.wildberries.ru",
                "advert-api-sandbox.wildberries.ru", "Продвижение"),
        Service("feedbacks", "feedbacks-api.wildberries.ru",
                "feedbacks-api-sandbox.wildberries.ru", "Вопросы и отзывы"),
        Service("chat", "buyer-chat-api.wildberries.ru",
                title="Чат с покупателями"),
        Service("supplies", "supplies-api.wildberries.ru", title="Поставки"),
        Service("returns", "returns-api.wildberries.ru",
                title="Возвраты покупателями"),
        Service("documents", "documents-api.wildberries.ru", title="Документы"),
        Service("finance", "finance-api.wildberries.ru", title="Финансы"),
        Service("users", "user-management-api.wildberries.ru",
                title="Управление пользователями"),
    )
}

# Категория токена, которая нужна для доступа к сервису.
# У `common` доступ есть с токеном любой категории, поэтому None.
SERVICE_TOKEN_CATEGORY: dict[str, str | None] = {
    "common": None,
    "content": "content",
    "analytics": "analytics",
    "prices": "prices",
    "marketplace": "marketplace",
    "statistics": "statistics",
    "advert": "advert",
    "feedbacks": "feedbacks",
    "chat": "chat",
    "supplies": "supplies",
    "returns": "returns",
    "documents": "documents",
    "finance": "finance",
    "users": "users",
}


def get_service(key: str) -> Service:
    try:
        return SERVICES[key]
    except KeyError:
        known = ", ".join(sorted(SERVICES))
        raise UnknownServiceError(
            f"Неизвестная категория «{key}». Доступные: {known}"
        ) from None


def required_category(service_key: str) -> str | None:
    """Какая категория должна быть у токена для этого сервиса."""
    return SERVICE_TOKEN_CATEGORY.get(service_key)
