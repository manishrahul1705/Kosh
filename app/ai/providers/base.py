"""Provider abstraction. The rest of Stage 3C depends ONLY on this module.

    AIProvider
        +-- GeminiProvider            (app/ai/providers/gemini.py)
        +-- OpenAICompatibleProvider  (app/ai/providers/openai_compatible.py)
        +-- MockProvider              (app/ai/providers/mock.py - offline, deterministic)

A provider receives an already-bounded prompt and returns raw text + usage.
It never sees file paths, database details or anything but tender evidence.
Errors are classified so the caller can decide: retry (transient), block
(auth/config - never hammer the provider) or fail (bad response).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class AIRequest:
    system: str
    user: str
    max_output_tokens: int
    temperature: float = 0.0
    timeout_seconds: float = 60.0
    # Structured copy of the chunks (id -> text) - used by the offline mock only;
    # real providers send just ``system`` + ``user``.
    chunks: list[dict] = field(default_factory=list)


@dataclass
class AIResponse:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    finish_reason: str | None = None
    model: str | None = None


class ProviderError(Exception):
    """Base class. ``code`` is an AIErrorCode value; ``transient`` => safe to retry."""

    code = "PROVIDER_ERROR"
    transient = False
    blocking = False   # auth / configuration: stop, do not retry automatically

    def __init__(self, message: str, *, status_code: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class ProviderTimeout(ProviderError):
    code, transient = "PROVIDER_TIMEOUT", True


class ProviderRateLimited(ProviderError):
    code, transient = "PROVIDER_RATE_LIMITED", True


class ProviderUnavailable(ProviderError):
    code, transient = "PROVIDER_UNAVAILABLE", True


class DailyLimitReached(ProviderError):
    """AI_MAX_ANALYSES_PER_DAY provider calls already made in the last 24 h (local cost cap)."""
    code, transient = "DAILY_LIMIT_REACHED", True


class ProviderAuthError(ProviderError):
    code, blocking = "PROVIDER_AUTH_FAILED", True


class ProviderConfigError(ProviderError):
    """Missing key/model, unknown provider, invalid model, rejected request shape."""
    code, blocking = "PROVIDER_CONFIG_ERROR", True


class NotConfigured(ProviderConfigError):
    code = "AI_NOT_CONFIGURED"


class ProviderResponseError(ProviderError):
    """Empty / truncated / safety-blocked response. Not retried automatically."""

    def __init__(self, message: str, code: str = "EMPTY_RESPONSE", **kw):
        super().__init__(message, **kw)
        self.code = code


class AIProvider(ABC):
    name: str = "abstract"

    def __init__(self, model: str) -> None:
        self.model = model

    @abstractmethod
    def generate(self, request: AIRequest) -> AIResponse:
        """One provider call. Must raise a ProviderError subclass on failure."""

    def close(self) -> None:  # noqa: B027 - optional hook, default no-op
        pass

    def describe(self) -> dict:
        """Safe metadata (never credentials)."""
        return {"provider": self.name, "model": self.model}


def classify_http_status(status: int, message: str, retry_after: float | None = None) -> ProviderError:
    """Map an HTTP error status to the right error class (shared by HTTP providers)."""
    if status in (401, 403):
        return ProviderAuthError(f"HTTP {status}: {message}", status_code=status)
    if status == 429:
        return ProviderRateLimited(f"HTTP 429: {message}", status_code=status, retry_after=retry_after)
    if status in (408,):
        return ProviderTimeout(f"HTTP {status}: {message}", status_code=status)
    if status >= 500:
        return ProviderUnavailable(f"HTTP {status}: {message}", status_code=status)
    # 400 / 404 / 422 ...: invalid model, unsupported parameter, malformed request -> configuration
    return ProviderConfigError(f"HTTP {status}: {message}", status_code=status)


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None
