"""Extract Slay the Spire facts from a game JAR."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from pathlib import Path
from typing import Any
import zipfile

from . import classparse


DEFAULT_JAR = Path.home() / "TSpire" / "desktop-1.0.jar"

CARD_CLASS_PREFIX = "com/megacrit/cardcrawl/cards/"
RELIC_CLASS_PREFIX = "com/megacrit/cardcrawl/relics/"
MONSTER_CLASS_PREFIX = "com/megacrit/cardcrawl/monsters/"
POTION_CLASS_PREFIX = "com/megacrit/cardcrawl/potions/"
CHARACTER_CLASS_PREFIX = "com/megacrit/cardcrawl/characters/"

CARD_FIELD_NAMES = (
    "baseDamage",
    "baseBlock",
    "baseMagicNumber",
    "magicNumber",
    "exhaust",
    "isEthereal",
    "isInnate",
    "retain",
    "selfRetain",
    "returnToHand",
    "shuffleBackIntoDrawPile",
)

BOOL_FIELDS = {
    "exhaust",
    "isEthereal",
    "isInnate",
    "retain",
    "selfRetain",
    "returnToHand",
    "shuffleBackIntoDrawPile",
}

CARD_COLOR_LABELS = {
    "RED": "Ironclad",
    "GREEN": "Silent",
    "BLUE": "Defect",
    "PURPLE": "Watcher",
    "COLORLESS": "Colorless",
    "CURSE": "Curse",
}

CARD_DIR_COLOR = {
    "red": "RED",
    "green": "GREEN",
    "blue": "BLUE",
    "purple": "PURPLE",
    "colorless": "COLORLESS",
    "curses": "CURSE",
    "status": "STATUS",
}

SKIP_RELIC_CLASSES = {"AbstractRelic", "CircletButton", "RunicDome"}
SKIP_POTION_CLASSES = {"AbstractPotion", "PotionHelper", "PotionSlot"}
MONSTER_CLASS_ALIASES = {
    "BanditPointy": "BanditChild",
}
CHARACTER_NAMES = {
    "Ironclad": "Ironclad",
    "TheSilent": "Silent",
    "Defect": "Defect",
    "Watcher": "Watcher",
}


@dataclass
class ExtractedEntity:
    kind: str
    entity_id: str
    name: str
    source_path: str
    data: dict[str, Any] = field(default_factory=dict)
    facts: dict[str, Any] = field(default_factory=dict)

    @property
    def chunk_title(self) -> str:
        return f"{self.kind}: {self.name}"

    @property
    def chunk_text(self) -> str:
        parts = [f"{self.kind.title()} {self.name}", f"id: {self.entity_id}"]
        if self.source_path:
            parts.append(f"source: {self.source_path}")
        if self.facts:
            facts = ", ".join(f"{k}={v}" for k, v in sorted(self.facts.items()) if v not in (None, "", []))
            if facts:
                parts.append(f"facts: {facts}")
        for key in ("description", "rendered_description", "moves", "flavor", "dialog"):
            value = self.data.get(key)
            if value:
                parts.append(f"{key}: {value}")
        if self.data.get("starting_deck_summary"):
            parts.append(f"starting_deck: {self.data['starting_deck_summary']}")
        return "\n".join(parts)


@dataclass
class Catalog:
    entities: list[ExtractedEntity]
    stats: dict[str, int]


def extract_catalog(jar_path: Path | str, *, lang: str = "eng") -> Catalog:
    jar = Path(jar_path)
    if not jar.is_file():
        raise FileNotFoundError(f"desktop-1.0.jar not found: {jar}")
    entities: list[ExtractedEntity] = []
    with zipfile.ZipFile(jar) as zf:
        loc = _load_localizations(zf, lang)
        names = zf.namelist()
        entities.extend(_extract_characters(zf, names))
        entities.extend(_extract_cards(zf, names, loc.get("cards", {})))
        entities.extend(_extract_relics(zf, names, loc.get("relics", {})))
        entities.extend(_extract_monsters(zf, names, loc.get("monsters", {})))
        entities.extend(_extract_potions(zf, names, loc.get("potions", {})))
        entities.extend(_extract_simple("power", "powers", loc.get("powers", {})))
        entities.extend(_extract_simple("event", "events", loc.get("events", {})))
        entities.extend(_extract_keywords(loc.get("keywords", {})))
        entities.extend(_extract_achievements(loc.get("achievements", {})))
    stats: dict[str, int] = {}
    for entity in entities:
        stats[entity.kind] = stats.get(entity.kind, 0) + 1
    return Catalog(entities=entities, stats=stats)


def _load_localizations(zf: zipfile.ZipFile, lang: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for name in ("cards", "relics", "monsters", "powers", "potions", "events", "keywords", "achievements"):
        path = f"localization/{lang}/{name}.json"
        try:
            out[name] = json.loads(zf.read(path).decode("utf-8"))
        except (KeyError, json.JSONDecodeError, UnicodeDecodeError):
            out[name] = {}
    return out


def _extract_characters(zf: zipfile.ZipFile, names: list[str]) -> list[ExtractedEntity]:
    out: list[ExtractedEntity] = []
    for stem, display_name in CHARACTER_NAMES.items():
        resource = f"{CHARACTER_CLASS_PREFIX}{stem}.class"
        if resource not in names:
            continue
        parsed = _safe_parse(zf, resource)
        if parsed is None:
            continue
        player_class = _one(classparse.enum_field_args(parsed.pool, "$PlayerClass")) or stem
        starting_deck = _starting_deck_ids(parsed)
        data = {
            "starting_deck": starting_deck,
            "starting_deck_summary": _deck_summary(starting_deck),
        }
        facts = {
            "class": parsed.this_class,
            "player_class": player_class,
            "starting_deck_size": len(starting_deck),
        }
        out.append(ExtractedEntity(
            kind="character",
            entity_id=display_name.lower(),
            name=display_name,
            source_path=resource,
            data=data,
            facts=facts,
        ))
    return out


def _extract_cards(zf: zipfile.ZipFile, names: list[str], loc: dict[str, dict]) -> list[ExtractedEntity]:
    resources = [
        n for n in names
        if n.startswith(CARD_CLASS_PREFIX)
        and n.endswith(".class")
        and "$" not in n
        and n[len(CARD_CLASS_PREFIX):].count("/") == 1
    ]
    out: list[ExtractedEntity] = []
    for resource in resources:
        stem = Path(resource).stem
        card_dir = resource.split("/")[-2]
        parsed = _safe_parse(zf, resource)
        if parsed is None:
            continue
        entity_id = _find_localization_id(parsed, loc, stem) or stem
        entry = loc.get(entity_id, {})
        facts: dict[str, Any] = {"class": parsed.this_class, "package": card_dir}
        color = _one(classparse.enum_field_args(parsed.pool, "$CardColor")) or CARD_DIR_COLOR.get(card_dir, "")
        if color:
            facts["color"] = color
            facts["character"] = CARD_COLOR_LABELS.get(color, color.title())
        _put_one(facts, "type", classparse.enum_field_args(parsed.pool, "$CardType"))
        _put_one(facts, "rarity", classparse.enum_field_args(parsed.pool, "$CardRarity"))
        _put_one(facts, "target", classparse.enum_field_args(parsed.pool, "$CardTarget"))
        tags = sorted(classparse.enum_field_args(parsed.pool, "$CardTags"))
        if tags:
            facts["tags"] = ", ".join(tags)
        cost = classparse.first_constructor_int_arg(parsed, "AbstractCard")
        if cost is not None:
            facts["cost"] = cost
        assignments = classparse.assigned_literals(parsed, CARD_FIELD_NAMES)
        field_map = {
            "baseDamage": "damage",
            "baseBlock": "block",
            "baseMagicNumber": "magic_number",
            "magicNumber": "magic_number_current",
        }
        for key, value in assignments.items():
            if key in BOOL_FIELDS:
                facts[_camel_to_snake(key)] = bool(value)
            else:
                facts[field_map.get(key, _camel_to_snake(key))] = value
        facts.update(classparse.upgrade_literals(parsed))

        raw_description = _clean_text(entry.get("DESCRIPTION", ""), replace_stat_tokens=False)
        rendered_description = _render_card_description(raw_description, facts)
        data = {
            "description": raw_description,
            "rendered_description": rendered_description,
            "extended_description": _clean_text(" ".join(entry.get("EXTENDED_DESCRIPTION", [])), replace_stat_tokens=False),
            "raw_localization": entry,
        }
        out.append(ExtractedEntity(
            kind="card",
            entity_id=entity_id,
            name=entry.get("NAME") or _humanize(stem),
            source_path=resource,
            data=data,
            facts=facts,
        ))
    return out


def _extract_relics(zf: zipfile.ZipFile, names: list[str], loc: dict[str, dict]) -> list[ExtractedEntity]:
    resources = [
        n for n in names
        if n.startswith(RELIC_CLASS_PREFIX) and n.endswith(".class") and "$" not in n
    ]
    out: list[ExtractedEntity] = []
    for resource in resources:
        stem = Path(resource).stem
        if stem in SKIP_RELIC_CLASSES or stem.startswith("Abstract"):
            continue
        parsed = _safe_parse(zf, resource)
        if parsed is None:
            continue
        entity_id = _find_localization_id(parsed, loc, stem) or stem
        entry = loc.get(entity_id, {})
        facts: dict[str, Any] = {"class": parsed.this_class}
        _put_one(facts, "tier", classparse.enum_field_args(parsed.pool, "$RelicTier"))
        _put_one(facts, "landing_sound", classparse.enum_field_args(parsed.pool, "$LandingSound"))
        data = {
            "description": _clean_text(" ".join(entry.get("DESCRIPTIONS", []))),
            "flavor": _clean_text(entry.get("FLAVOR", "")),
            "raw_localization": entry,
        }
        out.append(ExtractedEntity(
            kind="relic",
            entity_id=entity_id,
            name=entry.get("NAME") or _humanize(stem),
            source_path=resource,
            data=data,
            facts=facts,
        ))
    return out


def _extract_monsters(zf: zipfile.ZipFile, names: list[str], loc: dict[str, dict]) -> list[ExtractedEntity]:
    resources = [
        n for n in names
        if n.startswith(MONSTER_CLASS_PREFIX)
        and n.endswith(".class")
        and "$" not in n
        and n[len(MONSTER_CLASS_PREFIX):].count("/") >= 1
    ]
    out: list[ExtractedEntity] = []
    seen_loc_ids: set[str] = set()
    for resource in resources:
        stem = Path(resource).stem
        parsed = _safe_parse(zf, resource)
        if parsed is None:
            continue
        entity_id = MONSTER_CLASS_ALIASES.get(stem) or _find_localization_id(parsed, loc, stem, allow_contains=True) or stem
        entry = loc.get(entity_id, {})
        if entry:
            seen_loc_ids.add(entity_id)
        area = resource.split("/")[-2]
        facts: dict[str, Any] = {"class": parsed.this_class, "act_or_area": area}
        powers = _referenced_power_classes(parsed)
        if powers:
            facts["referenced_powers"] = powers
        assignments = classparse.assigned_literals(parsed, ("damage", "moveDmg", "blockAmount"))
        for key, value in assignments.items():
            facts[_camel_to_snake(key)] = value
        moves = [_clean_text(m) for m in entry.get("MOVES", []) if _clean_text(m)]
        dialog = [_clean_text(m) for m in entry.get("DIALOG", []) if _clean_text(m)]
        data = {"moves": "; ".join(moves), "dialog": "; ".join(dialog), "raw_localization": entry}
        out.append(ExtractedEntity(
            kind="monster",
            entity_id=entity_id,
            name=entry.get("NAME") or _humanize(stem),
            source_path=resource,
            data=data,
            facts=facts,
        ))
    for entity_id, entry in loc.items():
        if entity_id in seen_loc_ids or not isinstance(entry, dict):
            continue
        moves = [_clean_text(m) for m in entry.get("MOVES", []) if _clean_text(m)]
        dialog = [_clean_text(m) for m in entry.get("DIALOG", []) if _clean_text(m)]
        out.append(ExtractedEntity(
            kind="monster",
            entity_id=entity_id,
            name=entry.get("NAME") or _humanize(entity_id),
            source_path="localization/eng/monsters.json",
            data={"moves": "; ".join(moves), "dialog": "; ".join(dialog), "raw_localization": entry},
            facts={},
        ))
    return out


def _extract_potions(zf: zipfile.ZipFile, names: list[str], loc: dict[str, dict]) -> list[ExtractedEntity]:
    resources = [
        n for n in names
        if n.startswith(POTION_CLASS_PREFIX) and n.endswith(".class") and "$" not in n
    ]
    out: list[ExtractedEntity] = []
    for resource in resources:
        stem = Path(resource).stem
        if stem in SKIP_POTION_CLASSES or stem.startswith("Abstract"):
            continue
        parsed = _safe_parse(zf, resource)
        if parsed is None:
            continue
        entity_id = _find_localization_id(parsed, loc, stem) or stem
        entry = loc.get(entity_id, {})
        facts: dict[str, Any] = {"class": parsed.this_class}
        _put_one(facts, "rarity", classparse.enum_field_args(parsed.pool, "$PotionRarity"))
        _put_one(facts, "color", classparse.enum_field_args(parsed.pool, "$PotionColor"))
        _put_one(facts, "size", classparse.enum_field_args(parsed.pool, "$PotionSize"))
        data = {
            "description": _clean_text(" ".join(entry.get("DESCRIPTIONS", []))),
            "raw_localization": entry,
        }
        out.append(ExtractedEntity(
            kind="potion",
            entity_id=entity_id,
            name=entry.get("NAME") or _humanize(stem),
            source_path=resource,
            data=data,
            facts=facts,
        ))
    return out


def _extract_simple(kind: str, loc_name: str, loc: dict[str, dict]) -> list[ExtractedEntity]:
    out: list[ExtractedEntity] = []
    for entity_id, entry in loc.items():
        if not isinstance(entry, dict):
            continue
        name = entry.get("NAME") or entry.get("NAMES", [entity_id])[0] if entry.get("NAMES") else entity_id
        descriptions = entry.get("DESCRIPTIONS") or entry.get("DESCRIPTION") or entry.get("TEXT") or []
        if isinstance(descriptions, str):
            desc = descriptions
        else:
            desc = " ".join(str(part) for part in descriptions)
        data = {"description": _clean_text(desc), "raw_localization": entry}
        out.append(ExtractedEntity(
            kind=kind,
            entity_id=str(entity_id),
            name=str(name),
            source_path=f"localization/eng/{loc_name}.json",
            data=data,
            facts={},
        ))
    return out


def _safe_parse(zf: zipfile.ZipFile, resource: str) -> classparse.ParsedClass | None:
    try:
        return classparse.parse_class(zf.read(resource))
    except Exception:
        return None


def _find_localization_id(
    parsed: classparse.ParsedClass,
    loc: dict[str, dict],
    stem: str,
    *,
    allow_contains: bool = False,
) -> str | None:
    if not loc:
        return None
    loc_keys = set(loc)
    strings = classparse.string_constants(parsed.pool) + classparse.utf8_strings(parsed.pool)
    seen: set[str] = set()
    candidates: list[str] = []
    for value in strings:
        if value in loc_keys and value not in seen:
            seen.add(value)
            candidates.append(value)
    if not candidates:
        return None

    stem_norm = _norm(stem)

    def score(candidate: str) -> tuple[int, int]:
        cand_norm = _norm(candidate)
        if cand_norm == stem_norm:
            return 0, len(candidate)
        if stem_norm.startswith(cand_norm) or cand_norm.startswith(stem_norm):
            return 1, len(candidate)
        if allow_contains and (cand_norm in stem_norm or stem_norm in cand_norm):
            return 2, len(candidate)
        display = str(loc.get(candidate, {}).get("NAME", ""))
        if _norm(display) == stem_norm:
            return 2, len(candidate)
        return 3, len(candidate)

    best = sorted(candidates, key=score)[0]
    return best if score(best)[0] < 3 else None


def _extract_keywords(loc: dict[str, dict]) -> list[ExtractedEntity]:
    dictionary = loc.get("Game Dictionary", loc)
    if not isinstance(dictionary, dict):
        return []
    out: list[ExtractedEntity] = []
    for entity_id, entry in dictionary.items():
        if not isinstance(entry, dict):
            continue
        names = entry.get("NAMES") or [entity_id]
        name = str(names[0]) if names else str(entity_id)
        data = {
            "description": _clean_text(entry.get("DESCRIPTION", "")),
            "aliases": ", ".join(str(n) for n in names),
            "raw_localization": entry,
        }
        out.append(ExtractedEntity(
            kind="keyword",
            entity_id=str(entity_id),
            name=name,
            source_path="localization/eng/keywords.json",
            data=data,
            facts={},
        ))
    return out


def _extract_achievements(loc: dict[str, dict]) -> list[ExtractedEntity]:
    grid = loc.get("AchievementGrid", {})
    if not isinstance(grid, dict):
        return []
    names = grid.get("NAMES", [])
    texts = grid.get("TEXT", [])
    out: list[ExtractedEntity] = []
    for name, text in zip(names, texts):
        if not name:
            continue
        out.append(ExtractedEntity(
            kind="achievement",
            entity_id=_norm(str(name)),
            name=str(name),
            source_path="localization/eng/achievements.json",
            data={"description": _clean_text(text), "raw_localization": {"NAME": name, "TEXT": text}},
            facts={},
        ))
    return out


def _render_card_description(description: str, facts: dict[str, Any]) -> str:
    out = description
    replacements = {
        "!D!": facts.get("damage"),
        "!B!": facts.get("block"),
        "!M!": facts.get("magic_number"),
    }
    for token, value in replacements.items():
        if value is not None:
            out = out.replace(token, str(value))
    return _clean_text(out)


def _referenced_power_classes(parsed: classparse.ParsedClass) -> list[str]:
    refs = classparse.method_refs(parsed.pool) + classparse.field_refs(parsed.pool)
    powers = {
        owner.split("/")[-1]
        for owner, _name, _desc in refs
        if owner and owner.startswith("com/megacrit/cardcrawl/powers/")
    }
    return sorted(powers)


def _starting_deck_ids(parsed: classparse.ParsedClass) -> list[str]:
    for method in parsed.methods:
        if method.name != "getStartingDeck" or method.code is None:
            continue
        deck: list[str] = []
        pending: str | None = None
        for event in classparse.bytecode_events(parsed, method.code):
            if event.kind == "string" and isinstance(event.value, str):
                pending = event.value
                continue
            if event.kind == "method" and isinstance(event.value, tuple):
                owner, name, _desc = event.value
                if owner == "java/util/ArrayList" and name == "add" and pending:
                    deck.append(pending)
                    pending = None
        return deck
    return []


def _deck_summary(card_ids: list[str]) -> str:
    counts: dict[str, int] = {}
    for card_id in card_ids:
        counts[card_id] = counts.get(card_id, 0) + 1
    return ", ".join(f"{count}x {card_id}" for card_id, count in counts.items())


def _put_one(facts: dict[str, Any], key: str, values: set[str]) -> None:
    values = {v for v in values if v and v != "$VALUES"}
    if values:
        facts[key] = sorted(values)[0]


def _one(values: set[str]) -> str:
    values = {v for v in values if v and v != "$VALUES"}
    return sorted(values)[0] if values else ""


def _clean_text(value: Any, *, replace_stat_tokens: bool = True) -> str:
    text = str(value or "")
    text = text.replace(" NL ", " ").replace(" NL", " ").replace("NL ", " ")
    if replace_stat_tokens:
        text = text.replace("!D!", "damage").replace("!B!", "block").replace("!M!", "magic")
    text = re.sub(r"[#@~]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _humanize(stem: str) -> str:
    text = stem.replace("_", " ")
    text = re.sub(r"(?<!^)([A-Z])", r" \1", text)
    return re.sub(r"\s+", " ", text).strip()


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _camel_to_snake(value: str) -> str:
    value = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return value.lower()
