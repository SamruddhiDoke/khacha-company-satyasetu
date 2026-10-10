class ProviderError(Exception):
    """A provider failed. `code` is a stable, user-facing error category."""

    code = "provider_error"

    def __init__(self, message: str, *, provider: str = "", retryable: bool = False):
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable


class ProviderNotConfigured(ProviderError):
    code = "provider_not_configured"


class QuotaExhausted(ProviderError):
    code = "quota_exhausted"


class LocalBudgetExhausted(QuotaExhausted):
    """SatyaSetu's own configured daily budget is used up (provider-wide, not a single model's quota)."""


class RateLimited(ProviderError):
    code = "rate_limited"


class ProviderTimeout(ProviderError):
    code = "timeout"


class InvalidModelOutput(ProviderError):
    code = "invalid_model_output"


class ContentBlocked(ProviderError):
    code = "content_blocked"
