"""Any OpenAI-compatible Chat Completions endpoint (OpenAI, Azure-style gateways,
Groq, OpenRouter, local vLLM / Ollama / LM Studio ...) via httpx.

    POST {AI_BASE_URL}/chat/completions      header: Authorization: Bearer <key>
"""

from __future__ import annotations

import httpx

from app.ai.providers._http import post_json, validate_base_url, validate_key
from app.ai.providers.base import AIProvider, AIRequest, AIResponse, NotConfigured, ProviderResponseError

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


class OpenAICompatibleProvider(AIProvider):
    name = "openai_compatible"

    def __init__(self, model: str, api_key: str, base_url: str = "", *, json_mode: bool = True,
                 transport: httpx.BaseTransport | None = None) -> None:
        if not model:
            raise NotConfigured("AI_MODEL is not set for provider openai_compatible")
        base = validate_base_url(base_url or DEFAULT_OPENAI_BASE_URL)
        api_key = validate_key(api_key)
        if not api_key and base == DEFAULT_OPENAI_BASE_URL:
            raise NotConfigured("AI_API_KEY is not set for provider openai_compatible")
        super().__init__(model)
        self._key = api_key            # may be empty for keyless local servers (custom AI_BASE_URL)
        self.base_url = base
        self.json_mode = json_mode
        self._client = httpx.Client(transport=transport)

    def close(self) -> None:
        self._client.close()

    def generate(self, request: AIRequest) -> AIResponse:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": request.system},
                         {"role": "user", "content": request.user}],
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
        }
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        data = post_json(self._client, f"{self.base_url}/chat/completions", headers=headers, body=body,
                         timeout=request.timeout_seconds, secret=self._key)
        choices = data.get("choices") or []
        if not choices:
            raise ProviderResponseError("no choices in response", code="EMPTY_RESPONSE")
        ch = choices[0] or {}
        finish = ch.get("finish_reason")
        msg = ch.get("message") or {}
        text = msg.get("content") or ""
        if isinstance(text, list):  # some gateways return content parts
            text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
        if finish == "length":
            raise ProviderResponseError("response truncated (finish_reason=length); raise AI_MAX_OUTPUT_TOKENS",
                                        code="RESPONSE_TRUNCATED")
        if finish == "content_filter" or msg.get("refusal"):
            raise ProviderResponseError("response blocked by provider content filter", code="RESPONSE_BLOCKED")
        if not str(text).strip():
            raise ProviderResponseError("empty response text", code="EMPTY_RESPONSE")
        usage = data.get("usage") or {}
        return AIResponse(text=str(text), input_tokens=usage.get("prompt_tokens"),
                          output_tokens=usage.get("completion_tokens"), total_tokens=usage.get("total_tokens"),
                          finish_reason=finish, model=data.get("model") or self.model)
