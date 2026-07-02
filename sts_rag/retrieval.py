"""Deterministic facts and retrieval helpers."""

from __future__ import annotations

import json
import math
import re
import sqlite3
from typing import Any

from . import creative


CLASS_COLORS = {
    "ironclad": "RED",
    "silent": "GREEN",
    "defect": "BLUE",
    "watcher": "PURPLE",
    "colorless": "COLORLESS",
}
CLASS_ENTITY_IDS = {
    "ironclad": "ironclad",
    "silent": "silent",
    "defect": "defect",
    "watcher": "watcher",
}
COLOR_LABELS = {
    "RED": "Ironclad",
    "GREEN": "Silent",
    "BLUE": "Defect",
    "PURPLE": "Watcher",
    "COLORLESS": "Colorless",
    "CURSE": "Curse",
}
RARITY_TERMS = {
    "basic": "BASIC",
    "common": "COMMON",
    "uncommon": "UNCOMMON",
    "rare": "RARE",
    "special": "SPECIAL",
    "curse": "CURSE",
}
POWER_LABELS = {
    "ArtifactPower": "Artifact",
    "BeatOfDeathPower": "Beat Of Death",
    "FlightPower": "Flight",
    "IntangiblePower": "Intangible",
    "InvinciblePower": "Invincible",
    "ModeShiftPower": "Mode Shift",
    "PainfulStabsPower": "Painful Stabs",
    "SharpHidePower": "Sharp Hide",
    "ThornsPower": "Thorns",
    "TimeWarpPower": "Time Warp",
}

INFINITE_SEEDS = {
    "RED": [
        "Dropkick",
        "Bash",
        "Uppercut",
        "Thunderclap",
        "Pommel Strike",
        "Shrug It Off",
        "Offering",
        "Burning Pact",
        "Dark Embrace",
        "Corruption",
        "Sentinel",
        "Exhume",
        "Headbutt",
        "Flash of Steel",
        "Finesse",
        "Deep Breath",
        "Sundial",
        "Unceasing Top",
        "Abacus",
    ],
    "GREEN": [
        "Tactician",
        "Reflex",
        "Acrobatics",
        "Burst",
        "Adrenaline",
        "After Image",
        "Cloak and Dagger",
        "Blade Dance",
        "Infinite Blades",
        "Accuracy",
        "Sundial",
        "Unceasing Top",
    ],
    "BLUE": [
        "Echo Form",
        "All for One",
        "Hologram",
        "Machine Learning",
        "Seek",
        "Turbo",
        "Loop",
        "Defragment",
        "Capacitor",
        "Sundial",
        "Unceasing Top",
    ],
    "PURPLE": [
        "Rushdown",
        "Tantrum",
        "Eruption",
        "Fear No Evil",
        "Flurry of Blows",
        "Empty Fist",
        "Vigilance",
        "Mental Fortress",
        "Simmering Fury",
        "Sundial",
        "Unceasing Top",
    ],
}

BROAD_BEST_SEEDS = [
    "Offering",
    "Corruption",
    "Dark Embrace",
    "Adrenaline",
    "Wraith Form",
    "Seek",
    "Biased Cognition",
    "Echo Form",
    "Vault",
    "Scrawl",
    "Talk to the Hand",
    "Apotheosis",
    "Hand of Greed",
]
SHIV_COUNTER_MONSTERS = [
    "TimeEater",
    "Spiker",
    "TheGuardian",
    "Nemesis",
    "CorruptHeart",
]
SHIV_WEAK_MONSTERS = [
    "Byrd",
    "GremlinLeader",
    "Reptomancer",
    "Dagger",
    "TheCollector",
]
MINIMALIST_SEEDS = [
    "Minimalist",
    "Peace Pipe",
    "Empty Cage",
    "Smiling Mask",
    "Singing Bowl",
    "Busted Crown",
    "Purifier",
    "Living Wall",
    "The Cleric",
    "Wheel of Change",
    "Pandora's Box",
]


