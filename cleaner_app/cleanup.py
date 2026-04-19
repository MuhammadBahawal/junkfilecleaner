from __future__ import annotations

import ctypes
import os
import re
import shutil
import stat
import time
from ctypes import wintypes
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable
import winreg

from .models import ActionResult, CleanupTarget, DeepCleanResult, LeftoverCandidate

RECENT_FILE_GRACE_SECONDS = 10 * 60
LEFTOVER_MIN_AGE_DAYS = 30
LEFTOVER_MIN_SIZE_BYTES = 5 * 1024 * 1024
MAX_LEFTOVER_RESULTS = 120
AUTO_DELETE_LEFTOVER_CONFIDENCE = 80
SYSTEM_SKIP_NAMES = {
    "assembly",
    "connecteddevicesplatform",
    "crashdumps",
    "fontcache",
    "history",
    "identitycrisis",
    "microsoft",
    "microsoft shared",
    "package cache",
    "packages",
    "peerdistrepub",
    "placeholdertilelogofolder",
    "programs",
    "temp",
    "tempstate",
    "virtualstore",
}


class SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("i64Size", ctypes.c_longlong),
        ("i64NumItems", ctypes.c_longlong),
    ]


def scan_cleanup_targets() -> list[CleanupTarget]:
    env = os.environ
    windir = Path(env.get("WINDIR", r"C:\Windows"))
    local_app_data = Path(env.get("LOCALAPPDATA", ""))
    roaming_app_data = Path(env.get("APPDATA", ""))
    temp_dir = Path(env.get("TEMP", ""))
    targets: list[CleanupTarget] = []

    targets.extend(
        filter(
            None,
            [
                _scan_directory_target(
                    "user_temp",
                    "User Temp Files",
                    "Temporary Files",
                    temp_dir,
                    "Safe cleanup of your personal temp folder.",
                ),
                _scan_directory_target(
                    "windows_temp",
                    "Windows Temp",
                    "System Cache",
                    windir / "Temp",
                    "System temp files that commonly remain after installers and updates.",
                ),
                _scan_directory_target(
                    "shader_cache",
                    "DirectX Shader Cache",
                    "Graphics Cache",
                    local_app_data / "D3DSCache",
                    "Shader cache that Windows recreates automatically when needed.",
                ),
                _scan_directory_target(
                    "crash_dumps",
                    "Crash Dumps",
                    "Diagnostics",
                    local_app_data / "CrashDumps",
                    "Crash dump files created after application failures.",
                ),
                _scan_directory_target(
                    "minidumps",
                    "System Minidumps",
                    "Diagnostics",
                    windir / "Minidump",
                    "Blue-screen and system crash dump files.",
                ),
                _scan_directory_target(
                    "delivery_optimization",
                    "Delivery Optimization Cache",
                    "Windows Update",
                    windir / "SoftwareDistribution" / "DeliveryOptimization" / "Cache",
                    "Cached update chunks that Windows can download again if needed.",
                ),
                _scan_pattern_target(
                    "explorer_cache",
                    "Explorer Thumbnail/Icon Cache",
                    "Windows Cache",
                    local_app_data / "Microsoft" / "Windows" / "Explorer",
                    "Windows Explorer thumbnail and icon databases.",
                    ("thumbcache*.db", "iconcache*.db"),
                ),
                _scan_browser_cache_target(
                    "chrome_cache",
                    "Google Chrome Cache",
                    local_app_data / "Google" / "Chrome" / "User Data",
                    "Browser Cache",
                ),
                _scan_browser_cache_target(
                    "edge_cache",
                    "Microsoft Edge Cache",
                    local_app_data / "Microsoft" / "Edge" / "User Data",
                    "Browser Cache",
                ),
                _scan_firefox_cache_target(
                    "firefox_cache",
                    "Mozilla Firefox Cache",
                    local_app_data / "Mozilla" / "Firefox" / "Profiles",
                    "Browser Cache",
                ),
                _scan_recycle_bin_target(),
            ],
        )
    )

    # Roaming temp-like folders that often retain app leftovers.
    edge_webview_cache = roaming_app_data / "Microsoft" / "Teams"
    if edge_webview_cache.exists():
        webview_items = [
            child
            for child in _safe_iterdir(edge_webview_cache)
            if child.name.lower() in {"cache", "code cache", "gpucache", "logs"}
        ]
        targets.append(
            _build_target(
                "teams_cache",
                "Teams Cache",
                "App Cache",
                str(edge_webview_cache),
                "Microsoft Teams cache and log folders.",
                webview_items,
            )
        )

    return sorted(
        [target for target in targets if target.item_count or target.size_bytes],
        key=lambda target: target.size_bytes,
        reverse=True,
    )


