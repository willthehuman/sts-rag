"""Question answering over the Slay the Spire fact database."""

from __future__ import annotations

import sqlite3

from . import creative
from .game_tools import build_game_tool_context, local_tool_answer, tool_context_to_prompt
from .providers import ProviderError, select_provider
from .retrieval import exact_answer, retrieve, strategy_context
from .web_search import WebResult, WebSearchError, community_web_context, web_context_to_prompt


SYSTEM_PROMPT = """You are a Slay the Spire assistant.
Use only the provided JAR-derived context for factual claims.
Cite facts using the bracketed citations, e.g. [card:Bash].
Copy bracketed citations exactly as provided; do not invent citation ids from display names.
For strategy or deck-building advice, infer combos from the provided card/relic text.
Label that reasoning as strategy or speculation, not as a proven game fact.
Do not reject a strategy request merely because the context does not contain a prewritten guide.
If the answer is not extractable from the provided context, say that directly.
If community web context is provided, use it only as strategy/community inspiration.
If community web context conflicts with JAR-derived facts, prefer the JAR-derived facts.
Do not claim an idea has never been seen before unless indexed community/run data supports that claim.

When the question is about strategy, deck-building, combos, or archetypes, be genuinely creative:
- Propose 2-3 concrete, *named* deck ideas or combos (reuse the candidate archetypes if given).
- For each, explain the loop or engine step by step and state the win condition.
- Ground every card/relic you name in a bracketed citation; mark the plan itself as speculation.
Use short section headers ending with ':' and '- ' bullets so the answer is easy to scan."""


def answer_question(
    conn: sqlite3.Connection,
    question: str,
    *,
    backend: str = "auto",
    model: str | None = None,
    limit: int = 8,
    web: bool = False,
    web_max_results: int = 3,
    web_domains: list[str] | None = None,
) -> str:
    exact = exact_answer(conn, question)
    if exact:
        return _local_answer(question, exact, [], provider_error=None)
    tool_context = build_game_tool_context(conn, question, limit=max(limit, 10))
    context = _context_for(conn, question, limit=limit)
    creative_ideas = _creative_ideas(conn, question, tool_context)
    provider = None
    provider_error = None
    try:
        provider = select_provider(
            backend,
            model=model,
            web=web,
            web_max_results=web_max_results,
            web_domains=web_domains,
        )
    except ProviderError as exc:
        if backend != "auto":
            raise
        provider_error = str(exc)

    web_results: list[WebResult] = []
    web_error = None
    if web and (provider is None or provider.name == "ollama"):
        try:
            web_results = community_web_context(question, max_results=web_max_results, domains=web_domains)
        except WebSearchError as exc:
            web_error = str(exc)

    if provider is None:
        return _local_answer(
            question,
            exact,
            context,
            tool_context=tool_context,
            creative_ideas=creative_ideas,
            web_results=web_results,
            provider_error=provider_error,
            web_error=web_error,
        )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_prompt(question, exact, context, tool_context, creative_ideas, web_results, web_error)},
    ]
    try:
        result = provider.chat(messages)
    except ProviderError as exc:
        if backend != "auto":
            raise
        return _local_answer(
            question,
            exact,
            context,
            tool_context=tool_context,
            creative_ideas=creative_ideas,
            web_results=web_results,
            provider_error=str(exc),
            web_error=web_error,
        )
    return f"{result.text.strip()}\n\n(model: {result.provider}/{result.model})"


def _context_for(conn: sqlite3.Connection, question: str, *, limit: int) -> list[dict]:
    rows = strategy_context(conn, question, limit=limit)
    if rows:
        return rows
    return retrieve(conn, question, limit=limit)


def _creative_ideas(conn: sqlite3.Connection, question: str, tool_context: dict | None) -> list[creative.CreativeIdea]:
    plan = (tool_context or {}).get("plan") or {}
    intent = plan.get("intent")
    if intent not in {"strategy", "matchup"} and not plan.get("mechanics"):
        return []
    return creative.build_creative_ideas(conn, question, tool_context)