def exact_answer(conn: sqlite3.Connection, question: str) -> dict[str, Any] | None:
    q = question.lower()
    if "monster" in q and ("artifact" in q or "artifacts" in q):
        return monsters_with_power_answer(conn, "ArtifactPower")
    if "shiv" in q and "monster" in q and _mentions(q, {"counter", "counters", "bad", "hard", "hate"}):
        return shiv_matchup_answer(conn, weakness=False)
    if "shiv" in q and "monster" in q and _mentions(q, {"weak", "good", "best", "easy", "vulnerable"}):
        return shiv_matchup_answer(conn, weakness=True)
    if _mentions(q, {"achievement", "minimalist"}) and ("5" in q or "five" in q or "less" in q or "fewer" in q or "minimalist" in q):
        return minimalist_answer(conn)
    if ("starting" in q or "starter" in q) and "deck" in q:
        return starting_deck_answer(conn, q)
    if "highest" in q and "cost" in q and "card" in q:
        return highest_cost_card(conn, rarity=_requested_rarity(q), color=_requested_color(q), question=q)
    if ("lowest" in q or "cheapest" in q) and "cost" in q and "card" in q:
        return lowest_cost_card(conn, rarity=_requested_rarity(q), color=_requested_color(q), question=q)
    if "how many" in q and "card" in q:
        row = conn.execute("SELECT COUNT(*) AS n FROM entities WHERE kind = 'card'").fetchone()
        return {
            "kind": "count",
            "answer": f"The JAR extractor found {row['n']} card classes.",
            "citations": ["entities:card"],
        }
    detail = _maybe_entity_detail(conn, q)
    if detail:
        return detail
    return None


def starting_deck_answer(conn: sqlite3.Connection, question: str) -> dict[str, Any]:
    requested = _requested_character_ids(question) or list(CLASS_ENTITY_IDS.values())
    rows = []
    for character_id in requested:
        row = conn.execute(
            "SELECT * FROM entities WHERE kind = 'character' AND id = ?",
            (character_id,),
        ).fetchone()
        if row:
            rows.append(row)
    if not rows:
        return {
            "kind": "exact",
            "answer": "I could not find extracted starting deck data for that character.",
            "citations": [],
        }

    lines: list[str] = []
    citations: list[str] = []
    for row in rows:
        data = json.loads(row["data_json"])
        deck = data.get("starting_deck", [])
        summary, card_citations = _format_starting_deck(conn, deck)
        lines.append(f"{row['name']} starts with {len(deck)} cards: {summary}.")
        citations.append(f"character:{row['id']} -> {row['source_path']}")
        citations.extend(card_citations)
    return {
        "kind": "exact",
        "answer": " ".join(lines),
        "citations": citations,
    }


