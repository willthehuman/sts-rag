# sts-rag

Local Slay the Spire knowledge CLI built from the installed `desktop-1.0.jar`.

```powershell
C:\Users\wcperrier\TSpire\.venv\Scripts\python.exe -m sts_rag ingest --jar "C:\Users\wcperrier\TSpire\desktop-1.0.jar" --db data/sts.sqlite --rebuild
C:\Users\wcperrier\TSpire\.venv\Scripts\python.exe -m sts_rag ask "what is the highest cost card?"
C:\Users\wcperrier\TSpire\.venv\Scripts\python.exe -m sts_rag chat --backend auto
```

By default, answers use only JAR-derived facts: localization JSON plus class bytecode metadata.
Exact factual questions are answered from SQLite first. Strategy questions run reusable game tools
against the database, such as mechanic search, entity lookup, and synergy expansion, then OpenRouter
or Ollama can synthesize an answer over that structured context.

Examples:

```powershell
C:\Users\wcperrier\TSpire\.venv\Scripts\python.exe -m sts_rag ask --backend none "what relics should i look for for a poison deck?"
C:\Users\wcperrier\TSpire\.venv\Scripts\python.exe -m sts_rag ask --backend ollama "what are ways to have an infinite deck with the watcher?"
C:\Users\wcperrier\TSpire\.venv\Scripts\python.exe -m sts_rag chat --backend openrouter --web --web-domain reddit.com --web-domain slay-the-spire.fandom.com
```

`--web` is optional. With OpenRouter it enables the OpenRouter web plugin. With Ollama, `sts-rag`
performs a small app-side web search/fetch and passes community snippets into the local model.
JAR facts remain authoritative for card/relic/monster mechanics; web context is only for community
strategy inspiration.

## Model Configuration

Ollama:

```powershell
$env:OLLAMA_MODEL="llama3.1"
```

OpenRouter:

```powershell
$env:OPENROUTER_API_KEY="..."
$env:OPENROUTER_MODEL="openai/gpt-5.2"
```

Use `--backend none` for deterministic local answers without model calls.

## Answer Pipeline

1. Exact SQL handles factual comparisons and counts, such as highest cost cards or starting decks.
2. Generic game tools broaden strategy prompts into mechanics like Poison, Stance, Orbs, draw,
   energy, copy effects, card spam, and cross-color card access.
3. Optional web context can add community strategy sources, clearly separated from JAR-derived facts.
4. The model synthesizes strategy/speculation from the cited components, without claiming novelty
   unless an indexed community/run corpus supports it.
