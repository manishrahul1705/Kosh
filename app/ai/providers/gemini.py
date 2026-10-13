"""Google Gemini (Generative Language REST API, ``generateContent``) via httpx.

    POST {base}/models/{model}:generateContent      header: x-goog-api-key
The key is sent as a header (never a URL query parameter) so URLs can be logged.
"""

from __future__ import annotations

import httpx

from app.ai.providers._http import post_json, validate_base_url, validate_key
from app.ai.providers.base import AIProvider, AIRequest, AIResponse, NotConfigured, ProviderResponseError

DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(self, model: str, api_key: str, base_url: str = "", *,
                 transport: httpx.BaseTransport | None = None) -> None:
        api_key = validate_key(api_key)
        if not api_key:
            raise NotConfigured("AI_API_KEY is not set for provider gemini")
        if not model:
            raise NotConfigured("AI_MODEL is not set for provider gemini")
        super().__init__(model.removeprefix("models/"))
        self._key = api_key
        self.base_url = validate_base_url(base_url or DEFAULT_GEMINI_BASE_URL)
        self._client = httpx.Client(transport=transport)

    def close(self) -> None:
        self._client.close()

    def generate(self, request: AIRequest) -> AIResponse:
        body = {
            "systemInstruction": {"parts": [{"text": request.system}]},
            "contents": [{"role": "user", "parts": [{"text": request.user}]}],
            "generationConfig": {"temperature": request.temperature,
                                 "maxOutputTokens": request.max_output_tokens,
                                 "responseMimeType": "application/json"},
        }
        data = post_json(self._client, f"{self.base_url}/models/{self.model}:generateContent",
                         headers={"x-goog-api-key": self._key, "Content-Type": "application/json"},
                         body=body, timeout=request.timeout_seconds, secret=self._key)
        usage = data.get("usageMetadata") or {}
        block = (data.get("promptFeedback") or {}).get("blockReason")
        cands = data.get("candidates") or []
        if block and not cands:
            raise ProviderResponseError(f"prompt blocked by provider: {block}", code="RESPONSE_BLOCKED")
        if not cands:
            raise ProviderResponseError("no candidates in response", code="EMPTY_RESPONSE")
        cand = cands[0] or {}
        finish = cand.get("finishReason")
        parts = ((cand.get("content") or {}).get("parts")) or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought"))
        if finish == "MAX_TOKENS":
            raise ProviderResponseError("response truncated (MAX_TOKENS); raise AI_MAX_OUTPUT_TOKENS",
                                        code="RESPONSE_TRUNCATED")
        if finish in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"):
            raise ProviderResponseError(f"response blocked by provider: {finish}", code="RESPONSE_BLOCKED")
        if not text.strip():
            raise ProviderResponseError("empty response text", code="EMPTY_RESPONSE")
        return AIResponse(text=text, input_tokens=usage.get("promptTokenCount"),
                          output_tokens=usage.get("candidatesTokenCount"), total_tokens=usage.get("totalTokenCount"),
                          finish_reason=finish, model=data.get("modelVersion") or self.model)