def monsters_with_power_answer(conn: sqlite3.Connection, power_class: str) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT e.id, e.name, e.source_path
        FROM entities e
        JOIN facts f ON f.entity_kind = e.kind
            AND f.entity_id = e.id
            AND f.key = 'referenced_powers'
            AND f.value_text = ?
        WHERE e.kind = 'monster'
        ORDER BY e.name
        """,
        (power_class,),
    ).fetchall()
    label = POWER_LABELS.get(power_class, power_class)
    if not rows:
        return {
            "kind": "exact",
            "answer": f"I could not find monsters referencing {label} in the extracted monster bytecode.",
            "citations": [],
        }
    names = ", ".join(row["name"] for row in rows)
    return {
        "kind": "exact",
        "answer": f"Monsters whose extracted bytecode references {label}: {names}.",
        "citations": [f"monster:{row['id']} -> {row['source_path']}" for row in rows],
    }


def shiv_matchup_answer(conn: sqlite3.Connection, *, weakness: bool) -> dict[str, Any]:
    if weakness:
        rows = _entities_by_ids(conn, "monster", SHIV_WEAK_MONSTERS)
        answer = (
            "Strategy/speculation from JAR facts: shiv decks are best into monsters where many cheap "
            "Attack plays matter. Byrds are the clearest case because Flight is cancelled after several "
            "attack-damage hits; shivs also clean up minion fights well, so Gremlin Leader, Reptomancer, "
            "Snake Dagger/Reptomancer daggers, and The Collector are favorable targets when your shiv engine "
            "is online."
        )
        extra = _entities_by_names(conn, [("power", "Flight"), ("card", "Blade Dance"), ("card", "Accuracy"), ("card", "Finisher"), ("card", "After Image")])
    else:
        rows = _entities_by_ids(conn, "monster", SHIV_COUNTER_MONSTERS)
        answer = (
            "Strategy/speculation from JAR facts: the main shiv counters are Time Eater, Spiker, "
            "The Guardian, Nemesis, and the Corrupt Heart. Time Warp punishes playing many cards, "
            "Thorns/Sharp Hide punish repeated Attacks, Intangible blanks many small hits, and the Heart's "
            "Beat Of Death/Invincible-style mechanics punish card spam and cap burst."
        )
        extra = _entities_by_names(conn, [
            ("power", "Time Warp"),
            ("power", "Thorns"),
            ("power", "Sharp Hide"),
            ("power", "Intangible"),
            ("power", "BeatOfDeath"),
            ("power", "Invincible"),
        ])
    citations = [f"monster:{row['id']} -> {row['source_path']}" for row in rows]
    citations.extend(f"{row['kind']}:{row['id']} -> {row['source_path']}" for row in extra)
    return {"kind": "exact", "answer": answer, "citations": citations}


def minimalist_answer(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = _entities_by_names(conn, [
        ("achievement", "Minimalist"),
        ("relic", "Peace Pipe"),
        ("relic", "Empty Cage"),
        ("relic", "Smiling Mask"),
        ("relic", "Singing Bowl"),
        ("relic", "Busted Crown"),
        ("event", "Purifier"),
        ("event", "Living Wall"),
        ("event", "The Cleric"),
        ("event", "Wheel of Change"),
        ("relic", "Pandora's Box"),
    ])
    answer = (
        "Minimalist is the achievement for beating the game with a 5-card deck or smaller. "
        "Strategy/speculation from cited JAR facts: prioritize removals over card rewards, use shop removals "
        "aggressively, value Empty Cage/Peace Pipe/Smiling Mask highly, and take removal events such as "
        "Purifier, Living Wall, The Cleric, and Wheel of Change when offered. Singing Bowl and Busted Crown help "
        "avoid bloating the deck, while Pandora's Box can remove all Strike/Defend cards by transforming them, "
        "though it may leave you with more than five cards."
    )
    citations = [f"{row['kind']}:{row['id']} -> {row['source_path']}" for row in rows]
    return {"kind": "exact", "answer": answer, "citations": citations}


def highest_cost_card(
    conn: sqlite3.Connection,
    *,
    rarity: str | None = None,
    color: str | None = None,
    question: str = "",
) -> dict[str, Any]:
    rows = _cost_rows(conn, descending=True, rarity=rarity, color=color, question=question)
    if not rows:
        return {
            "kind": "exact",
            "answer": "I could not find extractable card cost facts in the database.",
            "citations": [],
        }
    top = rows[0]
    tied = [row for row in rows if row["cost"] == top["cost"]]
    names = ", ".join(_card_cost_label(row) for row in tied)
    scope = _cost_scope(rarity=rarity, color=color)
    return {
        "kind": "exact",
        "answer": f"The highest extractable base energy cost{scope} is {int(top['cost'])}: {names}.",
        "rows": [dict(row) for row in tied],
        "citations": [f"card:{row['id']} -> {row['source_path']}" for row in tied],
    }


def lowest_cost_card(
    conn: sqlite3.Connection,
    *,
    rarity: str | None = None,
    color: str | None = None,
    question: str = "",
) -> dict[str, Any]:
    rows = _cost_rows(conn, descending=False, rarity=rarity, color=color, question=question)
    if not rows:
        return {
            "kind": "exact",
            "answer": "I could not find extractable card cost facts in the database.",
            "citations": [],
    }
    top_cost = rows[0]["cost"]
    tied = [row for row in rows if row["cost"] == top_cost]
    names = ", ".join(_card_cost_label(row) for row in tied[:10])
    more = "" if len(tied) <= 10 else f" and {len(tied) - 10} more"
    scope = _cost_scope(rarity=rarity, color=color)
    return {
        "kind": "exact",
        "answer": f"The lowest extractable base energy cost{scope} is {int(top_cost)}: {names}{more}.",
        "rows": [dict(row) for row in tied],
        "citations": [f"card:{row['id']} -> {row['source_path']}" for row in tied[:10]],
    }


def _cost_rows(
    conn: sqlite3.Connection,
    *,
    descending: bool,
    rarity: str | None,
    color: str | None,
    question: str = "",
) -> list[sqlite3.Row]:
    joins = [
        """
        JOIN facts cost ON cost.entity_kind = e.kind
            AND cost.entity_id = e.id
            AND cost.key = 'cost'
        """,
        """
        JOIN facts package ON package.entity_kind = e.kind
            AND package.entity_id = e.id
            AND package.key = 'package'
            AND package.value_text != 'deprecated'
        """,
        """
        LEFT JOIN facts color ON color.entity_kind = e.kind
            AND color.entity_id = e.id
            AND color.key = 'color'
        """,
        """
        LEFT JOIN facts rarity ON rarity.entity_kind = e.kind
            AND rarity.entity_id = e.id
            AND rarity.key = 'rarity'
        """,
    ]
    where = ["e.kind = 'card'", "cost.value_num >= 0"]
    params: list[str] = []
    if rarity:
        where.append("rarity.value_text = ?")
        params.append(rarity)
    if color:
        where.append("color.value_text = ?")
        params.append(color)
    if color == "COLORLESS" and not _mentions(question, {"temp", "temporary", "generated", "special"}):
        where.append("package.value_text = 'colorless'")
    direction = "DESC" if descending else "ASC"
    sql = f"""
        SELECT e.kind, e.id, e.name, e.source_path, cost.value_num AS cost,
               color.value_text AS color, rarity.value_text AS rarity
        FROM entities e
        {' '.join(joins)}
        WHERE {' AND '.join(where)}
        ORDER BY cost.value_num {direction}, e.name ASC
        LIMIT 200
    """
    return conn.execute(sql, params).fetchall()


def _entities_by_ids(conn: sqlite3.Connection, kind: str, ids: list[str]) -> list[sqlite3.Row]:
    if not ids:
        return []
    placeholders = ", ".join("?" for _ in ids)
    order = " ".join(f"WHEN ? THEN {i}" for i, _id in enumerate(ids))
    return conn.execute(
        f"""
        SELECT kind, id, name, source_path
        FROM entities
        WHERE kind = ? AND id IN ({placeholders})
        ORDER BY CASE id {order} ELSE 999 END
        """,
        [kind, *ids, *ids],
    ).fetchall()


def _entities_by_names(conn: sqlite3.Connection, keys: list[tuple[str, str]]) -> list[sqlite3.Row]:
    rows: list[sqlite3.Row] = []
    seen: set[tuple[str, str]] = set()
    for kind, name in keys:
        row = conn.execute(
            """
            SELECT kind, id, name, source_path
            FROM entities
            WHERE kind = ? AND (name = ? OR id = ?)
            ORDER BY CASE WHEN name = ? THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (kind, name, name, name),
        ).fetchone()
        if row and (row["kind"], row["id"]) not in seen:
            seen.add((row["kind"], row["id"]))
            rows.append(row)
    return rows


