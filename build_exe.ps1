$ErrorActionPreference = "Stop"

Set-Location -Path $PSScriptRoot

$outputExe = Join-Path $PSScriptRoot "dist\\CleanerPro.exe"
$releaseDir = Join-Path $PSScriptRoot "release"
$portableZip = Join-Path $releaseDir "CleanerPro-portable.zip"
$checksumFile = Join-Path $releaseDir "CleanerPro-sha256.txt"
$packageDir = Join-Path $releaseDir "package"
$running = Get-Process CleanerPro -ErrorAction SilentlyContinue
if ($running) {
  $running | Stop-Process -Force
  Start-Sleep -Milliseconds 800
}

if (Test-Path $outputExe) {
  Remove-Item $outputExe -Force
}

if (Test-Path $releaseDir) {
  Remove-Item $releaseDir -Recurse -Force
}
New-Item -ItemType Directory -Path $releaseDir | Out-Null

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --icon assets\cleanerpro.ico `
  --add-data "assets;assets" `
  --name CleanerPro `
  app.py

New-Item -ItemType Directory -Path $packageDir | Out-Null
Copy-Item $outputExe (Join-Path $packageDir "CleanerPro.exe")
Copy-Item (Join-Path $PSScriptRoot "README.md") (Join-Path $packageDir "README.md")
Copy-Item (Join-Path $PSScriptRoot "LICENSE") (Join-Path $packageDir "LICENSE")

Compress-Archive -Path (Join-Path $packageDir "*") -DestinationPath $portableZip -Force

$hash = (Get-FileHash -Algorithm SHA256 $outputExe).Hash
"CleanerPro.exe SHA256: $hash" | Set-Content -Path $checksumFile -Encoding ASCII

Remove-Item $packageDir -Recurse -Force

Write-Host ""
Write-Host "Build complete:" -ForegroundColor Green
Write-Host "  $PSScriptRoot\\dist\\CleanerPro.exe"
Write-Host "  $portableZip"
Write-Host "  $checksumFile"
