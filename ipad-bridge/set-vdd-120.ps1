# Habilita 120 Hz en el monitor virtual: agrega el refresco al vdd_settings.xml y reinicia el dispositivo
# para que el driver lo relea. Requiere administrador (se eleva solo). Después: python tools/place_vdd.py left --hz=120
param([string]$Dst = "C:\VirtualDisplayDriver")
$ErrorActionPreference = "Stop"
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    $p = Start-Process powershell.exe -Verb RunAs -Wait -PassThru -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-File","`"$PSCommandPath`"","-Dst","`"$Dst`""
    Get-Content (Join-Path $Dst "set120.log") -ErrorAction SilentlyContinue
    exit $p.ExitCode
}
$log = Join-Path $Dst "set120.log"
Start-Transcript -Path $log -Force | Out-Null
try {
    $xml = Join-Path $Dst "vdd_settings.xml"
    $s = Get-Content $xml -Raw
    if ($s -notmatch "<g_refresh_rate>120</g_refresh_rate>") {
        $s = $s -replace "<g_refresh_rate>60</g_refresh_rate>", "<g_refresh_rate>60</g_refresh_rate>`n        <g_refresh_rate>120</g_refresh_rate>"
        Set-Content -Path $xml -Value $s -Encoding utf8
        Write-Host "120 Hz agregado a vdd_settings.xml"
    } else { Write-Host "vdd_settings.xml ya tenia 120 Hz" }
    $dev = Get-PnpDevice | Where-Object { $_.FriendlyName -like "*Virtual Display*" } | Select-Object -First 1
    Write-Host "Reiniciando $($dev.InstanceId)"
    pnputil /restart-device "$($dev.InstanceId)" | Out-String | Write-Host
    Start-Sleep -Seconds 4
    Write-Host "OK"
} catch { Write-Host "ERROR: $_" } finally { Stop-Transcript | Out-Null }