def _card_cost_label(row: sqlite3.Row) -> str:
    character = COLOR_LABELS.get(row["color"], row["color"] or "Unknown")
    return f"{row['name']} ({character}, {int(row['cost'])})"


def _cost_scope(*, rarity: str | None, color: str | None) -> str:
    parts = []
    if rarity:
        parts.append(rarity.lower())
    if color:
        parts.append(COLOR_LABELS.get(color, color).lower())
    return "" if not parts else " among " + " ".join(parts) + " cards"


def _format_starting_deck(conn: sqlite3.Connection, deck: list[str]) -> tuple[str, list[str]]:
    counts: dict[str, int] = {}
    for card_id in deck:
        counts[card_id] = counts.get(card_id, 0) + 1
    names: dict[str, tuple[str, str]] = {}
    for card_id in counts:
        row = conn.execute(
            "SELECT name, source_path FROM entities WHERE kind = 'card' AND id = ?",
            (card_id,),
        ).fetchone()
        names[card_id] = (row["name"], row["source_path"]) if row else (card_id, "")
    summary = ", ".join(f"{count}x {names[card_id][0]}" for card_id, count in counts.items())
    citations = [
        f"card:{card_id} -> {source}"
        for card_id, (_name, source) in names.items()
        if source
    ]
    return summary, citations


