"""Reusable game database tools for strategy-oriented questions."""

from __future__ import annotations

from dataclasses import dataclass
import re
import sqlite3
from typing import Any


CLASS_COLORS = {
    "ironclad": "RED",
    "silent": "GREEN",
    "defect": "BLUE",
    "watcher": "PURPLE",
    "colorless": "COLORLESS",
}

COLOR_LABELS = {
    "RED": "Ironclad",
    "GREEN": "Silent",
    "BLUE": "Defect",
    "PURPLE": "Watcher",
    "COLORLESS": "Colorless",
    "CURSE": "Curse",
}

KIND_WORDS = {
    "card": "card",
    "cards": "card",
    "relic": "relic",
    "relics": "relic",
    "monster": "monster",
    "monsters": "monster",
    "potion": "potion",
    "potions": "potion",
    "event": "event",
    "events": "event",
    "power": "power",
    "powers": "power",
    "achievement": "achievement",
    "achievements": "achievement",
}

MECHANIC_TRIGGERS = {
    "poison": {"poison", "catalyst", "toxic"},
    "shiv": {"shiv", "shivs"},
    "orb_slot": {"orb", "orbs", "slot", "slots"},
    "orb": {"orb", "orbs", "focus", "lightning", "frost", "dark", "plasma"},
    "focus": {"focus"},
    "stance": {"stance", "stances", "wrath", "calm", "divinity"},
    "draw": {"draw", "drawing", "cycle", "cycling"},
    "energy": {"energy", "refund", "free"},
    "zero_cost": {"free", "zero", "0-cost", "costless"},
    "shuffle": {"shuffle", "shuffling"},
    "exhaust": {"exhaust", "exhausting"},
    "vulnerable": {"vulnerable", "vuln"},
    "block": {"block", "defense", "defensive"},
    "card_spam": {"spam", "many", "cheap", "infinite", "loop"},
    "cross_color": {"prismatic", "cross", "off-class", "offclass", "other character", "other characters", "two characters", "other colors"},
    "random_card": {"random", "discover", "generate", "created", "creation"},
    "copy": {"copy", "duplicate", "twice", "double"},
    "transform_remove": {"remove", "removal", "transform", "thin", "minimalist"},
}

MECHANIC_PATTERNS = {
    "poison": ["%Poison%"],
    "shiv": ["%Shiv%", "%shiv%"],
    "orb_slot": ["%Orb slot%", "%Orb slots%"],
    "orb": ["%Orb%", "%Channel%", "%Focus%", "%Lightning%", "%Frost%", "%Dark%", "%Plasma%"],
    "focus": ["%Focus%"],
    "stance": ["%stance%", "%Stance%", "%Wrath%", "%Calm%", "%Divinity%"],
    "draw": ["%draw %", "%draws%", "%Draw %", "%draw !%", "%draw 1%", "%draw 2%", "%draw 3%", "%draw 4%", "%draw 5%"],
    "energy": ["%[E]%", "%Energy%", "%energy%", "%gain [E]%", "%Gain [E]%", "%costs 0%", "%Costs 0%"],
    "zero_cost": ["%costs 0%", "%Costs 0%", "%cost 0%", "%Cost 0%", "%zero%", "%free%"],
    "shuffle": ["%shuffle%", "%Shuffle%"],
    "exhaust": ["%Exhaust%", "%exhaust%"],
    "vulnerable": ["%Vulnerable%", "%vulnerable%"],
    "block": ["%Block%", "%block%"],
    "card_spam": ["%Whenever you play%", "%played this turn%", "%play a card%", "%play an Attack%", "%Shiv%"],
    "cross_color": ["%cards from other colors%", "%Colorless cards%", "%of any color%"],
    "random_card": ["%random card%", "%random Attack%", "%random Skill%", "%random Power%", "%Choose 1 of 3 random%", "%Choose one of 3 random%"],
    "copy": ["%play twice%", "%twice%", "%copy%", "%Copy%", "%duplicate%", "%Duplicate%", "%next Skill%", "%next card%"],
    "transform_remove": ["%remove%", "%Remove%", "%transform%", "%Transform%"],
}

