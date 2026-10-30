# Pasos de posinstalación de iPad Bridge; el instalador lo llama una vez por tarea elegida (ver ipad-bridge.iss).
# Corre elevado cuando el instalador lo está; con /CURRENTUSER, install-vdd.ps1 pide administrador por su cuenta.
# Todo queda en <carpeta de instalación>\install.log.
param(
    [Parameter(Mandatory)][string]$App,
    [switch]$Firewall,
    [switch]$AppleDevices,
    [switch]$Vdd,
    [switch]$PlaceVdd
)
$ErrorActionPreference = "Continue"
Start-Transcript -Path (Join-Path $App "install.log") -Append | Out-Null
try {
    if ($Firewall) {
        Write-Host "== Firewall: puertos 80 y 443 (TCP, redes privadas) para el Python de iPad Bridge"
        netsh advfirewall firewall delete rule name="iPad Bridge" | Out-Null
        netsh advfirewall firewall add rule name="iPad Bridge" dir=in action=allow protocol=TCP localport="80,443" profile=private program="$App\python\python.exe"
    }
    if ($AppleDevices) {
        Write-Host "== Dispositivos Apple (servicio USB para el iPad)"
        if (Get-AppxPackage -Name "AppleInc.AppleDevices*" -ErrorAction SilentlyContinue) {
            Write-Host "   ya instalada"
        } elseif (Get-Command winget -ErrorAction SilentlyContinue) {
            winget install --id 9NP83LWLPZ9K --source msstore --accept-package-agreements --accept-source-agreements -e
            Write-Host "   winget exit=$LASTEXITCODE"
        } else {
            Write-Host "   sin winget: instalala desde Microsoft Store (buscar 'Dispositivos Apple')"
        }
    }
    if ($Vdd) {
        Write-Host "== Monitor virtual (Virtual Display Driver)"
        if (Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -like "*Virtual Display*" }) {
            Write-Host "   ya instalado"
        } else {
            & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $App "install-vdd.ps1") -Src (Join-Path $App "vendor") -Dst "C:\VirtualDisplayDriver"
            Start-Sleep -Seconds 3
        }
    }
    if ($PlaceVdd) {
        Write-Host "== Ubicando el monitor virtual: izquierda, 120 Hz, escala 225 %"
        & (Join-Path $App "python\python.exe") (Join-Path $App "tools\place_vdd.py") left --hz=120 --scale=225
    }
} catch {
    Write-Host "ERROR: $_"
} finally {
    Stop-Transcript | Out-Null
}
