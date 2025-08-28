# app/services/memory.py
import sqlite3
import json
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

# Optional: If you have an embedding function in your llm service, import it.
# from app.services import llm

class MemoryManager:
    def __init__(self, db_path: str = "memories.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("""
            CREATE TABLE IF NOT EXISTS memory (
                id INTEGER PRIMARY KEY,
                user_id TEXT,
                text TEXT,
                metadata TEXT,
                created_at TEXT,
                summarized INTEGER DEFAULT 0
            )
            """)
            conn.commit()

    def add_memory(self, user_id: str, text: str, metadata: Optional[Dict[str, Any]] = None):
        metadata_json = json.dumps(metadata or {})
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO memory (user_id, text, metadata, created_at) VALUES (?,?,?,?)",
                (user_id, text, metadata_json, now)
            )
            conn.commit()

    def get_recent(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, text, metadata, created_at FROM memory WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit)
            )
            rows = cur.fetchall()
        return [
            {"id": r[0], "text": r[1], "metadata": json.loads(r[2] or "{}"), "created_at": r[3]}
            for r in rows
        ]

    def search_simple(self, user_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Lightweight fallback retrieval: simple substring search in memory text.
        If you have embeddings, swap this for a vector search.
        """
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            q = f"%{query}%"
            cur.execute(
                "SELECT id, text, metadata, created_at FROM memory WHERE user_id = ? AND text LIKE ? ORDER BY created_at DESC LIMIT ?",
                (user_id, q, limit)
            )
            rows = cur.fetchall()
        return [
            {"id": r[0], "text": r[1], "metadata": json.loads(r[2] or "{}"), "created_at": r[3]}
            for r in rows
        ]

    def clear_user(self, user_id: str):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM memory WHERE user_id = ?", (user_id,))
            conn.commit()

    def prune_older_than(self, days: int = 90):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM memory WHERE created_at < ?", (cutoff,))
            conn.commit()

    def summarize_old(self, user_id: str, summarizer_fn, older_than_days: int = 30):
        """
        Summarize older memories into a compact summary note using your LLM summarizer function.
        summarizer_fn(list_of_texts) -> str
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, text FROM memory WHERE user_id = ? AND created_at < ?",
                (user_id, cutoff)
            )
            rows = cur.fetchall()
            if not rows:
                return None
            texts = [r[1] for r in rows]
            summary = summarizer_fn(texts)

            # mark old rows as summarized (or delete and add one summary row)
            cur.execute("DELETE FROM memory WHERE user_id = ? AND created_at < ?", (user_id, cutoff))
            now = datetime.now(timezone.utc).isoformat()
            cur.execute(
                "INSERT INTO memory (user_id, text, metadata, created_at, summarized) VALUES (?,?,?,?,1)",
                (user_id, f"SUMMARIZED: {summary}", json.dumps({"auto_summary": True}), now)
            )
            conn.commit()
            return summary