def cleanup_selected_targets(targets: Iterable[CleanupTarget]) -> ActionResult:
    result = ActionResult()
    cutoff = time.time() - RECENT_FILE_GRACE_SECONDS

    for target in targets:
        if target.special_handler == "recycle_bin":
            if _empty_recycle_bin():
                result.freed_bytes += target.size_bytes
                result.deleted_items += target.item_count
                result.messages.append(f"Recycle Bin emptied: {target.location}")
            else:
                result.failed_items += 1
                result.messages.append("Recycle Bin cleanup failed or requires elevation.")
            continue

        for item in target.items:
            item_result = _delete_path(item, cutoff=cutoff, respect_recent=True)
            result.freed_bytes += item_result.freed_bytes
            result.deleted_items += item_result.deleted_items
            result.failed_items += item_result.failed_items
            result.skipped_items += item_result.skipped_items

        result.messages.append(
            f"Cleaned {target.name}: freed about {target.size_bytes // (1024 * 1024)} MB"
        )

    if result.deleted_items == 0 and (result.skipped_items or result.failed_items):
        result.messages.append(
            "Some junk items stayed because they were very recent or locked by another running app."
        )

    return result


def scan_leftover_candidates() -> list[LeftoverCandidate]:
    roots = _leftover_roots()
    installed_names = _installed_app_names()
    installed_norms = {normalize_name(name) for name in installed_names if normalize_name(name)}
    cutoff = datetime.now() - timedelta(days=LEFTOVER_MIN_AGE_DAYS)
    candidates: list[LeftoverCandidate] = []

    for root_label, root_path in roots:
        for child in _safe_iterdir(root_path):
            if not child.is_dir():
                continue
            folder_name = child.name.strip().lower()
            if folder_name in SYSTEM_SKIP_NAMES:
                continue
            if folder_name.startswith("."):
                continue

            modified_at = _safe_modified_at(child)
            if modified_at is None or modified_at > cutoff:
                continue

            normalized = normalize_name(child.name)
            if not normalized:
                continue
            if _matches_installed_app(normalized, installed_norms):
                continue

            size_bytes, file_count = _path_stats(child)
            if size_bytes < LEFTOVER_MIN_SIZE_BYTES or file_count == 0:
                continue

            confidence = _leftover_confidence(child, size_bytes, modified_at, installed_norms)
            if confidence < 60:
                continue

            age_days = max((datetime.now() - modified_at).days, 1)
            candidates.append(
                LeftoverCandidate(
                    path=child,
                    root_label=root_label,
                    size_bytes=size_bytes,
                    modified_at=modified_at,
                    confidence=confidence,
                    reason=f"No installed app match, inactive for {age_days} days.",
                )
            )

    candidates.sort(key=lambda item: (item.confidence, item.size_bytes), reverse=True)
    return candidates[:MAX_LEFTOVER_RESULTS]


def delete_leftover_candidates(candidates: Iterable[LeftoverCandidate]) -> ActionResult:
    result = ActionResult()
    for candidate in candidates:
        item_result = _delete_path(candidate.path, cutoff=0, respect_recent=False)
        result.freed_bytes += item_result.freed_bytes
        result.deleted_items += item_result.deleted_items
        result.failed_items += item_result.failed_items
        result.skipped_items += item_result.skipped_items
        result.messages.append(f"Removed leftover folder: {candidate.path}")
    return result