MECHANIC_SCORE_TERMS = {
    "poison": ["poison", "catalyst"],
    "shiv": ["shiv", "shivs"],
    "orb_slot": ["orb slot", "orb slots"],
    "orb": ["orb", "orbs", "channel", "focus", "lightning", "frost", "dark", "plasma"],
    "focus": ["focus"],
    "stance": ["stance", "stances", "wrath", "calm", "divinity", "draw"],
    "draw": ["draw", "draws"],
    "energy": ["energy", "[e]", "costs 0", "gain"],
    "zero_cost": ["costs 0", "cost 0", "free", "zero"],
    "shuffle": ["shuffle", "shuffles"],
    "exhaust": ["exhaust", "exhausts"],
    "vulnerable": ["vulnerable"],
    "block": ["block"],
    "card_spam": ["whenever you play", "played this turn", "play a card", "shiv"],
    "cross_color": ["other colors", "colorless cards", "any color"],
    "random_card": ["random card", "random attack", "random skill", "random power"],
    "copy": ["twice", "copy", "duplicate", "next skill", "next card"],
    "transform_remove": ["remove", "transform"],
}

SYNERGY_COMPLEMENTS = {
    "poison": ["copy", "draw", "energy", "random_card"],
    "shiv": ["card_spam", "draw", "energy", "block"],
    "orb": ["orb_slot", "focus", "draw", "energy"],
    "orb_slot": ["orb", "focus", "draw"],
    "stance": ["draw", "energy", "zero_cost", "block", "card_spam"],
    "block": ["draw", "energy", "card_spam"],
    "exhaust": ["draw", "energy", "block", "random_card"],
    "vulnerable": ["draw", "energy", "card_spam"],
    "cross_color": ["random_card", "copy", "draw", "energy", "card_spam"],
}

HIGH_LEVEL_EXPANSIONS = {
    "infinite": ["draw", "energy", "zero_cost", "shuffle", "card_spam"],
    "loop": ["draw", "energy", "zero_cost", "shuffle", "card_spam"],
    "combo": ["draw", "energy", "copy", "card_spam"],
    "best": ["draw", "energy", "block", "card_spam"],
    "broken": ["draw", "energy", "copy", "card_spam", "random_card"],
}

STOP_TERMS = {
    "the", "what", "which", "with", "about", "that", "this", "from", "into",
    "card", "cards", "relic", "relics", "monster", "monsters", "game", "deck",
    "ways", "should", "look", "have", "having", "come", "possible", "using",
    "for", "are", "can", "could", "would", "two", "one", "character", "characters",
    "things", "thing", "best", "broken", "limit", "maximum", "theoretical", "theorical",
}


@dataclass(frozen=True)
class ToolItem:
    kind: str
    entity_id: str
    name: str
    source_path: str
    text: str
    score: float = 0.0

    @property
    def citation(self) -> str:
        return f"{self.kind}:{self.entity_id}"


def build_game_tool_context(conn: sqlite3.Connection, question: str, *, limit: int = 8) -> dict[str, Any]:
    """Run reusable SQL tools that give the model broad game context."""
    q = question.lower()
    color = _requested_color(q)
    requested_kinds = _requested_kinds(q)
    mechanics = _detect_mechanics(q)
    sections: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    if _is_strategy_question(q) and not mechanics:
        mechanics.extend(["draw", "energy", "block"])

    literal_terms = [term for term in _terms(question) if term not in CLASS_COLORS]
    if literal_terms and not mechanics:
        items = search_entities(conn, literal_terms, kinds=requested_kinds or None, color=color, limit=limit)
        _append_section(sections, seen, "search_entities", f"literal search: {', '.join(literal_terms[:5])}", items)

    for mechanic in mechanics[:8]:
        kinds = _mechanic_kinds_for(q, mechanic, requested_kinds)
        items = find_by_mechanic(conn, mechanic, kinds=kinds, color=color, limit=limit)
        _append_section(sections, seen, "find_by_mechanic", f"mechanic: {mechanic}", items)

    complement_mechanics = _complement_mechanics(mechanics)
    if complement_mechanics:
        items = expand_synergy(conn, complement_mechanics, color=color, limit=max(limit, 10))
        _append_section(sections, seen, "expand_synergy", f"complementary mechanics: {', '.join(complement_mechanics[:6])}", items)

    if _mentions(q, {"counter", "counters", "weak", "weakness", "bad against", "good against"}):
        monster_items = find_monster_mechanics(conn, mechanics, limit=limit)
        _append_section(sections, seen, "find_monster_mechanics", "monster mechanics related to the requested matchup", monster_items)

    notes = _analysis_notes(q, mechanics, sections)
    return {
        "plan": {
            "color": COLOR_LABELS.get(color, color) if color else None,
            "requested_kinds": requested_kinds,
            "mechanics": mechanics,
            "complements": complement_mechanics,
            "intent": _intent(q),
        },
        "sections": sections,
        "notes": notes,
    }


