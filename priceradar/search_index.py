from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SearchResult:
    link: str
    title: str
    body: str


class SearchIndex:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS products_fts
                USING fts5(link UNINDEXED, title, body, tokenize='unicode61')
                """
            )

    def upsert(self, link: str, title: str, body: str) -> None:
        """Index product for search. link=product URL, title=product name, body=store+category+brand."""
        with self._connect() as conn:
            conn.execute("DELETE FROM products_fts WHERE link = ?", (link,))
            conn.execute(
                "INSERT INTO products_fts(link, title, body) VALUES (?, ?, ?)",
                (link, title, body),
            )

    def search(self, query: str, *, limit: int = 20) -> list[SearchResult]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT link, title, body
                FROM products_fts
                WHERE products_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()

        return [SearchResult(link=row[0], title=row[1], body=row[2]) for row in rows]
