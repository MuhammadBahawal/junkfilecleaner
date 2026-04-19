from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(slots=True)
class CleanupTarget:
    key: str
    name: str
    category: str
    location: str
    description: str
    items: list[Path] = field(default_factory=list)
    size_bytes: int = 0
    item_count: int = 0
    special_handler: str | None = None


@dataclass(slots=True)
class LeftoverCandidate:
    path: Path
    root_label: str
    size_bytes: int
    modified_at: datetime
    confidence: int
    reason: str


@dataclass(slots=True)
class PerformanceSnapshot:
    cpu_percent: float
    memory_percent: float
    memory_used: int
    memory_total: int
    disk_percent: float
    disk_free: int
    disk_total: int
    process_count: int
    uptime_seconds: int


@dataclass(slots=True)
class ProcessEntry:
    pid: int
    name: str
    cpu_percent: float
    memory_mb: float
    status: str
    username: str
    started_at: datetime | None = None
    exe_path: str = ""


@dataclass(slots=True)
class ActionResult:
    freed_bytes: int = 0
    deleted_items: int = 0
    failed_items: int = 0
    skipped_items: int = 0
    messages: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DeepCleanResult:
    action_result: ActionResult
    cleanup_target_count: int
    leftover_found_count: int
    leftover_deleted_count: int
    leftover_remaining_review_count: int