def search_entities(
    conn: sqlite3.Connection,
    terms: list[str],
    *,
    kinds: list[str] | None = None,
    color: str | None = None,
    limit: int = 8,
) -> list[ToolItem]:
    useful = [term for term in terms if term and term not in STOP_TERMS]
    if not useful:
        return []
    clauses = []
    params: list[Any] = []
    for term in useful[:6]:
        pattern = f"%{term}%"
        clauses.append("(e.name LIKE ? OR e.id LIKE ? OR ch.text LIKE ?)")
        params.extend([pattern, pattern, pattern])
    return _query_items(
        conn,
        " OR ".join(clauses),
        params,
        kinds=kinds,
        color=color,
        requested_terms=useful,
        limit=limit,
    )


def find_by_mechanic(
    conn: sqlite3.Connection,
    mechanic: str,
    *,
    kinds: list[str] | None = None,
    color: str | None = None,
    limit: int = 8,
) -> list[ToolItem]:
    patterns = MECHANIC_PATTERNS.get(mechanic)
    if not patterns:
        return []
    clauses = []
    params: list[Any] = []
    for pattern in patterns:
        clauses.append("(e.name LIKE ? OR ch.text LIKE ?)")
        params.extend([pattern, pattern])
    return _query_items(
        conn,
        " OR ".join(clauses),
        params,
        kinds=kinds,
        color=color,
        requested_terms=MECHANIC_SCORE_TERMS.get(mechanic, [mechanic]),
        limit=limit,
    )


