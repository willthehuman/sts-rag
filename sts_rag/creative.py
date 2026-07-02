"""Creative deck-idea and combo generation over JAR-derived facts.

This layer turns detected colors/mechanics into *named* deck archetypes and mechanic
combos so that even ``--backend none`` produces creative, structured suggestions. Every
suggested piece is validated against the database first, so citations always point at a
real extracted entity. The archetypes are curated designer knowledge, consistent with the
existing hardcoded seed lists in :mod:`sts_rag.retrieval`; the game facts stay authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import sqlite3
from typing import Any

from .game_tools import (
    MECHANIC_SCORE_TERMS,
    SYNERGY_COMPLEMENTS,
    ToolItem,
    find_by_mechanic,
)


COLOR_LABELS = {
    "RED": "Ironclad",
    "GREEN": "Silent",
    "BLUE": "Defect",
    "PURPLE": "Watcher",
    "COLORLESS": "Colorless",
    "": "Any character",
}

# Human labels for mechanic keys used when naming combos.
MECHANIC_LABELS = {
    "poison": "Poison scaling",
    "shiv": "Shiv spam",
    "orb": "Orbs",
    "orb_slot": "Orb slots",
    "focus": "Focus",
    "stance": "Stance dancing",
    "draw": "Card draw",
    "energy": "Energy",
    "zero_cost": "Zero-cost spam",
    "shuffle": "Shuffle control",
    "exhaust": "Exhaust payoffs",
    "vulnerable": "Vulnerable",
    "block": "Block scaling",
    "card_spam": "Card spam",
    "cross_color": "Off-color splash",
    "random_card": "Card generation",
    "copy": "Copy effects",
    "transform_remove": "Deck thinning",
}


@dataclass(frozen=True)
class Archetype:
    color: str            # RED/GREEN/BLUE/PURPLE/COLORLESS, or "" for any character
    key: str
    name: str
    seeds: tuple[str, ...]
    triggers: frozenset[str]  # mechanic keys that make this archetype relevant
    rationale: str


@dataclass(frozen=True)
class CreativeIdea:
    name: str
    rationale: str
    pieces: tuple[ToolItem, ...] = field(default_factory=tuple)


# Curated archetypes. Seed names use in-game display names (localization NAME), which are
# what the extractor stores as entity.name; unknown names are silently dropped at validation.
ARCHETYPES: tuple[Archetype, ...] = (
    # --- Ironclad (RED) ---
    Archetype(
        "RED", "ironclad_infinite", "Dropkick Vulnerable loop",
        ("Dropkick", "Bash", "Thunderclap", "Uppercut", "Pommel Strike", "Battle Trance",
         "Shrug It Off", "Corruption", "Sundial", "Unceasing Top"),
        frozenset({"vulnerable", "card_spam", "draw", "energy"}),
        "Dropkick draws a card and refunds energy while the enemy is Vulnerable, so a reliable "
        "Vulnerable source (Bash/Thunderclap) plus a thin deck lets Dropkick recur indefinitely. "
        "Win condition: chip the target down between loops or convert to a scaling payoff.",
    ),
    Archetype(
        "RED", "ironclad_exhaust", "Corruption exhaust engine",
        ("Corruption", "Feel No Pain", "Dark Embrace", "Second Wind", "Fiend Fire",
         "Sentinel", "Dead Branch", "Charon's Ashes"),
        frozenset({"exhaust", "block", "draw"}),
        "Corruption makes every Skill cost 0 and Exhaust; Feel No Pain and Dark Embrace turn that "
        "churn into Block and draw. Win condition: Fiend Fire or Dead Branch value converts the "
        "exhausting hand into burst or scaling.",
    ),
    Archetype(
        "RED", "ironclad_block", "Barricade Body Slam",
        ("Barricade", "Body Slam", "Entrench", "Impervious", "Bronze Scales", "Flame Barrier"),
        frozenset({"block"}),
        "Barricade stops Block from expiring; Entrench doubles it and Body Slam spends the whole "
        "pile as damage. Win condition: stack Block over several turns, then one Body Slam.",
    ),
    Archetype(
        "RED", "ironclad_strength", "Strength scaling",
        ("Demon Form", "Limit Break", "Heavy Blade", "Inflame", "Spot Weakness", "Reaper"),
        frozenset({"card_spam"}),
        "Demon Form and Inflame ramp Strength; Limit Break doubles it and Heavy Blade multiplies it "
        "into a single hit. Win condition: outscale the fight, healing back with Reaper.",
    ),
    # --- Silent (GREEN) ---
    Archetype(
        "GREEN", "silent_poison", "Catalyst poison stack",
        ("Catalyst", "Corpse Explosion", "Noxious Fumes", "Deadly Poison", "Bouncing Flask",
         "Crippling Cloud", "Bane", "Snecko Skull"),
        frozenset({"poison"}),
        "Stack Poison with Noxious Fumes and repeatable applicators, then Catalyst multiplies the "
        "current stack; Corpse Explosion spreads a lethal stack across the room. Win condition: let "
        "Poison tick the enemy out while you defend.",
    ),
    Archetype(
        "GREEN", "silent_shiv", "Infinite Blades shiv spam",
        ("Blade Dance", "Cloak and Dagger", "Infinite Blades", "Accuracy", "After Image",
         "Storm of Steel", "Finisher", "A Thousand Cuts"),
        frozenset({"shiv", "card_spam"}),
        "Generate Shivs with Blade Dance / Infinite Blades; Accuracy and A Thousand Cuts make each "
        "Shiv hit far harder while After Image adds Block per card. Win condition: a single big "
        "Finisher or the per-Shiv damage snowballs.",
    ),
    Archetype(
        "GREEN", "silent_draw", "Tactician discard cycle",
        ("Tactician", "Reflex", "Acrobatics", "Tools of the Trade", "Concentrate", "Eviscerate"),
        frozenset({"draw", "energy"}),
        "Discard synergies (Tactician/Reflex refund energy or draw when discarded) fuel a deep-draw "
        "turn that discounts Eviscerate to near-free. Win condition: chain a huge cheap-attack turn.",
    ),
    # --- Defect (BLUE) ---
    Archetype(
        "BLUE", "defect_frost", "Frost & Focus wall",
        ("Defragment", "Glacier", "Coolheaded", "Blizzard", "Loop", "Biased Cognition",
         "Chill", "Charge Battery"),
        frozenset({"orb", "orb_slot", "focus", "block"}),
        "Defragment and Biased Cognition pump Focus so each Frost orb blocks more; Loop re-triggers "
        "your passive every turn. Win condition: an unbreakable Frost wall while Blizzard closes it out.",
    ),
    Archetype(
        "BLUE", "defect_lightning", "Electrodynamics lightning",
        ("Electrodynamics", "Ball Lightning", "Thunder Strike", "Storm", "Static Discharge",
         "Defragment", "Loop"),
        frozenset({"orb", "focus"}),
        "Electrodynamics makes Lightning hit all enemies; with Focus and many orb slots the passive "
        "damage clears rooms. Win condition: Thunder Strike burst plus per-turn Lightning ticks.",
    ),
    Archetype(
        "BLUE", "defect_zero", "Echo Form zero-cost",
        ("Echo Form", "All for One", "Hologram", "Machine Learning", "Seek", "Turbo",
         "Meteor Strike"),
        frozenset({"zero_cost", "card_spam", "copy", "draw"}),
        "Echo Form copies the first card each turn; All for One returns 0-cost cards from the discard "
        "for an explosive replay turn. Win condition: chain a doubled, near-free hand into lethal.",
    ),
    # --- Watcher (PURPLE) ---
    Archetype(
        "PURPLE", "watcher_divinity", "Mantra into Divinity",
        ("Devotion", "Prostrate", "Worship", "Pray", "Mental Fortress", "Fasting", "Deceive Reality"),
        frozenset({"stance", "block"}),
        "Build Mantra with Devotion/Worship to enter Divinity (3x damage, +3 energy). Win condition: "
        "line up a big-damage turn the moment Divinity triggers.",
    ),
    Archetype(
        "PURPLE", "watcher_rushdown", "Rushdown stance loop",
        ("Rushdown", "Eruption", "Fear No Evil", "Vigilance", "Tantrum", "Empty Fist",
         "Flurry of Blows", "Simmering Fury"),
        frozenset({"stance", "draw", "card_spam", "energy"}),
        "Rushdown draws on every entry into Wrath; cheap stance-swap cards (Tantrum, Flurry of Blows) "
        "keep switching to draw and re-play. Win condition: a Wrath-doubled infinite that ends the "
        "fight in one turn - mind the incoming damage Wrath doubles too.",
    ),
    Archetype(
        "PURPLE", "watcher_scaling", "Pressure Points retain",
        ("Talk to the Hand", "Pressure Points", "Wallop", "Sanctity", "Wave of the Hand",
         "Establishment", "Nirvana"),
        frozenset({"block", "draw"}),
        "Pressure Points and Talk to the Hand pile on damage/Block that pays out every time the card "
        "is played; Establishment discounts retained cards. Win condition: multi-target scaling that "
        "snowballs across the fight.",
    ),
    # --- Cross-character / colorless ---
    Archetype(
        "", "cross_color", "Off-color splash",
        ("Prismatic Shard", "Chrysalis", "Metamorphosis", "Discovery", "Bandage Up",
         "Master of Strategy", "Dark Shackles"),
        frozenset({"cross_color", "random_card"}),
        "Prismatic Shard makes card rewards show every color; events like Chrysalis/Metamorphosis add "
        "permanent off-class cards, while Discovery-style effects generate temporary ones. Note: "
        "separate permanent additions from one-shot generated cards when planning a splash.",
    ),
)


def build_creative_ideas(
    conn: sqlite3.Connection,
    question: str,
    tool_context: dict[str, Any] | None,
    *,
    limit: int = 3,
) -> list[CreativeIdea]:
    """Select relevant archetypes + mechanic combos, validated against the database."""
    plan = (tool_context or {}).get("plan") or {}
    color = _plan_color(plan)
    mechanics = list(plan.get("mechanics") or [])

    ideas: list[CreativeIdea] = []
    for archetype in _select_archetypes(color, mechanics, limit=limit):
        idea = _archetype_idea(conn, archetype)
        if idea:
            ideas.append(idea)

    for combo in _mechanic_combos(conn, color, mechanics, limit=2):
        ideas.append(combo)

    return _dedupe_ideas(ideas)


def synergy_for_entity(
    conn: sqlite3.Connection,
    *,
    color: str | None,
    text: str,
    kind: str,
    limit: int = 5,
) -> list[ToolItem]:
    """Suggest partner cards/relics for a single entity by matching its own text to mechanics."""
    present = _mechanics_in_text(text)
    complements: list[str] = []
    for mechanic in present:
        complements.extend(SYNERGY_COMPLEMENTS.get(mechanic, []))
    wanted = _ordered_unique([*present, *complements])
    items: list[ToolItem] = []
    seen: set[tuple[str, str]] = set()
    for mechanic in wanted[:5]:
        for item in find_by_mechanic(conn, mechanic, kinds=["card", "relic", "power"], color=color, limit=limit):
            key = (item.kind, item.entity_id)
            if key not in seen:
                seen.add(key)
                items.append(item)
    return items[:limit]


def creative_ideas_to_prompt(ideas: list[CreativeIdea]) -> str:
    if not ideas:
        return "Creative candidate archetypes: none"
    parts = ["Creative candidate archetypes (validated JAR pieces; explain the loop and cite):"]
    for idea in ideas:
        parts.append(f"- {idea.name}: {idea.rationale}")
        pieces = ", ".join(f"[{p.citation}] {p.name}" for p in idea.pieces)
        if pieces:
            parts.append(f"  pieces: {pieces}")
    return "\n".join(parts)


def creative_ideas_to_local(ideas: list[CreativeIdea]) -> str:
    if not ideas:
        return ""
    lines = ["Creative deck ideas from JAR facts:"]
    for idea in ideas:
        lines.append(f"- {idea.name} - {idea.rationale}")
        for piece in idea.pieces[:6]:
            summary = piece.text.splitlines()[0] if piece.text else piece.name
            lines.append(f"  - {piece.name}: {_compact(summary, 140)} [{piece.citation}]")
    return "\n".join(lines)


# --- internals -------------------------------------------------------------------------


def _select_archetypes(color: str | None, mechanics: list[str], *, limit: int) -> list[Archetype]:
    mech_set = set(mechanics)
    scored: list[tuple[int, int, Archetype]] = []
    for idx, archetype in enumerate(ARCHETYPES):
        if not _color_matches(color, archetype.color):
            continue
        overlap = len(archetype.triggers & mech_set)
        # If a specific color was asked, still surface that color's flagship ideas even with
        # no mechanic overlap; drop off-color/any archetypes that don't match any mechanic.
        if overlap == 0:
            if color and archetype.color == color:
                pass
            else:
                continue
        # Prefer more overlap, then the curated ordering.
        scored.append((-overlap, idx, archetype))
    scored.sort(key=lambda t: (t[0], t[1]))
    return [archetype for _o, _i, archetype in scored[:limit]]


def _archetype_idea(conn: sqlite3.Connection, archetype: Archetype) -> CreativeIdea | None:
    resolved = _resolve_many(conn, list(archetype.seeds))
    pieces: list[ToolItem] = []
    seen: set[tuple[str, str]] = set()
    for seed in archetype.seeds:
        item = resolved.get(_norm(seed))
        if item and (item.kind, item.entity_id) not in seen:
            seen.add((item.kind, item.entity_id))
            pieces.append(item)
    if len(pieces) < 2:
        return None
    return CreativeIdea(name=archetype.name, rationale=archetype.rationale, pieces=tuple(pieces[:8]))


def _mechanic_combos(
    conn: sqlite3.Connection,
    color: str | None,
    mechanics: list[str],
    *,
    limit: int,
) -> list[CreativeIdea]:
    combos: list[CreativeIdea] = []
    seen_pairs: set[frozenset[str]] = set()
    for mechanic in mechanics:
        complements = [c for c in SYNERGY_COMPLEMENTS.get(mechanic, []) if c in mechanics or c in {"draw", "energy"}]
        for complement in complements:
            pair = frozenset({mechanic, complement})
            if mechanic == complement or pair in seen_pairs:
                continue
            primary = find_by_mechanic(conn, mechanic, kinds=["card", "relic", "power"], color=color, limit=1)
            partner = find_by_mechanic(conn, complement, kinds=["card", "relic", "power"], color=color, limit=1)
            if not primary or not partner or primary[0].entity_id == partner[0].entity_id:
                continue
            seen_pairs.add(pair)
            name = f"{MECHANIC_LABELS.get(mechanic, mechanic)} + {MECHANIC_LABELS.get(complement, complement)}"
            rationale = (
                f"Pair {mechanic.replace('_', ' ')} payoffs with {complement.replace('_', ' ')} enablers "
                f"so the engine keeps running; the two cited pieces are a concrete starting point."
            )
            combos.append(CreativeIdea(name=name, rationale=rationale, pieces=(primary[0], partner[0])))
            if len(combos) >= limit:
                return combos
    return combos


def _mechanics_in_text(text: str) -> list[str]:
    lowered = text.lower()
    present: list[str] = []
    for mechanic, terms in MECHANIC_SCORE_TERMS.items():
        if any(term in lowered for term in terms):
            present.append(mechanic)
    return present


def _resolve_many(conn: sqlite3.Connection, names: list[str]) -> dict[str, ToolItem]:
    if not names:
        return {}
    placeholders = ", ".join("?" for _ in names)
    rows = conn.execute(
        f"""
        SELECT e.kind, e.id, e.name, e.source_path, ch.text
        FROM entities e
        JOIN chunks ch ON ch.entity_kind = e.kind AND ch.entity_id = e.id
        WHERE e.name IN ({placeholders}) OR e.id IN ({placeholders})
        """,
        [*names, *names],
    ).fetchall()
    by_norm: dict[str, ToolItem] = {}
    for row in rows:
        item = ToolItem(
            kind=row["kind"],
            entity_id=row["id"],
            name=row["name"],
            source_path=row["source_path"],
            text=row["text"],
        )
        by_norm.setdefault(_norm(row["name"]), item)
        by_norm.setdefault(_norm(row["id"]), item)
    return by_norm


def _plan_color(plan: dict[str, Any]) -> str | None:
    label = plan.get("color")
    if not label:
        return None
    for color, name in COLOR_LABELS.items():
        if name == label:
            return color or None
    return None


def _color_matches(requested: str | None, archetype_color: str) -> bool:
    if archetype_color in {"", "COLORLESS"}:
        return True
    if not requested:
        return True
    return requested == archetype_color


def _dedupe_ideas(ideas: list[CreativeIdea]) -> list[CreativeIdea]:
    seen: set[str] = set()
    out: list[CreativeIdea] = []
    for idea in ideas:
        if idea.name not in seen:
            seen.add(idea.name)
            out.append(idea)
    return out


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _compact(text: str, limit: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)].rstrip() + "..."
