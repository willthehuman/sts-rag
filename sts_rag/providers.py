"""LLM and embedding provider adapters."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class ProviderError(RuntimeError):
    pass


@dataclass
class ChatResult:
    text: str
    provider: str
    model: str


class BaseProvider:
    name = "base"

    def __init__(self, model: str | None = None) -> None:
        self.model = model or ""

    def chat(self, messages: list[dict[str, str]]) -> ChatResult:
        raise NotImplementedError

    def embed(self, inputs: list[str]) -> list[list[float]]:
        raise NotImplementedError


class OllamaProvider(BaseProvider):
    name = "ollama"

    def __init__(self, model: str | None = None, host: str | None = None, timeout: float = 60.0) -> None:
        super().__init__(model or os.environ.get("OLLAMA_MODEL") or "llama3.1")
        self.host = (host or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
        self.timeout = timeout

    def chat(self, messages: list[dict[str, str]]) -> ChatResult:
        payload = {"model": self.model, "messages": messages, "stream": False}
        data = self._post("/api/chat", payload)
        message = data.get("message", {})
        text = message.get("content")
        if not text:
            raise ProviderError("Ollama returned no chat message content.")
        return ChatResult(text=text, provider=self.name, model=self.model)

    def embed(self, inputs: list[str]) -> list[list[float]]:
        data = self._post("/api/embed", {"model": self.model, "input": inputs})
        vectors = data.get("embeddings")
        if not isinstance(vectors, list):
            raise ProviderError("Ollama returned no embeddings array.")
        return vectors

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.host}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=0.75) as resp:
                return 200 <= resp.status < 300
        except Exception:
            return False

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return _post_json(f"{self.host}{path}", payload, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise ProviderError(
                f"Ollama request to {self.host}{path} failed with HTTP {exc.code}. "
                f"Check that Ollama is running and supports the endpoint, and set OLLAMA_MODEL "
                f"to an installed chat model. Details: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ProviderError(
                f"Could not reach Ollama at {self.host}. Start Ollama and set OLLAMA_MODEL, "
                f"or run with --backend none. Details: {exc}"
            ) from exc


class OpenRouterProvider(BaseProvider):
    name = "openrouter"

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        embedding_model: str | None = None,
        web: bool = False,
        web_max_results: int = 5,
        web_domains: list[str] | None = None,
        timeout: float = 90.0,
    ) -> None:
        super().__init__(model or os.environ.get("OPENROUTER_MODEL") or "openai/gpt-5.2")
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY") or ""
        self.embedding_model = embedding_model or os.environ.get("OPENROUTER_EMBEDDING_MODEL") or "openai/text-embedding-3-small"
        self.web = web
        self.web_max_results = web_max_results
        self.web_domains = web_domains or []
        self.timeout = timeout
        if not self.api_key:
            raise ProviderError("OPENROUTER_API_KEY is required for --backend openrouter.")

    def chat(self, messages: list[dict[str, str]]) -> ChatResult:
        payload: dict[str, Any] = {"model": self.model, "messages": messages}
        if self.web:
            plugin: dict[str, Any] = {"id": "web", "max_results": self.web_max_results}
            if self.web_domains:
                plugin["include_domains"] = self.web_domains
            payload["plugins"] = [plugin]
        data = self._post(
            "/chat/completions",
            payload,
        )
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError("OpenRouter returned no chat choices.")
        text = choices[0].get("message", {}).get("content")
        if not text:
            raise ProviderError("OpenRouter returned no chat message content.")
        return ChatResult(text=text, provider=self.name, model=self.model)

    def embed(self, inputs: list[str]) -> list[list[float]]:
        data = self._post(
            "/embeddings",
            {"model": self.embedding_model, "input": inputs, "encoding_format": "float"},
        )
        rows = data.get("data") or []
        vectors = [row.get("embedding") for row in rows if isinstance(row, dict)]
        if len(vectors) != len(inputs):
            raise ProviderError("OpenRouter returned an unexpected embeddings response.")
        return vectors

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-OpenRouter-Title": "sts-rag",
        }
        try:
            return _post_json(f"https://openrouter.ai/api/v1{path}", payload, headers=headers, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise ProviderError(f"OpenRouter request failed with HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"Could not reach OpenRouter: {exc}") from exc


def select_provider(
    backend: str,
    model: str | None = None,
    *,
    web: bool = False,
    web_max_results: int = 5,
    web_domains: list[str] | None = None,
) -> BaseProvider | None:
    backend = backend.lower()
    if backend == "none":
        return None
    if backend == "openrouter":
        return OpenRouterProvider(model=model, web=web, web_max_results=web_max_results, web_domains=web_domains)
    if backend == "ollama":
        return OllamaProvider(model=model)
    if backend == "auto":
        if os.environ.get("OPENROUTER_API_KEY"):
            return OpenRouterProvider(model=model, web=web, web_max_results=web_max_results, web_domains=web_domains)
        ollama = OllamaProvider(model=model, timeout=30.0)
        if ollama.is_available():
            return ollama
        return None
    raise ProviderError(f"Unknown backend {backend!r}; choose auto, none, ollama, or openrouter.")


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout: float,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    req = urllib.request.Request(url, data=body, headers=request_headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read().decode("utf-8")
    return json.loads(data)
