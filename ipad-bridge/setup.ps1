# Instalación de iPad Bridge en una PC con Windows 11 y GPU NVIDIA. Correr una vez, desde la carpeta del proyecto:
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
# Instala lo que falte (Python, ffmpeg, Dispositivos Apple), las librerías de Python, el monitor virtual (pide
# administrador), genera los certificados para la IP de esta PC y ubica el monitor virtual a la izquierda.
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

function Have($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Winget($id, $source) {
    $args = @("install", "--id", $id, "--accept-package-agreements", "--accept-source-agreements", "-e")
    if ($source) { $args += @("--source", $source) }
    & winget @args | Select-Object -Last 2
}

Write-Host "== 1/6 Python =="
if (-not (Have python) -or -not ((python --version 2>&1) -match "3\.(1[1-9]|[2-9][0-9])")) {
    Winget "Python.Python.3.12" "winget"
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
python --version

Write-Host "== 2/6 ffmpeg (build full de gyan.dev: trae ddagrab y NVENC) =="
if (-not (Have ffmpeg) -or -not ((ffmpeg -hide_banner -filters 2>$null) -match "ddagrab")) {
    Winget "Gyan.FFmpeg" "winget"
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
ffmpeg -version 2>$null | Select-Object -First 1

Write-Host "== 3/6 Librerías de Python =="
python -m pip install --quiet --upgrade aiohttp pymobiledevice3 pillow cryptography numpy zeroconf qrcode
python -c "import aiohttp, pymobiledevice3, PIL, cryptography, zeroconf, qrcode; print('librerias ok')"

Write-Host "== 4/6 Dispositivos Apple (servicio USB para el iPad por cable) =="
if (-not (Get-AppxPackage -Name "AppleInc.AppleDevices*")) { Winget "9NP83LWLPZ9K" "msstore" } else { Write-Host "ya instalada" }

Write-Host "== 5/6 Monitor virtual (pide administrador) =="
if (Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -like "*Virtual Display*" }) {
    Write-Host "ya instalado"
} else {
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "install-vdd.ps1")
    Start-Sleep -Seconds 3
}
python tools\place_vdd.py left --hz=120 --scale=225   # a la izquierda, 120 Hz, interfaz de Windows al 225 % en el iPad

Write-Host "== 6/6 Certificados para esta PC =="
python tools\make_certs.py

Write-Host ""
Write-Host "Listo. Para arrancar:  .\start.ps1   (o .\start.ps1 <IP del iPad> para usar también la red)"
Write-Host "En el iPad, la primera vez: abrí http://<IP de esta PC>/ e instalá el certificado; después https://<IP>/ipad.html"
Write-Host "o la app nativa (zip en esa misma página). Por USB: conectá el iPad, tocá Confiar, y abrí la app Dispositivos Apple una vez."