DETAIL_TRIGGERS = (
    re.compile(r"details?\s+(?:on|about|for|of)\s+(.+)"),
    re.compile(r"tell me about\s+(.+)"),
    re.compile(r"(?:give|show)\s+(?:me\s+)?(?:the\s+)?(?:details?|info(?:rmation)?|stats?)\s+(?:on|about|for|of)\s+(.+)"),
    re.compile(r"info(?:rmation)?\s+(?:on|about)\s+(.+)"),
    re.compile(r"describe\s+(.+)"),
    re.compile(r"what does\s+(.+?)\s+do"),
    re.compile(r"what(?:'s| is)\s+(.+?)\s+do(?:es)?"),
)

_DETAIL_TRAILING_KINDS = {"card", "relic", "potion", "power", "monster", "event", "keyword", "achievement"}
_DETAIL_KIND_PRIORITY = ["card", "relic", "potion", "power", "keyword", "event", "monster", "character", "achievement"]

CARD_FLAG_LABELS = {
    "exhaust": "Exhaust",
    "is_ethereal": "Ethereal",
    "is_innate": "Innate",
    "retain": "Retain",
    "self_retain": "Retain",
}


def _maybe_entity_detail(conn: sqlite3.Connection, question: str) -> dict[str, Any] | None:
    target = _detail_target(question)
    if not target:
        return None
    return entity_detail_answer(conn, target)


def _detail_target(question: str) -> str | None:
    for pattern in DETAIL_TRIGGERS:
        match = pattern.search(question)
        if not match:
            continue
        candidate = match.group(1).strip().strip("?.!").strip()
        candidate = re.sub(r"^(?:a|an|the)\s+", "", candidate)
        words = candidate.split()
        if words and words[-1] in _DETAIL_TRAILING_KINDS:
            words = words[:-1]
        candidate = " ".join(words).strip()
        if candidate:
            return candidate
    return None


