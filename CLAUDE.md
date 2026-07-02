# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`sts-rag` is a near-stdlib CLI that extracts Slay the Spire facts from the installed game JAR
(`desktop-1.0.jar`) into SQLite, then answers questions over those facts. JAR-derived facts are
treated as the only authoritative source; LLMs and web search only synthesize/inspire strategy on
top of that structured context. The one runtime dependency is `rich` (chat UI only); the core
pipeline and `ask` remain stdlib-only.

## Commands

Use the project venv interpreter (there is no console-script install step in normal use):

```powershell
# Build/refresh the database from the JAR (run this first)
C:\Users\wcperrier\TSpire\.venv\Scripts\python.exe -m sts_rag ingest --jar "C:\Users\wcperrier\TSpire\desktop-1.0.jar" --db data/sts.sqlite --rebuild

# One-shot question / interactive chat
python -m sts_rag ask "what is the highest cost card?"
python -m sts_rag ask --backend none "what relics help a poison deck?"
python -m sts_rag chat --backend auto

# Embed chunks for optional vector search
python -m sts_rag embed --backend ollama
```

- `--backend`: `auto` (OpenRouter if `OPENROUTER_API_KEY` set, else a running Ollama, else local fallback),
  `none` (deterministic, no model call), `ollama`, or `openrouter`.
- `--web` adds optional community web context for strategy questions (OpenRouter web plugin, or app-side
  fetch for Ollama). JAR facts stay authoritative over web context.

### Tests

Uses stdlib `unittest`. Many tests **skip unless the real JAR exists** at `DEFAULT_JAR`
(`~/TSpire/desktop-1.0.jar`) — for those, a green run with everything skipped means nothing was
exercised. `test_render.py` and `test_creative.py` are **JAR-independent** (they fabricate a tiny DB
via `db.insert_entity` with hand-built `ExtractedEntity` rows), so they always run. `test_queries.py`
also acts as a behavior spec for the exact-fact / creative / entity-detail handlers.

```powershell
python -m unittest discover -s tests -v          # all
python -m unittest tests.test_queries -v         # one module
python -m unittest tests.test_queries.QueryTests.test_highest_cost_card  # one test
```

There is no configured linter/formatter, but `.ruff_cache`/`.mypy_cache` are gitignored, so ruff and mypy
are expected if you add tooling.

## Architecture

The answer flow is a deterministic-first cascade in `answer.py::answer_question`:

1. **Exact SQL** (`retrieval.exact_answer`) — pattern-matches the question against hand-written handlers
   for factual queries (highest/lowest cost, card counts, starting decks, shiv matchups, minimalist, etc.).
   It also detects **entity lookup intent** ("details on / tell me about / describe X") and dispatches to
   `retrieval.entity_detail_answer` (via `find_entity_by_name`). If it returns, the model is never called.
2. **Game tools** (`game_tools.build_game_tool_context`) — for strategy questions, detects mechanics
   (poison, stance, orbs, draw, energy, exhaust, cross-color…), expands them into complementary synergies,
   and runs reusable SQL over the fact DB to assemble broad structured context with citations.
3. **Creative engine** (`creative.build_creative_ideas`) — selects curated per-character archetypes
   (`creative.ARCHETYPES`) by detected color+mechanics and builds named combos, **validating every seed
   against the DB** so citations are real. Feeds both the LLM prompt and the offline fallback, so
   `--backend none` still produces named deck ideas. Gated on strategy/matchup intent in `_creative_ideas`.
4. **Retrieval context** (`retrieval.strategy_context` → falls back to `retrieve`: FTS5 `bm25`, then LIKE).
5. **Provider synthesis** (`providers.select_provider`) — Ollama/OpenRouter synthesize over the above,
   with a creative-mode addendum in `SYSTEM_PROMPT`. If no provider is available or a call fails under
   `--backend auto`, `answer.py::_local_answer` / `game_tools.local_tool_answer` +
   `creative.creative_ideas_to_local` produce a deterministic fallback from the same context.

### Chat rendering (`render.py`, chat only)

`answer_question` always returns a **plain string** using stable conventions (headers ending `:`,
`- ` bullets, `[kind:id]` citations, trailing `(model: …)`). `render.py` (rich) styles those
conventions for the `chat` command — `ask` prints the raw string so it stays scriptable. Glyphs
(`•`, `›`) fall back to ASCII when the output encoding can't encode them (`_supports_unicode`);
`--no-color` / `NO_COLOR` / non-tty disable color. **Do not embed markup in answer strings** — the
renderer recognizes structure, so adding markup would leak into `ask` output.

Guardrails live in `SYSTEM_PROMPT` (`answer.py`): cite JAR facts with exact bracketed ids
(`[card:Bash]`), label strategy as speculation, prefer JAR facts over web context, don't claim novelty.

### Extraction (JAR → facts)

- `extract.py` opens the JAR zip and combines two sources per entity: `localization/<lang>/*.json`
  (names, descriptions) and parsed `.class` bytecode. It produces `ExtractedEntity` objects with a
  `kind` (card, relic, monster, potion, character, power, event, keyword, achievement), structured
  `facts`, and a searchable `chunk_text`.
- `classparse.py` is a **minimal `.class` reader, not a decompiler**. It recovers only what's needed:
  constant-pool strings, enum references (`$CardColor`, `$CardRarity`…), literal constructor args (card
  cost), simple field assignments (`baseDamage = 8`), and specific bytecode walks (e.g. `getStartingDeck`).
  It's brittle by nature — `extract._safe_parse` swallows parse errors and skips the class.
- Localization ids are matched to class stems heuristically in `_find_localization_id` (normalized
  name scoring); this is the usual culprit when an entity's facts and text don't line up.

### Storage (`db.py`)

SQLite schema: `entities` (json blob + name/source), `facts` (one row per key/value, with `value_num`
for numeric comparisons), `chunks` (retrieval text), `chunks_fts` (FTS5, degrades gracefully if the
build lacks FTS5), `embeddings`. `ingest_catalog` is idempotent (INSERT OR REPLACE); `reset` drops and
rebuilds (used by `--rebuild`). The `facts` table is what the exact-SQL handlers query.

### Conventions worth knowing

- Card `character`/`color` come from the `$CardColor` enum, falling back to the source directory
  (`CARD_DIR_COLOR`). Deprecated cards live under a `deprecated` package and are filtered out of most
  query results (`package.value_text != 'deprecated'`, `source_path NOT LIKE '%/deprecated/%'`).
- Question parsing is keyword-based throughout (`_requested_color`, `_requested_rarity`,
  `_detect_mechanics`, `MECHANIC_TRIGGERS`). Extending question coverage usually means adding to these
  keyword/pattern maps rather than adding new control flow.
- `retrieval.py`, `game_tools.py`, and `creative.py` each keep their own copies of
  `CLASS_COLORS`/`COLOR_LABELS` and small term helpers (`_norm`, `_ordered_unique`) — keep them in
  sync when you change one.
- Curated designer knowledge lives in hardcoded name lists: `retrieval.INFINITE_SEEDS` /
  `*_SEEDS` (retrieval context) and `creative.ARCHETYPES` (named deck ideas). Seed names must match
  in-game display names (localization `NAME`); unknown names are silently dropped at DB validation.
  Keep these ASCII (the `ask` path prints them through the console's native encoding).

## Data / environment

- `data/*.sqlite` is gitignored; regenerate with `ingest`.
- Model config via env: `OLLAMA_MODEL`/`OLLAMA_HOST`, `OPENROUTER_API_KEY`/`OPENROUTER_MODEL`/
  `OPENROUTER_EMBEDDING_MODEL`.
