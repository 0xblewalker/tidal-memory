from dataclasses import dataclass, field
from typing import Optional


BACKGROUND_TYPES = frozenset({"window_impression", "rollup_week", "rollup_month"})


@dataclass(frozen=True)
class Memory:
    id: int
    occurred_at: str
    recorded_at: str
    event_type: str
    layer: str
    summary: str
    details: str = ""
    importance: int = 5
    tags: str = ""
    conversation_id: Optional[str] = None
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    archived: bool = False
    merged_into: Optional[int] = None


@dataclass(frozen=True)
class RetrievalHit:
    memory: Memory
    score: float
    source: str = "keyword"
    provenance: str = "direct"


@dataclass
class RecallPolicy:
    """The three independent recall valves."""

    trigger: str = "balanced"  # explicit | balanced | active
    association: str = "direct_plus_one_hop"  # direct | direct_plus_one_hop
    max_items: int = 2
    max_chars: int = 900
    repeat_cooldown_turns: int = 3
    candidate_pool: int = 8
    excluded_event_types: set[str] = field(default_factory=lambda: set(BACKGROUND_TYPES))

    def __post_init__(self):
        if self.trigger not in {"explicit", "balanced", "active"}:
            raise ValueError("trigger must be explicit, balanced, or active")
        if self.association not in {"direct", "direct_plus_one_hop"}:
            raise ValueError("association must be direct or direct_plus_one_hop")
        if self.max_items < 1 or self.max_chars < 40:
            raise ValueError("recall budget is too small")

