# Construye el instalador de iPad Bridge (Inno Setup) en la PC de desarrollo. Uso, desde cualquier carpeta:
#   powershell -ExecutionPolicy Bypass -File C:\Users\dszkl\ipad-link\ipad-bridge\installer\build.ps1 [-Version 0.1.5] [-NoCompile]
# Necesita: Python 3.12 (el mismo que usa el proyecto: los paquetes se instalan con su pip para el Python embebido),
# ffmpeg "full" de gyan.dev instalado (setup.ps1 lo instala con winget; se copia de ahí), Inno Setup 6
# (winget install JRSoftware.InnoSetup) e internet la primera vez (Python embebido, driver y nefcon van a vendor\).
# Resultado: installer\dist\iPadBridge-Setup-<versión>.exe. vendor\ y payload\ se regeneran y no van al repositorio.
param(
    [string]$Version = "",
    [switch]$NoCompile          # solo arma payload\ (para revisar qué va adentro)
)
$ErrorActionPreference = "Stop"
$Installer = $PSScriptRoot
$Proj = Split-Path $Installer -Parent
$Vendor = Join-Path $Installer "vendor"
$Payload = Join-Path $Installer "payload"
$Dist = Join-Path $Installer "dist"
$PyVer = "3.12.10"
$PyUrl = "https://www.python.org/ftp/python/$PyVer/python-$PyVer-embed-amd64.zip"
$Packages = @("aiohttp", "pymobiledevice3", "pillow", "cryptography", "numpy", "pystray")   # lo mismo que setup.ps1 + pystray
if (-not $Version) { $Version = "0.1." + (git -C $Proj rev-list --count HEAD) }

function Step($t) { Write-Host "`n== $t ==" -ForegroundColor Cyan }
New-Item -ItemType Directory -Force -Path $Vendor, $Dist | Out-Null

Step "1/6 Python embebido $PyVer en vendor\python"
$pyinfo = (python -c "import sys; print('%d.%d' % sys.version_info[:2])")
if ($pyinfo -ne "3.12") { throw "El Python de desarrollo es $pyinfo; hace falta 3.12 (los paquetes se instalan con su pip para el embebido 3.12)" }
$pyDir = Join-Path $Vendor "python"
if (-not (Test-Path (Join-Path $pyDir "python.exe"))) {
    $zip = Join-Path $Vendor "python-$PyVer-embed-amd64.zip"
    if (-not (Test-Path $zip)) { Invoke-WebRequest -Uri $PyUrl -OutFile $zip -UseBasicParsing }
    Expand-Archive -Path $zip -DestinationPath $pyDir -Force
}
# ._pth: rutas fijas del embebido + site-packages + ".." (la carpeta de la app: con ._pth el intérprete no agrega la
# carpeta del script, y server.py importa hevc y winput); "import site" procesa los .pth de los paquetes (pywin32).
Set-Content -Path (Join-Path $pyDir "python312._pth") -Encoding ascii -Value @("python312.zip", ".", "Lib\site-packages", "..", "import site")
$site = Join-Path $pyDir "Lib\site-packages"
New-Item -ItemType Directory -Force -Path $site | Out-Null

Step "2/6 Paquetes de Python ($($Packages -join ', ')) en el embebido"
python -m pip install --quiet --upgrade --target $site @Packages
& (Join-Path $pyDir "python.exe") -c "import aiohttp, pymobiledevice3.usbmux, PIL, cryptography, numpy, pystray; print('runtime embebido ok')"
if ($LASTEXITCODE -ne 0) { throw "el Python embebido no importa los paquetes" }

Step "3/6 ffmpeg (copia del instalado en esta PC)"
$ff = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source
if (-not $ff) { throw "No hay ffmpeg en el PATH: winget install Gyan.FFmpeg (o setup.ps1)" }
$item = Get-Item $ff
if ($item.Target) { $ff = $item.Target | Select-Object -First 1 }     # el enlace de winget apunta al exe real
if (-not ((& $ff -hide_banner -filters 2>$null) -match "ddagrab") -or -not ((& $ff -hide_banner -encoders 2>$null) -match "hevc_nvenc")) {
    throw "$ff no tiene ddagrab o hevc_nvenc: hace falta el build full de gyan.dev"
}
New-Item -ItemType Directory -Force -Path (Join-Path $Vendor "ffmpeg") | Out-Null
Copy-Item $ff (Join-Path $Vendor "ffmpeg\ffmpeg.exe") -Force
Write-Host "   $ff"

Step "4/6 Virtual Display Driver y nefcon (install-vdd.ps1 -DownloadOnly)"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Proj "install-vdd.ps1") -DownloadOnly -Src $Vendor
if (-not (Test-Path (Join-Path $Vendor "vdd\VirtualDisplayDriver\MttVDD.inf"))) { throw "no se descargó el driver" }

Step "5/6 Armando payload\"
if (Test-Path $Payload) { Remove-Item $Payload -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Payload, (Join-Path $Payload "vendor") | Out-Null
foreach ($f in @("server.py", "usb_bridge.py", "tray.py", "hevc.py", "winput.py", "install-vdd.ps1", "set-vdd-120.ps1", "README.md")) {
    Copy-Item (Join-Path $Proj $f) $Payload
}
$rc = @("/E", "/NFL", "/NDL", "/NJH", "/NJS", "/XD", "__pycache__")
robocopy (Join-Path $Proj "static") (Join-Path $Payload "static") @rc | Out-Null
robocopy (Join-Path $Proj "tools") (Join-Path $Payload "tools") @rc | Out-Null
robocopy (Join-Path $Installer "scripts") (Join-Path $Payload "scripts") @rc | Out-Null
robocopy $pyDir (Join-Path $Payload "python") @rc | Out-Null
robocopy (Join-Path $Vendor "ffmpeg") (Join-Path $Payload "ffmpeg") @rc | Out-Null
robocopy (Join-Path $Vendor "vdd") (Join-Path $Payload "vendor\vdd") @rc | Out-Null
robocopy (Join-Path $Vendor "nefcon") (Join-Path $Payload "vendor\nefcon") @rc | Out-Null
python -c "import sys; sys.path.insert(0, r'$Proj'); import tray; tray.write_ico(r'$Payload\ipad-bridge.ico')"
$size = [math]::Round((Get-ChildItem $Payload -Recurse -File | Measure-Object Length -Sum).Sum / 1MB)
Write-Host "   payload: $size MB"
if ($NoCompile) { Write-Host "Listo (sin compilar): $Payload"; exit 0 }

Step "6/6 Inno Setup"
$iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
foreach ($c in @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe")) {
    if (-not $iscc -and (Test-Path $c)) { $iscc = $c }
}
if (-not $iscc) { throw "No encuentro ISCC.exe: winget install JRSoftware.InnoSetup" }
& $iscc /Q "/DAppVersion=$Version" "/O$Dist" (Join-Path $Installer "ipad-bridge.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC terminó con $LASTEXITCODE" }
$out = Join-Path $Dist "iPadBridge-Setup-$Version.exe"
Write-Host "`nListo: $out ($([math]::Round((Get-Item $out).Length / 1MB)) MB)" -ForegroundColor Green
