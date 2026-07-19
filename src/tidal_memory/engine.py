from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Optional

from .models import RecallPolicy, RetrievalHit
from .policy import should_recall
from .retrieval import KeywordRetriever, Retriever
from .store import MemoryStore, utcnow


ImpressionWriter = Callable[[list[dict]], str]
FactExtractor = Callable[[list[dict]], list[dict]]
ThreadExtractor = Callable[[list[dict]], list[dict]]
RelevanceVerifier = Callable[[str, list[RetrievalHit]], list[RetrievalHit]]


def quiet_impression(messages: list[dict]) -> str:
    """Privacy-safe offline fallback with broad topics and no quotations."""
    text = " ".join(
        str(item.get("content", "")).lower()
        for item in messages if item.get("role") in {"user", "assistant"}
    )
    if not text.strip():
        return "A quiet conversation passed without a durable impression."
    topic_words = {
        "technology": ("code", "bug", "server", "model", "缓存", "代码", "系统", "模型"),
        "daily life": ("food", "sleep", "work", "猫", "吃", "睡", "上班", "日常"),
        "travel": ("trip", "travel", "hotel", "旅行", "酒店", "车站"),
        "relationships": ("love", "miss", "together", "喜欢", "想你", "关系", "亲亲"),
        "entertainment": ("game", "movie", "book", "游戏", "电影", "小说"),
    }
    topics = [name for name, words in topic_words.items() if any(word in text for word in words)]
    broad = " and ".join(topics[:3]) if topics else "ordinary things"
    return f"They spent time talking about {broad}; the overall memory is warm but indistinct."


def quiet_rollup(impressions: list[str], label: str) -> str:
    return (
        f"A {label} of recurring conversations and ordinary shared moments; "
        "the overall memory is warm but indistinct."
    )


class TidalMemory:
    def __init__(
        self,
        path: str = "tidal-memory.db",
        *,
        policy: Optional[RecallPolicy] = None,
        retriever: Optional[Retriever] = None,
        impression_writer: Optional[ImpressionWriter] = None,
        fact_extractor: Optional[FactExtractor] = None,
        thread_extractor: Optional[ThreadExtractor] = None,
        relevance_verifier: Optional[RelevanceVerifier] = None,
    ):
        self.store = MemoryStore(path)
        self.policy = policy or RecallPolicy()
        self.retriever = retriever or KeywordRetriever(self.store)
        self.impression_writer = impression_writer or quiet_impression
        self.fact_extractor = fact_extractor
        self.thread_extractor = thread_extractor
        self.relevance_verifier = relevance_verifier
        self.turn = 0
        self._last_injected: dict[int, int] = {}

    def close(self):
        self.store.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def remember(self, summary: str, **kwargs) -> int:
        return self.store.add(summary, **kwargs)

    def forget(self, memory_id: int):
        self.store.forget(memory_id)

    def close_window(
        self,
        conversation_id: str,
        messages: list[dict],
        *,
        title: str = "Untitled",
        occurred_at: Optional[str] = None,
    ) -> int:
        if self.fact_extractor:
            for fact in self.fact_extractor(messages):
                if not isinstance(fact, dict) or not fact.get("summary"):
                    continue
                allowed = {
                    key: fact[key] for key in (
                        "details", "occurred_at", "event_type", "layer", "importance",
                        "tags", "valid_from", "valid_to"
                    ) if key in fact
                }
                self.remember(fact["summary"], **allowed)
        impression = self.impression_writer(messages)
        ongoing_threads = self.thread_extractor(messages) if self.thread_extractor else []
        return self.store.upsert_window_impression(
            conversation_id, impression, title=title, occurred_at=occurred_at,
            ongoing_threads=ongoing_threads,
        )

    def opening_context(self, conversation_id: str = "") -> str:
        core = self.store.stable_context()
        impressions = self.store.impression_ladder(conversation_id)
        sections = []
        if core:
            sections.append("[Stable memory]\n" + core)
        if impressions:
            sections.append("[Impressions]\n" + impressions)
        return "\n\n".join(sections)

    def recall(self, message: str, *, force: bool = False) -> str:
        self.turn += 1
        if not force and not should_recall(message, self.policy):
            return ""
        candidates = self.retriever.retrieve(
            message, limit=self.policy.candidate_pool,
            exclude_event_types=self.policy.excluded_event_types,
        )
        if self.policy.association == "direct_plus_one_hop":
            seen = {hit.memory.id for hit in candidates}
            spread = []
            for hit in candidates:
                for neighbor in self.store.neighbors(hit.memory.id):
                    if neighbor.id in seen or neighbor.event_type in self.policy.excluded_event_types:
                        continue
                    seen.add(neighbor.id)
                    spread.append(RetrievalHit(
                        neighbor, hit.score * 0.7, hit.source, "spread"
                    ))
            candidates = sorted(
                [*candidates, *spread], key=lambda hit: hit.score, reverse=True
            )[:self.policy.candidate_pool]
        candidates = [
            hit for hit in candidates
            if self.turn - self._last_injected.get(hit.memory.id, -10_000)
            > self.policy.repeat_cooldown_turns
        ]
        if self.relevance_verifier:
            candidates = self.relevance_verifier(message, candidates)
        selected = candidates[:self.policy.max_items]
        lines, used = [], 0
        for hit in selected:
            line = f"- [{hit.memory.occurred_at[:10]}] {hit.memory.summary}"
            remaining = self.policy.max_chars - used - (1 if lines else 0)
            if remaining <= 3:
                break
            if len(line) > remaining:
                line = line[:remaining - 1].rstrip() + "…"
            lines.append(line)
            used += len(line)
            self._last_injected[hit.memory.id] = self.turn
        return "\n".join(lines)

    @staticmethod
    def _week_key(timestamp: str) -> str:
        date = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        iso = date.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"

    def rollup(
        self,
        *,
        now: Optional[datetime] = None,
        writer: Optional[Callable[[list[str], str], str]] = None,
        min_group_size: int = 2,
    ) -> dict:
        now = now or datetime.now(timezone.utc)
        writer = writer or quiet_rollup
        week_cutoff = (now - timedelta(days=7)).isoformat()
        month_cutoff = (now - timedelta(days=35)).isoformat()
        stats = {"weekly": 0, "monthly": 0}

        windows = self.store.rows(
            "archived=0 AND event_type='window_impression' AND occurred_at<?",
            (week_cutoff,),
        )
        groups = defaultdict(list)
        for item in windows:
            groups[self._week_key(item.occurred_at)].append(item)
        for key, items in groups.items():
            if len(items) < min_group_size:
                continue
            summary = writer([item.summary for item in items], "week")
            new_id = self.store.add(
                summary, occurred_at=max(item.occurred_at for item in items),
                event_type="rollup_week", layer="episodic", importance=5,
                tags="rollup,impression-week:" + key,
            )
            self.store.archive_many([item.id for item in items], new_id)
            stats["weekly"] += 1

        weeks = self.store.rows(
            "archived=0 AND event_type='rollup_week' AND occurred_at<?",
            (month_cutoff,),
        )
        months = defaultdict(list)
        for item in weeks:
            months[item.occurred_at[:7]].append(item)
        for key, items in months.items():
            if len(items) < min_group_size:
                continue
            summary = writer([item.summary for item in items], "month")
            new_id = self.store.add(
                summary, occurred_at=max(item.occurred_at for item in items),
                event_type="rollup_month", layer="episodic", importance=5,
                tags="rollup,impression-month:" + key,
            )
            self.store.archive_many([item.id for item in items], new_id)
            stats["monthly"] += 1
        return stats
