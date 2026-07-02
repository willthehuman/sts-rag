"""Command line interface."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .answer import answer_question
from .db import connect, counts, initialize, ingest_catalog, iter_chunks, reset, store_embedding
from .extract import DEFAULT_JAR, extract_catalog
from .providers import ProviderError, select_provider


DEFAULT_DB = Path("data") / "sts.sqlite"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sts-rag", description="Slay the Spire JAR RAG CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="extract JAR facts into SQLite")
    ingest.add_argument("--jar", type=Path, default=DEFAULT_JAR)
    ingest.add_argument("--db", type=Path, default=DEFAULT_DB)
    ingest.add_argument("--lang", default="eng")
    ingest.add_argument("--rebuild", action="store_true")

    ask = sub.add_parser("ask", help="ask one question")
    ask.add_argument("question")
    ask.add_argument("--db", type=Path, default=DEFAULT_DB)
    ask.add_argument("--backend", choices=("auto", "none", "ollama", "openrouter"), default="auto")
    ask.add_argument("--model", default=None)
    ask.add_argument("--limit", type=int, default=8)
    ask.add_argument("--web", action="store_true", help="add optional community web context for strategy questions")
    ask.add_argument("--web-max-results", type=int, default=3)
    ask.add_argument("--web-domain", action="append", dest="web_domains", default=None)

    chat = sub.add_parser("chat", help="interactive chat")
    chat.add_argument("--db", type=Path, default=DEFAULT_DB)
    chat.add_argument("--backend", choices=("auto", "none", "ollama", "openrouter"), default="auto")
    chat.add_argument("--model", default=None)
    chat.add_argument("--limit", type=int, default=8)
    chat.add_argument("--web", action="store_true", help="add optional community web context for strategy questions")
    chat.add_argument("--web-max-results", type=int, default=3)
    chat.add_argument("--web-domain", action="append", dest="web_domains", default=None)
    chat.add_argument("--no-color", action="store_true", help="disable colored/formatted chat output")

    embed = sub.add_parser("embed", help="embed chunks for vector search")
    embed.add_argument("--db", type=Path, default=DEFAULT_DB)
    embed.add_argument("--backend", choices=("ollama", "openrouter"), default="ollama")
    embed.add_argument("--model", default=None)
    embed.add_argument("--batch-size", type=int, default=32)

    args = parser.parse_args(argv)
    try:
        if args.command == "ingest":
            return _cmd_ingest(args)
        if args.command == "ask":
            return _cmd_ask(args)
        if args.command == "chat":
            return _cmd_chat(args)
        if args.command == "embed":
            return _cmd_embed(args)
    except (FileNotFoundError, ProviderError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    try:
        if args.rebuild:
            reset(conn)
        else:
            initialize(conn)
        catalog = extract_catalog(args.jar, lang=args.lang)
        ingest_catalog(conn, catalog)
        db_counts = counts(conn)
        print(f"ingested {sum(db_counts.values())} entities into {args.db}")
        for kind, count in sorted(db_counts.items()):
            print(f"  {kind}: {count}")
        return 0
    finally:
        conn.close()


def _cmd_ask(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    try:
        initialize(conn)
        print(
            answer_question(
                conn,
                args.question,
                backend=args.backend,
                model=args.model,
                limit=args.limit,
                web=args.web,
                web_max_results=args.web_max_results,
                web_domains=args.web_domains,
            )
        )
        return 0
    finally:
        conn.close()


def _cmd_chat(args: argparse.Namespace) -> int:
    from . import render

    conn = connect(args.db)
    try:
        initialize(conn)
        console = render.build_console(no_color=args.no_color)
        render.render_banner(console, backend=args.backend, web=args.web)
        while True:
            try:
                question = render.render_prompt(console)
            except EOFError:
                console.print()
                break
            if not question:
                continue
            if question.lower() in {"exit", "quit", ":q"}:
                break
            answer = answer_question(
                conn,
                question,
                backend=args.backend,
                model=args.model,
                limit=args.limit,
                web=args.web,
                web_max_results=args.web_max_results,
                web_domains=args.web_domains,
            )
            console.print()
            render.render_answer(console, answer)
            console.print()
        return 0
    finally:
        conn.close()


def _cmd_embed(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    try:
        initialize(conn)
        provider = select_provider(args.backend, model=args.model)
        if provider is None:
            raise ProviderError("Embedding requires --backend ollama or --backend openrouter.")
        chunks = list(iter_chunks(conn))
        total = 0
        for start in range(0, len(chunks), args.batch_size):
            batch = chunks[start:start + args.batch_size]
            vectors = provider.embed([row["text"] for row in batch])
            for row, vector in zip(batch, vectors):
                store_embedding(conn, int(row["id"]), provider.name, provider.model, vector)
                total += 1
            conn.commit()
            print(f"embedded {total}/{len(chunks)} chunks")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