def deep_clean_system() -> DeepCleanResult:
    cleanup_targets = scan_cleanup_targets()
    cleanup_result = cleanup_selected_targets(cleanup_targets)

    leftover_candidates = scan_leftover_candidates()
    auto_delete_leftovers = [
        candidate
        for candidate in leftover_candidates
        if candidate.confidence >= AUTO_DELETE_LEFTOVER_CONFIDENCE
    ]
    leftover_result = delete_leftover_candidates(auto_delete_leftovers)

    merged = _merge_action_results(cleanup_result, leftover_result)
    merged.messages.append(
        f"Deep clean scanned {len(cleanup_targets)} junk targets and {len(leftover_candidates)} old-software leftover candidates."
    )
    if auto_delete_leftovers:
        merged.messages.append(
            f"Auto-removed {len(auto_delete_leftovers)} high-confidence old-software leftover folders."
        )
    else:
        merged.messages.append(
            "No high-confidence old-software leftover folders qualified for auto-delete."
        )

    remaining_review = max(len(leftover_candidates) - len(auto_delete_leftovers), 0)
    if remaining_review:
        merged.messages.append(
            f"{remaining_review} lower-confidence leftover folders remain in review mode."
        )

    return DeepCleanResult(
        action_result=merged,
        cleanup_target_count=len(cleanup_targets),
        leftover_found_count=len(leftover_candidates),
        leftover_deleted_count=len(auto_delete_leftovers),
        leftover_remaining_review_count=remaining_review,
    )


def open_in_explorer(path: Path) -> None:
    os.startfile(str(path))


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _merge_action_results(*results: ActionResult) -> ActionResult:
    merged = ActionResult()
    for result in results:
        merged.freed_bytes += result.freed_bytes
        merged.deleted_items += result.deleted_items
        merged.failed_items += result.failed_items
        merged.skipped_items += result.skipped_items
        merged.messages.extend(result.messages)
    return merged


def _scan_directory_target(
    key: str,
    name: str,
    category: str,
    path: Path,
    description: str,
) -> CleanupTarget | None:
    if not path.exists():
        return None
    items = _safe_iterdir(path)
    return _build_target(key, name, category, str(path), description, items)


def _scan_pattern_target(
    key: str,
    name: str,
    category: str,
    path: Path,
    description: str,
    patterns: tuple[str, ...],
) -> CleanupTarget | None:
    if not path.exists():
        return None

    items: list[Path] = []
    for pattern in patterns:
        items.extend(path.glob(pattern))

    if not items:
        return None

    return _build_target(key, name, category, str(path), description, items)


def _scan_browser_cache_target(
    key: str,
    name: str,
    base_path: Path,
    category: str,
) -> CleanupTarget | None:
    if not base_path.exists():
        return None

    items: list[Path] = []
    patterns = (
        "Default/Cache",
        "Default/Code Cache",
        "Default/GPUCache",
        "Profile */Cache",
        "Profile */Code Cache",
        "Profile */GPUCache",
    )
    for pattern in patterns:
        items.extend(base_path.glob(pattern))

    if not items:
        return None

    return _build_target(
        key,
        name,
        category,
        str(base_path),
        "Browser cache folders that can be recreated automatically.",
        items,
    )


def _scan_firefox_cache_target(
    key: str,
    name: str,
    base_path: Path,
    category: str,
) -> CleanupTarget | None:
    if not base_path.exists():
        return None

    items: list[Path] = []
    for pattern in ("*/cache2", "*/startupCache"):
        items.extend(base_path.glob(pattern))

    if not items:
        return None

    return _build_target(
        key,
        name,
        category,
        str(base_path),
        "Firefox profile cache and startup cache folders.",
        items,
    )


def _scan_recycle_bin_target() -> CleanupTarget | None:
    query = SHQUERYRBINFO()
    query.cbSize = ctypes.sizeof(SHQUERYRBINFO)
    result = ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(query))
    if result != 0 or query.i64Size <= 0:
        return None

    return CleanupTarget(
        key="recycle_bin",
        name="Recycle Bin",
        category="Recovery",
        location="Windows Recycle Bin",
        description="Files already deleted by the user that still occupy disk space.",
        items=[],
        size_bytes=int(query.i64Size),
        item_count=int(query.i64NumItems),
        special_handler="recycle_bin",
    )


def _build_target(
    key: str,
    name: str,
    category: str,
    location: str,
    description: str,
    items: Iterable[Path],
) -> CleanupTarget:
    item_list = [item for item in items if item.exists()]
    size_bytes, file_count = _measure_items(item_list)
    return CleanupTarget(
        key=key,
        name=name,
        category=category,
        location=location,
        description=description,
        items=item_list,
        size_bytes=size_bytes,
        item_count=file_count,
    )


def _measure_items(items: Iterable[Path]) -> tuple[int, int]:
    total_size = 0
    total_files = 0
    for item in items:
        size_bytes, file_count = _path_stats(item)
        total_size += size_bytes
        total_files += file_count
    return total_size, total_files


