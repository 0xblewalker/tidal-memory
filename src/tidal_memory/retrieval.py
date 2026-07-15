import re
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Iterable

from .models import RetrievalHit
from .store import MemoryStore, utcnow


class Retriever(ABC):
    @abstractmethod
    def retrieve(
        self, query: str, *, limit: int = 8,
        exclude_event_types: Iterable[str] = (),
    ) -> list[RetrievalHit]:
        raise NotImplementedError


class KeywordRetriever(Retriever):
    """SQLite FTS5/BM25 retriever. No model download and no vector database."""

    def __init__(self, store: MemoryStore):
        self.store = store

    @staticmethod
    def _fts_query(query: str) -> str:
        tokens = re.findall(r"[\w\u3400-\u9fff]+", query.lower())
        return " OR ".join(f'"{token}"' for token in tokens if len(token) > 1)

    @staticmethod
    def _lexical_tokens(text: str) -> set[str]:
        english = {word.lower() for word in re.findall(r"[A-Za-z0-9_]+", text) if len(word) > 1}
        cjk = set()
        for run in re.findall(r"[\u3400-\u9fff]+", text):
            if len(run) == 1:
                cjk.add(run)
            else:
                cjk.update(run[index:index + 2] for index in range(len(run) - 1))
        return english | cjk

    def retrieve(self, query, *, limit=8, exclude_event_types=()):
        expression = self._fts_query(query)
        if not expression:
            return []
        excluded = set(exclude_event_types)
        try:
            rows = self.store._db.execute(
                """SELECT m.*, bm25(memory_fts) AS rank
                   FROM memory_fts JOIN memories m ON m.id=memory_fts.memory_id
                   WHERE memory_fts MATCH ? AND m.archived=0
                   ORDER BY rank LIMIT ?""", (expression, max(limit * 3, limit)),
            ).fetchall()
        except Exception:
            rows = []
        by_id = {}
        for row in rows:
            if row["event_type"] in excluded:
                continue
            # FTS5 ranks better matches with more-negative values.
            score = 1.0 / (1.0 + abs(float(row["rank"])))
            by_id[row["id"]] = RetrievalHit(self.store._memory(row), score, "fts5", "direct")

        # unicode61 does not segment every CJK language well. A bounded token
        # overlap pass keeps the default backend multilingual and model-free.
        query_tokens = self._lexical_tokens(query)
        lexical_rows = self.store._db.execute(
            "SELECT * FROM memories WHERE archived=0 ORDER BY occurred_at DESC LIMIT 5000"
        ).fetchall()
        for row in lexical_rows:
            if row["event_type"] in excluded:
                continue
            memory_tokens = self._lexical_tokens(
                (row["summary"] or "") + " " + (row["details"] or "") + " " + (row["tags"] or "")
            )
            overlap = len(query_tokens & memory_tokens)
            if not overlap:
                continue
            score = overlap / max(len(query_tokens), 1)
            old = by_id.get(row["id"])
            if old is None or score > old.score:
                by_id[row["id"]] = RetrievalHit(self.store._memory(row), score, "lexical", "direct")

        hits = sorted(by_id.values(), key=lambda hit: hit.score, reverse=True)[:limit]
        if hits:
            ids = [hit.memory.id for hit in hits]
            marks = ",".join("?" for _ in ids)
            self.store._db.execute(
                f"UPDATE memories SET access_count=access_count+1,last_accessed=? WHERE id IN ({marks})",
                [utcnow(), *ids],
            )
            self.store._db.commit()
        return hits


class HybridRetriever(Retriever):
    """Reciprocal-rank fusion over any set of retriever adapters."""

    def __init__(self, *retrievers: Retriever):
        if not retrievers:
            raise ValueError("at least one retriever is required")
        self.retrievers = retrievers

    def retrieve(self, query, *, limit=8, exclude_event_types=()):
        fused = defaultdict(float)
        memories = {}
        sources = defaultdict(set)
        for retriever in self.retrievers:
            for rank, hit in enumerate(retriever.retrieve(
                query, limit=limit, exclude_event_types=exclude_event_types
            ), 1):
                fused[hit.memory.id] += 1.0 / (60 + rank)
                memories[hit.memory.id] = hit.memory
                sources[hit.memory.id].add(hit.source)
        ordered = sorted(fused, key=fused.get, reverse=True)[:limit]
        return [
            RetrievalHit(memories[mid], fused[mid], "+".join(sorted(sources[mid])), "direct")
            for mid in ordered
        ]
