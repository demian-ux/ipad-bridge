# Quita el monitor virtual (dispositivo Root\MttVDD, paquete del driver, configuración y clave de registro).
# Requiere administrador (se eleva solo). Lo llama el desinstalador si el usuario acepta; se puede correr a mano.
param([string]$Dst = "C:\VirtualDisplayDriver")
$ErrorActionPreference = "Continue"
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    $p = Start-Process powershell.exe -Verb RunAs -Wait -PassThru -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-File","`"$PSCommandPath`"","-Dst","`"$Dst`""
    exit $p.ExitCode
}
$log = Join-Path $env:TEMP "ipad-bridge-uninstall-vdd.log"
Start-Transcript -Path $log -Force | Out-Null
try {
    foreach ($d in (Get-PnpDevice -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -like "*Virtual Display*" })) {
        Write-Host "quitando dispositivo $($d.InstanceId)"
        pnputil /remove-device "$($d.InstanceId)" | Out-String | Write-Host
    }
    # Paquete del driver: pnputil /enum-drivers lista bloques (etiquetas en el idioma de Windows); el que nombra MttVDD.inf
    # tiene su nombre publicado oemNN.inf.
    $blocks = ((pnputil /enum-drivers | Out-String) -split "(\r?\n){2,}")
    foreach ($b in $blocks) {
        if ($b -match "(?i)mttvdd\.inf" -and $b -match "(?i)(oem\d+\.inf)") {
            Write-Host "quitando paquete $($Matches[1])"
            pnputil /delete-driver $Matches[1] /uninstall /force | Out-String | Write-Host
        }
    }
    Remove-Item -Path "HKLM:\SOFTWARE\MikeTheTech\VirtualDisplayDriver" -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path $Dst) { Remove-Item $Dst -Recurse -Force -ErrorAction SilentlyContinue }
    Write-Host "OK"
} finally { Stop-Transcript | Out-Null }