def find_entity_by_name(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    """Resolve a free-text name to a single entity, normalized and ranked across kinds."""
    query = _norm(name)
    if not query:
        return None
    rows = conn.execute(
        "SELECT kind, id, name, source_path, data_json FROM entities"
    ).fetchall()
    best: tuple[tuple[int, int, int], sqlite3.Row] | None = None
    for row in rows:
        name_norm = _norm(row["name"])
        id_norm = _norm(row["id"])
        rank: int | None = None
        if query in {name_norm, id_norm}:
            rank = 0
        elif name_norm.startswith(query) or query.startswith(name_norm):
            rank = 1
        elif id_norm.startswith(query) or query.startswith(id_norm):
            rank = 2
        elif query in name_norm or (len(query) >= 5 and name_norm in query):
            rank = 3
        if rank is None:
            continue
        kind_priority = _DETAIL_KIND_PRIORITY.index(row["kind"]) if row["kind"] in _DETAIL_KIND_PRIORITY else len(_DETAIL_KIND_PRIORITY)
        key = (rank, kind_priority, len(row["name"]))
        if best is None or key < best[0]:
            best = (key, row)
    if best is None:
        return None
    row = best[1]
    data = json.loads(row["data_json"])
    chunk = conn.execute(
        "SELECT text FROM chunks WHERE entity_kind = ? AND entity_id = ? LIMIT 1",
        (row["kind"], row["id"]),
    ).fetchone()
    return {
        "kind": row["kind"],
        "id": row["id"],
        "name": row["name"],
        "source_path": row["source_path"],
        "data": data,
        "facts": data.get("facts", {}),
        "text": chunk["text"] if chunk else "",
    }


def entity_detail_answer(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    ent = find_entity_by_name(conn, name)
    if ent is None:
        return None
    facts = ent["facts"] or {}
    data = ent["data"] or {}
    lines = [f"{ent['name']} ({ent['kind']})"]

    facts_line = _detail_facts_line(ent["kind"], facts)
    if facts_line:
        lines.append(facts_line)

    description = data.get("rendered_description") or data.get("description") or ""
    if description:
        lines.append("Description:")
        lines.append(f"- {description}")
    extended = data.get("extended_description")
    if extended:
        lines.append(f"- Upgraded/extended: {extended}")
    if data.get("flavor"):
        lines.append(f"- Flavor: {data['flavor']}")
    if data.get("moves"):
        lines.append(f"- Moves: {data['moves']}")

    citations = [f"{ent['kind']}:{ent['id']} -> {ent['source_path']}"]

    color = facts.get("color")
    if ent["kind"] in {"card", "relic", "power"}:
        partners = creative.synergy_for_entity(
            conn, color=color, text=ent["text"], kind=ent["kind"], limit=5
        )
        partners = [p for p in partners if not (p.kind == ent["kind"] and p.entity_id == ent["id"])]
        if partners:
            lines.append("Uses & synergies (strategy/speculation):")
            for item in partners:
                summary = item.text.splitlines()[0] if item.text else item.name
                lines.append(f"- {item.name}: {_truncate(summary, 140)} [{item.citation}]")
                citations.append(f"{item.kind}:{item.entity_id} -> {item.source_path}")

    return {"kind": "exact", "answer": "\n".join(lines), "citations": citations}


def _detail_facts_line(kind: str, facts: dict[str, Any]) -> str:
    parts: list[str] = []
    if kind == "card":
        character = COLOR_LABELS.get(facts.get("color", ""), facts.get("character"))
        for value in (character, facts.get("type"), facts.get("rarity")):
            if value:
                parts.append(str(value).title() if str(value).isupper() else str(value))
        if facts.get("cost") is not None:
            parts.append(f"cost {facts['cost']}")
        for key, label in (("damage", "damage"), ("block", "block"), ("magic_number", "magic")):
            if facts.get(key) is not None:
                parts.append(f"{label} {facts[key]}")
        flags = [label for key, label in CARD_FLAG_LABELS.items() if facts.get(key)]
        parts.extend(flags)
        if facts.get("tags"):
            parts.append(f"tags: {facts['tags']}")
    elif kind == "relic":
        if facts.get("tier"):
            parts.append(f"{str(facts['tier']).title()} relic")
    elif kind == "potion":
        for value in (facts.get("rarity"), facts.get("size")):
            if value:
                parts.append(str(value).title())
    elif kind == "monster":
        if facts.get("act_or_area"):
            parts.append(f"area: {facts['act_or_area']}")
        if facts.get("damage") is not None:
            parts.append(f"damage {facts['damage']}")
    return "Facts: " + ", ".join(parts) if parts else ""


def _truncate(text: str, limit: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)].rstrip() + "..."


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def retrieve(conn: sqlite3.Connection, question: str, *, limit: int = 8) -> list[dict[str, Any]]:
    rows = _retrieve_fts(conn, question, limit=limit)
    if rows:
        return rows
    return _retrieve_like(conn, question, limit=limit)


def strategy_context(conn: sqlite3.Connection, question: str, *, limit: int = 12) -> list[dict[str, Any]]:
    q = question.lower()
    color = _requested_color(q)
    if color in INFINITE_SEEDS and _mentions(q, {"infinite", "loop", "combo"}):
        seeds = INFINITE_SEEDS[color]
        return named_context(conn, seeds, kinds=("card", "relic"), limit=max(limit, len(seeds)))
    if color == "RED" and "block" in q:
        rows = block_strategy_context(conn, limit=max(limit, 12))
        if rows:
            return rows
    if "best" in q and "card" in q:
        if color:
            rows = class_card_context(conn, color, limit=max(limit, 14))
            if rows:
                return rows
        return named_context(conn, BROAD_BEST_SEEDS, kinds=("card",), limit=max(limit, len(BROAD_BEST_SEEDS)))
    if color and _mentions(q, {"deck", "build", "strategy", "come", "idea", "ideas", "archetype"}):
        terms = _terms(q)
        rows = class_term_context(conn, color, terms, limit=max(limit, 16))
        if rows:
            return rows
        return class_card_context(conn, color, limit=max(limit, 16))
    return []


def named_context(
    conn: sqlite3.Connection,
    names: list[str],
    *,
    kinds: tuple[str, ...] | None = None,
    limit: int,
) -> list[dict[str, Any]]:
    if not names:
        return []
    placeholders = ", ".join("?" for _ in names)
    kind_filter = ""
    kind_params: list[str] = []
    if kinds:
        kind_placeholders = ", ".join("?" for _ in kinds)
        kind_filter = f" AND e.kind IN ({kind_placeholders})"
        kind_params = list(kinds)
    order = " ".join(f"WHEN ? THEN {i}" for i, _name in enumerate(names))
    params = [*names, *names, *kind_params, *names, limit]
    rows = conn.execute(
        f"""
        SELECT ch.id AS chunk_id, ch.entity_kind, ch.entity_id, ch.title, ch.text
        FROM chunks ch
        JOIN entities e ON e.kind = ch.entity_kind AND e.id = ch.entity_id
        WHERE (e.name IN ({placeholders}) OR e.id IN ({placeholders}))
          {kind_filter}
        ORDER BY CASE COALESCE(NULLIF(e.name, ''), e.id) {order} ELSE 999 END,
                 CASE ch.entity_kind WHEN 'card' THEN 0 WHEN 'relic' THEN 1 ELSE 2 END,
                 e.name
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [_chunk_dict(row) for row in rows]


def class_card_context(conn: sqlite3.Connection, color: str, *, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT ch.id AS chunk_id, ch.entity_kind, ch.entity_id, ch.title, ch.text
        FROM chunks ch
        JOIN entities e ON e.kind = ch.entity_kind AND e.id = ch.entity_id
        JOIN facts color ON color.entity_kind = e.kind
            AND color.entity_id = e.id
            AND color.key = 'color'
        LEFT JOIN facts rarity ON rarity.entity_kind = e.kind
            AND rarity.entity_id = e.id
            AND rarity.key = 'rarity'
        WHERE e.kind = 'card'
          AND color.value_text = ?
          AND ch.text NOT LIKE '%package=deprecated%'
        ORDER BY CASE rarity.value_text
                   WHEN 'RARE' THEN 0
                   WHEN 'UNCOMMON' THEN 1
                   WHEN 'COMMON' THEN 2
                   ELSE 3
                 END,
                 e.name
        LIMIT ?
        """,
        (color, limit),
    ).fetchall()
    return [_chunk_dict(row) for row in rows]


def class_term_context(conn: sqlite3.Connection, color: str, terms: list[str], *, limit: int) -> list[dict[str, Any]]:
    useful_terms = [term for term in terms if term not in CLASS_COLORS and term not in {"deck", "build", "strategy", "come", "idea", "ideas"}]
    if not useful_terms:
        return []
    clauses = " OR ".join("ch.text LIKE ?" for _ in useful_terms)
    params = [color, *(f"%{term}%" for term in useful_terms), limit]
    rows = conn.execute(
        f"""
        SELECT ch.id AS chunk_id, ch.entity_kind, ch.entity_id, ch.title, ch.text
        FROM chunks ch
        JOIN entities e ON e.kind = ch.entity_kind AND e.id = ch.entity_id
        JOIN facts color ON color.entity_kind = e.kind
            AND color.entity_id = e.id
            AND color.key = 'color'
        WHERE e.kind = 'card'
          AND color.value_text = ?
          AND ch.text NOT LIKE '%package=deprecated%'
          AND ({clauses})
        ORDER BY e.name
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [_chunk_dict(row) for row in rows]


def block_strategy_context(conn: sqlite3.Connection, *, limit: int = 12) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT c.id AS chunk_id, c.entity_kind, c.entity_id, c.title, c.text, e.data_json
        FROM chunks c
        JOIN entities e ON e.kind = c.entity_kind AND e.id = c.entity_id
        LEFT JOIN facts color ON color.entity_kind = e.kind
            AND color.entity_id = e.id
            AND color.key = 'color'
        WHERE e.kind = 'card'
          AND (color.value_text = 'RED' OR c.text LIKE '%Ironclad%')
          AND (c.text LIKE '%block%' OR c.text LIKE '%Block%' OR c.text LIKE '%Barricade%'
               OR c.text LIKE '%Entrench%' OR c.text LIKE '%Body Slam%')
        ORDER BY
          CASE WHEN c.text LIKE '%Barricade%' THEN 0
               WHEN c.text LIKE '%Entrench%' THEN 1
               WHEN c.text LIKE '%Body Slam%' THEN 2
               ELSE 3 END,
          e.name
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [_chunk_dict(row) for row in rows]


def vector_search(
    conn: sqlite3.Connection,
    query_vector: list[float],
    *,
    provider: str,
    model: str,
    limit: int = 8,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT c.id AS chunk_id, c.entity_kind, c.entity_id, c.title, c.text, emb.vector_json
        FROM embeddings emb
        JOIN chunks c ON c.id = emb.chunk_id
        WHERE emb.provider = ? AND emb.model = ?
        """,
        (provider, model),
    ).fetchall()
    scored = []
    for row in rows:
        try:
            vector = json.loads(row["vector_json"])
        except json.JSONDecodeError:
            continue
        score = cosine_similarity(query_vector, vector)
        item = _chunk_dict(row)
        item["score"] = score
        scored.append(item)
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:limit]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


