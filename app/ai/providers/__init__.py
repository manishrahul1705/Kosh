"""Provider factory: the only place that knows concrete provider classes."""

from __future__ import annotations

from app.ai.providers.base import AIProvider, NotConfigured, ProviderConfigError
from app.core.config import Settings

SUPPORTED_PROVIDERS = ("gemini", "openai_compatible", "mock")


def effective_provider(settings: Settings) -> str:
    name = settings.ai_provider_name
    return "openai_compatible" if name == "openai" else name


def effective_model(settings: Settings) -> str:
    """Model name recorded with runs / used for idempotency (no provider call)."""
    if settings.ai_provider_name == "mock" and not settings.ai_model:
        from app.ai.providers.mock import DEFAULT_MOCK_MODEL
        return DEFAULT_MOCK_MODEL
    model = (settings.ai_model or "").strip()
    return model.removeprefix("models/") if settings.ai_provider_name == "gemini" else model


def provider_configured(settings: Settings) -> bool:
    """True when a provider could be built (key presence is checked, never its value)."""
    try:
        build_provider(settings).close()
        return True
    except ProviderConfigError:
        return False


def build_provider(settings: Settings) -> AIProvider:
    """Build the configured provider. Raises NotConfigured / ProviderConfigError (blocking)."""
    name = settings.ai_provider_name
    key = settings.ai_api_key_value()
    if not name:
        raise NotConfigured("AI_PROVIDER is not set (gemini | openai_compatible | mock)")
    if name == "gemini":
        from app.ai.providers.gemini import GeminiProvider
        return GeminiProvider(settings.ai_model.strip(), key, settings.ai_base_url)
    if name in ("openai_compatible", "openai"):
        from app.ai.providers.openai_compatible import OpenAICompatibleProvider
        return OpenAICompatibleProvider(settings.ai_model.strip(), key, settings.ai_base_url,
                                        json_mode=settings.ai_openai_json_mode)
    if name == "mock":
        from app.ai.providers.mock import MockProvider
        return MockProvider(settings.ai_model.strip())
    raise ProviderConfigError(f"Unknown AI_PROVIDER '{name[:40]}' (supported: {', '.join(SUPPORTED_PROVIDERS)})")
