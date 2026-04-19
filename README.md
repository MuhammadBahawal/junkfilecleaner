# CleanerPro

![CleanerPro Icon](assets/cleanerpro-icon.png)

CleanerPro is a Windows desktop utility for cleaning safe junk files, reviewing old software leftovers, monitoring system usage, and managing heavy tasks from both the main window and the system tray.

## Features

- junk and temporary file cleanup
- browser cache cleanup
- uninstall-leftover folder detection
- live CPU, RAM, disk, and task monitoring
- process list with end-task support
- bottom-right tray quick panel
- high-DPI aware UI and custom Windows icon
- one-click EXE packaging

## Included Files

- `app.py`: desktop app entry point
- `cleaner_app/`: cleanup engine, monitoring, UI, and tray logic
- `assets/`: icon files used by the source app and packaged EXE
- `build_exe.ps1`: one-step Windows build script
- `RELEASE.md`: GitHub publishing and release checklist

## Safety Model

CleanerPro is intentionally conservative:

- it targets temporary files, caches, crash dumps, and Recycle Bin data
- very recent files are skipped automatically to reduce the chance of interfering with active apps
- lower-confidence software leftovers stay review-based unless the user chooses a stronger cleanup flow
- it does not perform risky registry cleaning

## Run From Source

```powershell
python app.py
```

## Build The EXE

```powershell
.\build_exe.ps1
```

Build outputs:

- `dist/CleanerPro.exe`
- `release/CleanerPro-portable.zip`
- `release/CleanerPro-sha256.txt`

The build script packages:

- `assets/cleanerpro.ico` as the Windows app icon
- tray/taskbar icon resources for the packaged EXE
- a single portable `.exe`
- a ZIP release package and SHA-256 checksum

## GitHub Publishing

1. Push the source code to GitHub.
2. Do not commit `build/`, `dist/`, or `release/` to the source repo.
3. Create a GitHub Release.
4. Upload either `dist/CleanerPro.exe` or `release/CleanerPro-portable.zip`.
5. Optionally include `release/CleanerPro-sha256.txt` in the release assets.

## Main Screens

- `Overview`: system summary, recoverable space, top heavy tasks
- `Cleanup`: junk scan, selected cleanup, and one-click deep cleanup
- `Leftovers`: review likely orphaned folders left after uninstall
- `Tasks`: search, inspect, and end running processes

## Tray Workflow

- closing the main window sends CleanerPro to the Windows system tray
- clicking the tray icon opens a small bottom-right quick panel
- the quick panel can scan junk, clean safe junk, run quick boost, deep clean, and manage heavy tasks

## Notes

- browser cache cleanup may skip files if the browser is currently open
- some system locations may require elevated permissions for full cleanup
- leftover detection is heuristic-based, so review flagged folders before deleting them
- CleanerPro improves responsiveness by removing safe clutter and helping manage heavy tasks, but it intentionally avoids unsafe "magic boost" claims like registry cleaning or blind task killing

