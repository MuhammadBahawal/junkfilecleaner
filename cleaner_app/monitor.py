from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import psutil

from .models import PerformanceSnapshot, ProcessEntry


def prime_counters() -> None:
    psutil.cpu_percent(interval=None)
    for process in psutil.process_iter():
        try:
            process.cpu_percent(interval=None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def get_performance_snapshot() -> PerformanceSnapshot:
    system_drive = Path(os.environ.get("SystemDrive", "C:") + "\\")
    disk = psutil.disk_usage(str(system_drive))
    memory = psutil.virtual_memory()
    return PerformanceSnapshot(
        cpu_percent=psutil.cpu_percent(interval=None),
        memory_percent=memory.percent,
        memory_used=memory.used,
        memory_total=memory.total,
        disk_percent=disk.percent,
        disk_free=disk.free,
        disk_total=disk.total,
        process_count=len(psutil.pids()),
        uptime_seconds=int(datetime.now().timestamp() - psutil.boot_time()),
    )


def get_processes(search: str = "", limit: int = 250) -> list[ProcessEntry]:
    query = search.strip().lower()
    entries: list[ProcessEntry] = []
    for process in psutil.process_iter(
        ["pid", "name", "username", "memory_info", "status", "create_time", "exe"]
    ):
        try:
            name = process.info.get("name") or "Unknown"
            pid = int(process.info.get("pid", 0))
            if query and query not in name.lower() and query not in str(pid):
                continue

            memory_info = process.info.get("memory_info")
            memory_mb = (memory_info.rss / (1024 * 1024)) if memory_info else 0.0
            started_at = None
            create_time = process.info.get("create_time")
            if create_time:
                started_at = datetime.fromtimestamp(create_time)

            entries.append(
                ProcessEntry(
                    pid=pid,
                    name=name,
                    cpu_percent=process.cpu_percent(interval=None),
                    memory_mb=memory_mb,
                    status=str(process.info.get("status") or "-"),
                    username=str(process.info.get("username") or "-"),
                    started_at=started_at,
                    exe_path=str(process.info.get("exe") or ""),
                )
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    entries.sort(key=lambda item: (item.memory_mb, item.cpu_percent), reverse=True)
    return entries[:limit]


def terminate_process(pid: int) -> tuple[bool, str]:
    try:
        process = psutil.Process(pid)
        name = process.name()
        process.terminate()
        try:
            process.wait(timeout=3)
        except psutil.TimeoutExpired:
            process.kill()
        return True, f"Process ended: {name} ({pid})"
    except psutil.NoSuchProcess:
        return False, f"Process {pid} is no longer running."
    except psutil.AccessDenied:
        return False, f"Access denied while trying to end process {pid}."
