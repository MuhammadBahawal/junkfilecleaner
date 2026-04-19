# Release Checklist

## Source Repo

1. Commit the source code to GitHub.
2. Push the repository.
3. Confirm that `build/`, `dist/`, `release/`, and `__pycache__/` are not part of the commit.

## Portable App

1. Run:

```powershell
.\build_exe.ps1
```

2. Upload one of these files to GitHub Releases:

- `dist/CleanerPro.exe`
- `release/CleanerPro-portable.zip`

3. Optionally include the checksum from:

- `release/CleanerPro-sha256.txt`

## Recommended Release Title

`CleanerPro v1.0.0`