def _build_user_prompt(
    question: str,
    exact: dict | None,
    context: list[dict],
    tool_context: dict | None,
    creative_ideas: list[creative.CreativeIdea],
    web_results: list[WebResult],
    web_error: str | None,
) -> str:
    parts = [f"Question: {question}"]
    if exact:
        parts.append(f"Deterministic SQL result: {exact['answer']}")
        if exact.get("citations"):
            parts.append("SQL citations: " + "; ".join(exact["citations"]))
    if tool_context:
        parts.append(tool_context_to_prompt(tool_context))
    if creative_ideas:
        parts.append(creative.creative_ideas_to_prompt(creative_ideas))
    if context:
        parts.append("Retrieved context:")
        for item in context:
            parts.append(f"[{item['citation']}]\n{item['text']}")
    else:
        parts.append("Retrieved context: none")
    if web_results:
        parts.append(web_context_to_prompt(web_results))
    elif web_error:
        parts.append(f"Community web context: unavailable ({web_error})")
    return "\n\n".join(parts)


def _local_answer(
    question: str,
    exact: dict | None,
    context: list[dict],
    *,
    tool_context: dict | None = None,
    creative_ideas: list[creative.CreativeIdea] | None = None,
    web_results: list[WebResult] | None = None,
    provider_error: str | None,
    web_error: str | None = None,
) -> str:
    if exact:
        lines = [exact["answer"]]
        if exact.get("citations"):
            lines.append("Citations: " + "; ".join(exact["citations"]))
        if provider_error:
            lines.append(f"Model note: {provider_error}")
        return "\n".join(lines)

    has_tool_content = bool(tool_context and (tool_context.get("sections") or tool_context.get("notes")))
    if creative_ideas or has_tool_content:
        lines: list[str] = []
        if has_tool_content:
            lines.append(local_tool_answer(tool_context, provider_error=provider_error))
        elif provider_error:
            lines.append(f"Model note: {provider_error}")
        if creative_ideas:
            lines.append(creative.creative_ideas_to_local(creative_ideas))
        if web_results:
            lines.append(web_context_to_prompt(web_results))
        if web_error:
            lines.append(f"Web note: {web_error}")
        return "\n".join(lines)

    q = question.lower()
    if "best" in q and "card" in q:
        lines = [
            "There is no objective 'best card' fact in the JAR. The database has card text and mechanics, not win rates or tier lists.",
        ]
        if context:
            lines.append("Strong candidates to compare by role, from retrieved JAR facts:")
            for item in context[:8]:
                summary = item["text"].splitlines()[0]
                lines.append(f"- {summary} [{item['citation']}]")
        lines.append("Strategy/speculation: define the criterion first: best damage, best draw/energy, best defensive card, best boss-scaling card, or best overall rare.")
        if provider_error:
            lines.append(f"Model note: {provider_error}")
        return "\n".join(lines)

    if "ironclad" in q and "infinite" in q and context:
        lines = [
            "Strategy from JAR facts only: an Ironclad infinite shell should combine a repeatable draw/energy card with deck thinning and a condition enabler.",
        ]
        for item in context[:12]:
            summary = item["text"].splitlines()[0]
            lines.append(f"- {summary} [{item['citation']}]")
        lines.append("Speculation: Dropkick is the cleanest cited core because it draws and refunds energy when the enemy is Vulnerable; exhaust/draw tools help reduce the deck to the loop.")
        if provider_error:
            lines.append(f"Model note: {provider_error}")
        return "\n".join(lines)

    if "ironclad" in q and "block" in q and context:
        lines = [
            "Strategy from JAR facts only: Ironclad block shells should start with the cards whose text directly scales or spends Block.",
        ]
        for item in context[:8]:
            summary = item["text"].splitlines()[0]
            lines.append(f"- {summary} [{item['citation']}]")
        lines.append(
            "Speculation: prioritize reliable block generation, then add payoffs like Body Slam/Barricade-style scaling when the retrieved card facts support them."
        )
        lines.append("Model note: no OpenRouter key or running Ollama model was available, so this is the local fallback answer.")
        return "\n".join(lines)

    if context:
        lines = ["I found these JAR-derived matches:"]
        for item in context[:8]:
            first = item["text"].splitlines()[0]
            lines.append(f"- {first} [{item['citation']}]")
        lines.append("A configured Ollama/OpenRouter model can synthesize a fuller answer from these citations.")
        return "\n".join(lines)
    return "I could not find that in the JAR-derived database. If this is a strategy question, configure Ollama or OpenRouter for synthesis."
