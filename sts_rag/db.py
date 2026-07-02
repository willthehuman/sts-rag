"""SQLite persistence for extracted game facts and RAG chunks."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from .extract import Catalog, ExtractedEntity


def connect(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    if path.parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def initialize(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS entities (
            kind TEXT NOT NULL,
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            source_path TEXT NOT NULL,
            data_json TEXT NOT NULL,
            PRIMARY KEY (kind, id)
        );

        CREATE TABLE IF NOT EXISTS facts (
            entity_kind TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value_text TEXT NOT NULL,
            value_num REAL,
            source TEXT NOT NULL,
            PRIMARY KEY (entity_kind, entity_id, key, value_text)
        );

        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_kind TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            title TEXT NOT NULL,
            text TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS embeddings (
            chunk_id INTEGER NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            vector_json TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (chunk_id, provider, model)
        );
        """
    )
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(title, text, chunk_id UNINDEXED)"
        )
    except sqlite3.OperationalError:
        pass
    conn.commit()


def reset(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS embeddings;
        DROP TABLE IF EXISTS chunks;
        DROP TABLE IF EXISTS facts;
        DROP TABLE IF EXISTS entities;
        DROP TABLE IF EXISTS chunks_fts;
        """
    )
    conn.commit()
    initialize(conn)


def ingest_catalog(conn: sqlite3.Connection, catalog: Catalog) -> None:
    initialize(conn)
    for entity in catalog.entities:
        insert_entity(conn, entity)
    conn.commit()


def insert_entity(conn: sqlite3.Connection, entity: ExtractedEntity) -> None:
    data = dict(entity.data)
    data["facts"] = entity.facts
    conn.execute(
        """
        INSERT OR REPLACE INTO entities(kind, id, name, source_path, data_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (entity.kind, entity.entity_id, entity.name, entity.source_path, json.dumps(data, sort_keys=True)),
    )
    conn.execute("DELETE FROM facts WHERE entity_kind = ? AND entity_id = ?", (entity.kind, entity.entity_id))
    for key, value in entity.facts.items():
        for item in _fact_items(value):
            value_text = _value_text(item)
            value_num = _value_num(item)
            conn.execute(
                """
                INSERT OR REPLACE INTO facts(entity_kind, entity_id, key, value_text, value_num, source)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (entity.kind, entity.entity_id, key, value_text, value_num, entity.source_path),
            )
    conn.execute("DELETE FROM chunks WHERE entity_kind = ? AND entity_id = ?", (entity.kind, entity.entity_id))
    cur = conn.execute(
        """
        INSERT INTO chunks(entity_kind, entity_id, title, text)
        VALUES (?, ?, ?, ?)
        """,
        (entity.kind, entity.entity_id, entity.chunk_title, entity.chunk_text),
    )
    chunk_id = cur.lastrowid
    try:
        conn.execute(
            "INSERT INTO chunks_fts(title, text, chunk_id) VALUES (?, ?, ?)",
            (entity.chunk_title, entity.chunk_text, chunk_id),
        )
    except sqlite3.OperationalError:
        pass


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT kind, COUNT(*) AS n FROM entities GROUP BY kind ORDER BY kind").fetchall()
    return {row["kind"]: int(row["n"]) for row in rows}


def get_entity(conn: sqlite3.Connection, kind: str, entity_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM entities WHERE kind = ? AND id = ?",
        (kind, entity_id),
    ).fetchone()


def iter_chunks(conn: sqlite3.Connection) -> Iterable[sqlite3.Row]:
    yield from conn.execute("SELECT id, title, text FROM chunks ORDER BY id")


def store_embedding(
    conn: sqlite3.Connection,
    chunk_id: int,
    provider: str,
    model: str,
    vector: list[float],
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO embeddings(chunk_id, provider, model, vector_json)
        VALUES (?, ?, ?, ?)
        """,
        (chunk_id, provider, model, json.dumps(vector)),
    )


def _fact_items(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _value_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _value_num(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return None

