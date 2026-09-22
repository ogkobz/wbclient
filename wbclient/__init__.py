"""wbclient — клиент Wildberries Seller API.

Тонкая обёртка вокруг HTTP: карта доменов, разбор токена, соблюдение
лимитов и понятные исключения. Бизнес-логики нет намеренно —
она у каждого продавца своя.
"""

from .client import RequestsTransport, Response, WBClient
from .endpoints import (
    SERVICES,
    SandboxUnavailableError,
    Service,
    UnknownServiceError,
    get_service,
    required_category,
)
from .errors import (
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
from .ratelimit import BucketState, RateLimiter
from .token import InvalidTokenError, TokenInfo, parse_token

__version__ = "0.1.0"

__all__ = [
    "WBClient",
    "Response",
    "RequestsTransport",
    "RateLimiter",
    "BucketState",
    "TokenInfo",
    "parse_token",
    "InvalidTokenError",
    "Service",
    "SERVICES",
    "get_service",
    "required_category",
    "SandboxUnavailableError",
    "UnknownServiceError",
    "WBError",
    "WBAuthError",
    "WBForbiddenError",
    "WBPaymentRequiredError",
    "WBNotFoundError",
    "WBValidationError",
    "WBPayloadTooLargeError",
    "WBRateLimitError",
    "WBServerError",
    "RETRYABLE",
    "error_from_response",
    "__version__",
]