def _path_stats(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    if path.is_file():
        try:
            return path.stat().st_size, 1
        except OSError:
            return 0, 0
    if path.is_symlink():
        return 0, 0

    total_size = 0
    file_count = 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_file(follow_symlinks=False):
                            total_size += entry.stat(follow_symlinks=False).st_size
                            file_count += 1
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                    except OSError:
                        continue
        except OSError:
            continue
    return total_size, file_count


def _delete_path(path: Path, cutoff: float, respect_recent: bool) -> ActionResult:
    result = ActionResult()

    if not path.exists():
        result.skipped_items += 1
        return result

    if path.is_file():
        if respect_recent and _is_recent(path, cutoff):
            result.skipped_items += 1
            return result
        file_size = _safe_file_size(path)
        if _unlink_file(path):
            result.freed_bytes += file_size
            result.deleted_items += 1
        else:
            result.failed_items += 1
        return result

    if path.is_symlink():
        try:
            path.unlink(missing_ok=True)
            result.deleted_items += 1
        except OSError:
            result.failed_items += 1
        return result

    for root, dirs, files in os.walk(path, topdown=False):
        root_path = Path(root)
        for file_name in files:
            file_path = root_path / file_name
            if respect_recent and _is_recent(file_path, cutoff):
                result.skipped_items += 1
                continue
            file_size = _safe_file_size(file_path)
            if _unlink_file(file_path):
                result.freed_bytes += file_size
                result.deleted_items += 1
            else:
                result.failed_items += 1

        for dir_name in dirs:
            dir_path = root_path / dir_name
            try:
                dir_path.rmdir()
                result.deleted_items += 1
            except OSError:
                pass

    try:
        path.rmdir()
        result.deleted_items += 1
    except OSError:
        pass

    return result


def _unlink_file(path: Path) -> bool:
    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        pass
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _empty_recycle_bin() -> bool:
    flags = 0x00000001 | 0x00000002 | 0x00000004
    result = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
    return result == 0


def _is_recent(path: Path, cutoff: float) -> bool:
    try:
        return path.stat().st_mtime > cutoff
    except OSError:
        return False


def _safe_file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _safe_modified_at(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None


def _safe_iterdir(path: Path) -> list[Path]:
    try:
        return list(path.iterdir())
    except OSError:
        return []


def _leftover_roots() -> list[tuple[str, Path]]:
    env = os.environ
    roots = [
        ("Local AppData", Path(env.get("LOCALAPPDATA", ""))),
        ("Roaming AppData", Path(env.get("APPDATA", ""))),
        ("Local Programs", Path(env.get("LOCALAPPDATA", "")) / "Programs"),
        ("ProgramData", Path(env.get("ProgramData", r"C:\ProgramData"))),
    ]
    return [(label, path) for label, path in roots if path.exists()]


def _installed_app_names() -> set[str]:
    uninstall_locations = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    names: set[str] = set()
    for hive, location in uninstall_locations:
        try:
            with winreg.OpenKey(hive, location) as root:
                total_subkeys = winreg.QueryInfoKey(root)[0]
                for index in range(total_subkeys):
                    try:
                        subkey_name = winreg.EnumKey(root, index)
                        with winreg.OpenKey(root, subkey_name) as item:
                            display_name, _ = winreg.QueryValueEx(item, "DisplayName")
                            if display_name:
                                names.add(str(display_name))
                    except OSError:
                        continue
        except OSError:
            continue
    return names


def _matches_installed_app(folder_norm: str, installed_norms: set[str]) -> bool:
    if folder_norm in installed_norms:
        return True

    if len(folder_norm) < 5:
        return False

    for installed in installed_norms:
        if len(installed) < 5:
            continue
        if folder_norm in installed or installed in folder_norm:
            return True
    return False


def _leftover_confidence(
    path: Path,
    size_bytes: int,
    modified_at: datetime,
    installed_norms: set[str],
) -> int:
    confidence = 45
    age_days = max((datetime.now() - modified_at).days, 0)
    normalized = normalize_name(path.name)

    if size_bytes >= 50 * 1024 * 1024:
        confidence += 10
    if size_bytes >= 500 * 1024 * 1024:
        confidence += 15
    if age_days >= 60:
        confidence += 10
    if age_days >= 180:
        confidence += 10
    if normalized and not _matches_installed_app(normalized, installed_norms):
        confidence += 15
    if path.parent.name.lower() == "programs":
        confidence += 10
    return min(confidence, 95)
