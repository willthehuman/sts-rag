"""Small optional web search/fetch helper for community strategy context."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from html import unescape
import re
from typing import Iterable
from urllib.parse import quote_plus, urlparse
import urllib.error
import urllib.request


DEFAULT_DOMAINS = [
    "slay-the-spire.fandom.com",
    "reddit.com",
    "steamcommunity.com",
]


class WebSearchError(RuntimeError):
    pass


@dataclass(frozen=True)
class WebResult:
    title: str
    url: str
    snippet: str


def community_web_context(
    question: str,
    *,
    max_results: int = 3,
    domains: list[str] | None = None,
    timeout: float = 8.0,
) -> list[WebResult]:
    """Search a few community/game pages and fetch short text snippets.

    This is intentionally small and optional. OpenRouter can use its own web
    plugin; this helper exists so local Ollama models can receive web context.
    """
    query_domains = domains or DEFAULT_DOMAINS
    query = "Slay the Spire " + question
    results = search_duckduckgo_lite(query, max_results=max_results * 2, domains=query_domains, timeout=timeout)
    enriched: list[WebResult] = []
    for result in results:
        snippet = result.snippet
        try:
            fetched = fetch_page_excerpt(result.url, question, timeout=timeout)
        except WebSearchError:
            fetched = ""
        if fetched:
            snippet = fetched
        enriched.append(WebResult(title=result.title, url=result.url, snippet=snippet))
        if len(enriched) >= max_results:
            break
    return enriched


def search_duckduckgo_lite(
    query: str,
    *,
    max_results: int,
    domains: list[str] | None = None,
    timeout: float = 8.0,
) -> list[WebResult]:
    domain_query = " ".join(f"site:{domain}" for domain in domains or [])
    full_query = f"{query} {domain_query}".strip()
    url = "https://lite.duckduckgo.com/lite/?q=" + quote_plus(full_query)
    html = _get_text(url, timeout=timeout)
    parser = _DuckDuckGoLiteParser()
    parser.feed(html)
    results = []
    seen = set()
    for result in parser.results:
        if not result.url or result.url in seen:
            continue
        if domains and not _domain_allowed(result.url, domains):
            continue
        seen.add(result.url)
        results.append(result)
        if len(results) >= max_results:
            break
    return results


def fetch_page_excerpt(url: str, question: str, *, timeout: float = 8.0, max_chars: int = 1400) -> str:
    html = _get_text(url, timeout=timeout)
    parser = _TextParser()
    parser.feed(html)
    text = " ".join(parser.parts)
    text = re.sub(r"\s+", " ", unescape(text)).strip()
    if not text:
        return ""
    terms = [term for term in re.findall(r"[A-Za-z][A-Za-z0-9'-]{3,}", question.lower())[:10]]
    index = _best_excerpt_index(text.lower(), terms)
    start = max(0, index - 350)
    end = min(len(text), start + max_chars)
    return text[start:end].strip()


def web_context_to_prompt(results: Iterable[WebResult]) -> str:
    rows = list(results)
    if not rows:
        return "Community web context: none"
    parts = ["Community web context:"]
    for result in rows:
        snippet = " ".join(result.snippet.split())
        if len(snippet) > 700:
            snippet = snippet[:697].rstrip() + "..."
        parts.append(f"- {result.title} ({result.url}): {snippet}")
    return "\n".join(parts)


def _get_text(url: str, *, timeout: float) -> str:
    headers = {
        "User-Agent": "sts-rag/0.1 (+local research tool)",
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(1_000_000)
    except urllib.error.HTTPError as exc:
        raise WebSearchError(f"web request failed with HTTP {exc.code}: {url}") from exc
    except urllib.error.URLError as exc:
        raise WebSearchError(f"web request failed: {exc}") from exc
    return raw.decode("utf-8", "replace")


def _best_excerpt_index(text: str, terms: list[str]) -> int:
    if not terms:
        return 0
    best_index = 0
    best_score = -1
    for match in re.finditer(r"\b\w+\b", text):
        window = text[match.start(): match.start() + 900]
        score = sum(1 for term in terms if term in window)
        if score > best_score:
            best_score = score
            best_index = match.start()
    return best_index


def _domain_allowed(url: str, domains: list[str]) -> bool:
    host = urlparse(url).netloc.lower()
    return any(host == domain or host.endswith("." + domain) for domain in domains)


class _DuckDuckGoLiteParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[WebResult] = []
        self._in_link = False
        self._href = ""
        self._link_text: list[str] = []
        self._last_result_index: int | None = None
        self._capture_snippet = False
        self._snippet: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "a" and attr.get("href"):
            href = attr["href"] or ""
            if href.startswith("http"):
                self._in_link = True
                self._href = href
                self._link_text = []
        if tag in {"td", "span"}:
            class_name = attr.get("class") or ""
            if "result-snippet" in class_name or "snippet" in class_name:
                self._capture_snippet = True
                self._snippet = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_link:
            title = _clean(" ".join(self._link_text))
            if title:
                self.results.append(WebResult(title=title, url=self._href, snippet=""))
                self._last_result_index = len(self.results) - 1
            self._in_link = False
            self._href = ""
            self._link_text = []
        if tag in {"td", "span"} and self._capture_snippet:
            if self._last_result_index is not None:
                snippet = _clean(" ".join(self._snippet))
                if snippet:
                    current = self.results[self._last_result_index]
                    self.results[self._last_result_index] = WebResult(
                        title=current.title,
                        url=current.url,
                        snippet=snippet,
                    )
            self._capture_snippet = False
            self._snippet = []

    def handle_data(self, data: str) -> None:
        if self._in_link:
            self._link_text.append(data)
        if self._capture_snippet:
            self._snippet.append(data)


class _TextParser(HTMLParser):
    SKIP_TAGS = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP_TAGS:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP_TAGS and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            cleaned = _clean(data)
            if cleaned:
                self.parts.append(cleaned)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text)).strip()