def _retrieve_fts(conn: sqlite3.Connection, question: str, *, limit: int) -> list[dict[str, Any]]:
    query = _fts_query(question)
    if not query:
        return []
    try:
        rows = conn.execute(
            """
            SELECT c.id AS chunk_id, c.entity_kind, c.entity_id, c.title, c.text,
                   bm25(chunks_fts) AS score
            FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.chunk_id
            WHERE chunks_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [_chunk_dict(row) for row in rows]


def _retrieve_like(conn: sqlite3.Connection, question: str, *, limit: int) -> list[dict[str, Any]]:
    terms = _terms(question)
    if not terms:
        rows = conn.execute(
            "SELECT id AS chunk_id, entity_kind, entity_id, title, text FROM chunks LIMIT ?",
            (limit,),
        ).fetchall()
        return [_chunk_dict(row) for row in rows]
    clauses = " OR ".join("text LIKE ?" for _ in terms)
    params = [f"%{term}%" for term in terms]
    rows = conn.execute(
        f"""
        SELECT id AS chunk_id, entity_kind, entity_id, title, text
        FROM chunks
        WHERE {clauses}
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    return [_chunk_dict(row) for row in rows]


def _fts_query(question: str) -> str:
    terms = _terms(question)
    return " OR ".join(f'"{term}"' for term in terms[:12])


def _terms(question: str) -> list[str]:
    stop = {
        "the", "what", "which", "with", "about", "that", "this", "from", "into",
        "card", "cards", "relic", "relics", "monster", "monsters", "game",
        "want", "make", "deck", "considering", "itself", "anything", "related",
    }
    terms = []
    for term in re.findall(r"[A-Za-z][A-Za-z0-9_'-]{2,}", question.lower()):
        if term not in stop and term not in terms:
            terms.append(term)
    return terms


def _requested_color(question: str) -> str | None:
    for term, color in CLASS_COLORS.items():
        if term in question:
            return color
    return None


def _requested_rarity(question: str) -> str | None:
    for term, rarity in RARITY_TERMS.items():
        if term in question:
            return rarity
    return None


def _requested_character_ids(question: str) -> list[str]:
    return [entity_id for term, entity_id in CLASS_ENTITY_IDS.items() if term in question]


def _mentions(question: str, words: set[str]) -> bool:
    return any(word in question for word in words)


def _chunk_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "chunk_id": row["chunk_id"],
        "entity_kind": row["entity_kind"],
        "entity_id": row["entity_id"],
        "title": row["title"],
        "text": row["text"],
        "citation": f"{row['entity_kind']}:{row['entity_id']}",
    }