def expand_synergy(
    conn: sqlite3.Connection,
    mechanics: list[str],
    *,
    color: str | None = None,
    limit: int = 12,
) -> list[ToolItem]:
    items: list[ToolItem] = []
    seen: set[tuple[str, str]] = set()
    per_mechanic = max(3, limit // max(len(mechanics), 1))
    for mechanic in mechanics[:8]:
        found = find_by_mechanic(conn, mechanic, kinds=["card", "relic", "power"], color=color, limit=per_mechanic)
        for item in found:
            key = (item.kind, item.entity_id)
            if key not in seen:
                seen.add(key)
                items.append(item)
    return items[:limit]


def find_monster_mechanics(conn: sqlite3.Connection, mechanics: list[str], *, limit: int = 8) -> list[ToolItem]:
    monster_mechanics = list(mechanics)
    if "shiv" in monster_mechanics or "card_spam" in monster_mechanics:
        monster_mechanics.extend(["card_spam", "block"])
    items: list[ToolItem] = []
    seen: set[tuple[str, str]] = set()
    for mechanic in monster_mechanics[:6]:
        found = find_by_mechanic(conn, mechanic, kinds=["monster", "power"], limit=limit)
        for item in found:
            key = (item.kind, item.entity_id)
            if key not in seen:
                seen.add(key)
                items.append(item)
    return items[:limit]


def tool_context_to_prompt(context: dict[str, Any]) -> str:
    if not context.get("sections") and not context.get("notes"):
        return "Game database tool results: none"
    parts = ["Game database tool results:"]
    plan = context.get("plan") or {}
    plan_bits = []
    if plan.get("intent"):
        plan_bits.append(f"intent={plan['intent']}")
    if plan.get("color"):
        plan_bits.append(f"character/color={plan['color']}")
    if plan.get("mechanics"):
        plan_bits.append("mechanics=" + ", ".join(plan["mechanics"]))
    if plan_bits:
        parts.append("Plan: " + "; ".join(plan_bits))
    for note in context.get("notes", []):
        parts.append(f"Note: {note}")
    for section in context.get("sections", []):
        parts.append(f"Tool: {section['tool']} ({section['label']})")
        for item in section.get("items", [])[:10]:
            parts.append(f"- [{item.citation}] {item.name} ({item.kind}): {_compact(item.text, 420)}")
    return "\n".join(parts)


def local_tool_answer(context: dict[str, Any], *, provider_error: str | None = None) -> str:
    lines = ["Tool-guided answer from JAR-derived data:"]
    for note in context.get("notes", []):
        lines.append(f"- {note}")
    for section in context.get("sections", [])[:6]:
        items = section.get("items", [])
        if not items:
            continue
        lines.append(f"{section['label']}:")
        for item in items[:6]:
            lines.append(f"- {item.name}: {_compact(item.text, 180)} [{item.citation}]")
    lines.append("Strategy/speculation: combine the cited mechanics above; JAR facts support the components, while the final deck idea is inferred rather than a logged win-rate claim.")
    if provider_error:
        lines.append(f"Model note: {provider_error}")
    return "\n".join(lines)


def _query_items(
    conn: sqlite3.Connection,
    where_sql: str,
    params: list[Any],
    *,
    kinds: list[str] | None,
    color: str | None,
    requested_terms: list[str],
    limit: int,
) -> list[ToolItem]:
    filters = [f"({where_sql})"]
    query_params = list(params)
    if kinds:
        placeholders = ", ".join("?" for _ in kinds)
        filters.append(f"e.kind IN ({placeholders})")
        query_params.extend(kinds)
    if color:
        filters.append("(e.kind != 'card' OR color.value_text = ?)")
        query_params.append(color)
    filters.append(
        """
        NOT EXISTS (
            SELECT 1 FROM facts p
            WHERE p.entity_kind = e.kind
              AND p.entity_id = e.id
              AND p.key = 'package'
              AND p.value_text = 'deprecated'
        )
        """
    )
    filters.append("e.name NOT LIKE 'DEPRECATED%'")
    filters.append("e.source_path NOT LIKE '%/deprecated/%'")
    sql = f"""
        SELECT e.kind, e.id, e.name, e.source_path, ch.text,
               color.value_text AS color, rarity.value_text AS rarity,
               type.value_text AS card_type, cost.value_num AS cost
        FROM entities e
        JOIN chunks ch ON ch.entity_kind = e.kind AND ch.entity_id = e.id
        LEFT JOIN facts color ON color.entity_kind = e.kind
            AND color.entity_id = e.id
            AND color.key = 'color'
        LEFT JOIN facts rarity ON rarity.entity_kind = e.kind
            AND rarity.entity_id = e.id
            AND rarity.key = 'rarity'
        LEFT JOIN facts type ON type.entity_kind = e.kind
            AND type.entity_id = e.id
            AND type.key = 'type'
        LEFT JOIN facts cost ON cost.entity_kind = e.kind
            AND cost.entity_id = e.id
            AND cost.key = 'cost'
        WHERE {' AND '.join(filters)}
        LIMIT 200
    """
    rows = conn.execute(sql, query_params).fetchall()
    scored = [_row_item(row, _score_row(row, requested_terms, kinds, color)) for row in rows]
    scored.sort(key=lambda item: (-item.score, _kind_priority(item.kind, kinds), item.name))
    return _dedupe_items(scored)[:limit]


def _row_item(row: sqlite3.Row, score: float) -> ToolItem:
    return ToolItem(
        kind=row["kind"],
        entity_id=row["id"],
        name=row["name"],
        source_path=row["source_path"],
        text=row["text"],
        score=score,
    )


def _score_row(row: sqlite3.Row, terms: list[str], kinds: list[str] | None, color: str | None) -> float:
    text = f"{row['name']} {row['id']} {row['text']}".lower()
    score = 0.0
    for term in terms:
        if term.lower() in row["name"].lower():
            score += 12.0
        if term.lower() in text:
            score += 4.0
    if row["kind"] == "relic" and any(term.lower() in text for term in terms):
        score += 20.0
    if kinds and row["kind"] in kinds:
        kind_index = kinds.index(row["kind"])
        score += 35.0 if kind_index == 0 else max(0, 12 - (kind_index * 2))
    if color and row["kind"] == "card" and row["color"] == color:
        score += 14.0
    elif color and row["kind"] not in {"card", "relic"}:
        score -= 6.0
    if row["kind"] == "relic":
        score += 2.0
    if row["rarity"] == "RARE":
        score += 1.0
    if row["card_type"] == "POWER":
        score += 1.0
    return score


def _append_section(
    sections: list[dict[str, Any]],
    seen: set[tuple[str, str]],
    tool: str,
    label: str,
    items: list[ToolItem],
) -> None:
    unique = []
    for item in items:
        key = (item.kind, item.entity_id)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    if unique:
        sections.append({"tool": tool, "label": label, "items": unique})


def _detect_mechanics(question: str) -> list[str]:
    mechanics: list[str] = []
    for mechanic, triggers in MECHANIC_TRIGGERS.items():
        if _mentions(question, triggers):
            mechanics.append(mechanic)
    for term, expansions in HIGH_LEVEL_EXPANSIONS.items():
        if term in question:
            mechanics.extend(expansions)
    if "watcher" in question and _mentions(question, {"infinite", "loop", "combo"}):
        mechanics.extend(["stance", "draw", "energy"])
    if "ironclad" in question and _mentions(question, {"infinite", "loop", "combo"}):
        mechanics.extend(["vulnerable", "exhaust", "draw", "energy"])
    if "defect" in question and _mentions(question, {"orb", "orbs", "loop", "combo"}):
        mechanics.extend(["orb", "orb_slot", "focus", "draw"])
    if "silent" in question and _mentions(question, {"poison", "shiv", "loop", "combo"}):
        mechanics.extend(["draw", "energy"])
    mechanics = _ordered_unique(mechanics)
    priority: list[str] = []
    if "watcher" in question:
        priority.extend(["stance", "draw", "energy"])
    if "defect" in question or "orb" in question or "orbs" in question:
        priority.extend(["orb_slot", "orb", "focus"])
    if "poison" in question:
        priority.extend(["poison", "copy", "draw", "energy"])
    if "cross" in question or "prismatic" in question or "other character" in question or "other colors" in question:
        priority.extend(["cross_color", "random_card", "copy"])
    return _ordered_unique([item for item in priority if item in mechanics] + mechanics)


def _complement_mechanics(mechanics: list[str]) -> list[str]:
    complements: list[str] = []
    for mechanic in mechanics:
        complements.extend(SYNERGY_COMPLEMENTS.get(mechanic, []))
    return [item for item in _ordered_unique(complements) if item not in mechanics]


def _analysis_notes(question: str, mechanics: list[str], sections: list[dict[str, Any]]) -> list[str]:
    notes = []
    if "best" in question:
        notes.append("There is no objective best-card fact in the JAR; it contains mechanics, text, and numbers, not a win-rate tier list.")
    if _mentions(question, {"limit", "maximum", "max", "theoretical", "theorical"}) and "orb_slot" in mechanics:
        notes.append("No fixed numeric hard cap for orb slots was found in the retrieved JAR text; cited effects show ways to add or remove slots.")
    if "never" in question or "brand new" in question:
        notes.append("Novelty cannot be proven from JAR facts alone; add community/run corpora to check whether an idea is already known.")
    if "cross_color" in mechanics:
        notes.append("Cross-character claims should distinguish permanent rewards from temporary/random card generation.")
    if not sections:
        notes.append("No broad mechanic matches were found; the answer should say what is missing instead of guessing.")
    return notes


def _mechanic_kinds_for(question: str, mechanic: str, requested_kinds: list[str]) -> list[str]:
    if mechanic == "cross_color":
        return ["relic", "card", "potion", "power", "event", "keyword"]
    if requested_kinds:
        extras = ["card", "relic", "power", "potion", "event", "keyword", "monster"]
        return _ordered_unique([*requested_kinds, *extras])
    if mechanic == "stance":
        return ["relic", "card", "power", "potion", "event", "keyword"]
    if mechanic in {"orb_slot", "orb", "focus"}:
        return ["card", "relic", "power", "potion", "monster"]
    if mechanic in {"stance", "draw", "energy", "zero_cost", "shuffle", "block"}:
        return ["card", "relic", "power", "potion", "event", "keyword"]
    if mechanic in {"poison", "shiv", "exhaust", "vulnerable", "card_spam", "copy", "random_card"}:
        return ["card", "relic", "power", "potion", "event", "keyword"]
    if _is_strategy_question(question):
        return ["card", "relic", "power", "potion", "event", "keyword", "monster"]
    return ["card", "relic", "monster", "power", "potion", "event", "keyword", "achievement"]


def _requested_color(question: str) -> str | None:
    for term, color in CLASS_COLORS.items():
        if term in question:
            return color
    return None


def _requested_kinds(question: str) -> list[str]:
    kinds = [kind for word, kind in KIND_WORDS.items() if word in question]
    return _ordered_unique(kinds)


def _intent(question: str) -> str:
    if _mentions(question, {"highest", "lowest", "cheapest", "how many", "count"}):
        return "exact_fact"
    if _mentions(question, {"strategy", "deck", "build", "combo", "infinite", "loop", "broken", "best"}):
        return "strategy"
    if _mentions(question, {"counter", "weak", "good against", "bad against"}):
        return "matchup"
    return "lookup"


def _is_strategy_question(question: str) -> bool:
    return _intent(question) in {"strategy", "matchup"}


def _terms(question: str) -> list[str]:
    terms = []
    for term in re.findall(r"[A-Za-z][A-Za-z0-9_'-]{2,}", question.lower()):
        if term not in STOP_TERMS and term not in terms:
            terms.append(term)
    return terms


def _mentions(question: str, words: set[str]) -> bool:
    return any(word in question for word in words)


def _ordered_unique(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _dedupe_items(items: list[ToolItem]) -> list[ToolItem]:
    seen = set()
    result = []
    for item in items:
        key = (item.kind, item.entity_id)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _kind_priority(kind: str, requested: list[str] | None) -> int:
    if requested and kind in requested:
        return requested.index(kind)
    order = ["card", "relic", "power", "potion", "event", "keyword", "monster", "achievement"]
    return order.index(kind) if kind in order else len(order)


def _compact(text: str, limit: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)].rstrip() + "..."
