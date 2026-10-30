# Instala Virtual Display Driver (MikeTheTech, MIT, firmado por SignPath) como monitor virtual para el iPad,
# con las resoluciones del iPad Pro 12.9" a 60 y 120 Hz. Descarga el driver y nefcon desde GitHub si hace falta.
# Requiere administrador (se eleva solo). Fuente: https://github.com/VirtualDrivers/Virtual-Display-Driver
# -DownloadOnly: solo baja y descomprime en -Src (sin administrador); lo usa installer\build.ps1 para empaquetar el driver.
param(
    [string]$Src = "$env:LOCALAPPDATA\Temp\ipad-bridge-dl",
    [string]$Dst = "C:\VirtualDisplayDriver",
    [switch]$DownloadOnly
)
$ErrorActionPreference = "Stop"
$VddUrl = "https://github.com/VirtualDrivers/Virtual-Display-Driver/releases/download/25.7.23/VirtualDisplayDriver-x86.Driver.Only.zip"
$NefconUrl = "https://github.com/nefarius/nefcon/releases/download/v1.21.0/nefcon_v1.21.0.zip"

function Download-Vdd($Src) {
    $driverDir = Join-Path $Src "vdd\VirtualDisplayDriver"
    $nefcon = Join-Path $Src "nefcon\x64\nefconc.exe"
    if ((Test-Path (Join-Path $driverDir "MttVDD.inf")) -and (Test-Path $nefcon)) { Write-Host "1/5 Driver y nefcon ya descargados"; return }
    Write-Host "1/5 Descargando driver y nefcon"
    New-Item -ItemType Directory -Force -Path $Src | Out-Null
    Invoke-WebRequest -Uri $VddUrl -OutFile (Join-Path $Src "vdd-x86.zip") -UseBasicParsing
    Invoke-WebRequest -Uri $NefconUrl -OutFile (Join-Path $Src "nefcon.zip") -UseBasicParsing
    Expand-Archive -Path (Join-Path $Src "vdd-x86.zip") -DestinationPath (Join-Path $Src "vdd") -Force
    Expand-Archive -Path (Join-Path $Src "nefcon.zip") -DestinationPath (Join-Path $Src "nefcon") -Force
}
if ($DownloadOnly) { Download-Vdd $Src; exit 0 }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    $p = Start-Process powershell.exe -Verb RunAs -Wait -PassThru -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-File","`"$PSCommandPath`"","-Src","`"$Src`"","-Dst","`"$Dst`""
    Get-Content (Join-Path $Dst "install.log") -ErrorAction SilentlyContinue | Select-String "^\d/5|exit=|OK|ERROR|Virtual Display|   CN="
    exit $p.ExitCode
}

New-Item -ItemType Directory -Force -Path $Dst, $Src | Out-Null
$log = Join-Path $Dst "install.log"
Start-Transcript -Path $log -Force | Out-Null
try {
    $driverDir = Join-Path $Src "vdd\VirtualDisplayDriver"
    $nefcon = Join-Path $Src "nefcon\x64\nefconc.exe"
    if (-not (Test-Path (Join-Path $driverDir "MttVDD.inf")) -or -not (Test-Path $nefcon)) {
        Write-Host "1/5 Descargando driver y nefcon"
        Invoke-WebRequest -Uri $VddUrl -OutFile (Join-Path $Src "vdd-x86.zip") -UseBasicParsing
        Invoke-WebRequest -Uri $NefconUrl -OutFile (Join-Path $Src "nefcon.zip") -UseBasicParsing
        Expand-Archive -Path (Join-Path $Src "vdd-x86.zip") -DestinationPath (Join-Path $Src "vdd") -Force
        Expand-Archive -Path (Join-Path $Src "nefcon.zip") -DestinationPath (Join-Path $Src "nefcon") -Force
    } else { Write-Host "1/5 Driver y nefcon ya descargados" }
    foreach ($f in @((Join-Path $driverDir "mttvdd.cat"), (Join-Path $driverDir "MttVDD.dll"), $nefcon)) {
        $sig = Get-AuthenticodeSignature $f
        if ($sig.Status -ne "Valid") { throw "Firma invalida en $f ($($sig.Status))" }
    }
    Write-Host "   firmas validas (SignPath Foundation / Nefarius)"

    Write-Host "2/5 Copiando driver y configuracion a $Dst"
    Copy-Item (Join-Path $driverDir "*") $Dst -Force
    $settings = @"
<?xml version='1.0' encoding='utf-8'?>
<vdd_settings>
    <monitors><count>1</count></monitors>
    <gpu><friendlyname>default</friendlyname></gpu>
    <global>
        <g_refresh_rate>60</g_refresh_rate>
        <g_refresh_rate>120</g_refresh_rate>
    </global>
    <resolutions>
        <!-- iPad Pro 12.9" (2732x2048, 4:3) y mitades; 1920x1080 por si se usa otro visor -->
        <resolution><width>2732</width><height>2048</height><refresh_rate>60</refresh_rate></resolution>
        <resolution><width>2048</width><height>1536</height><refresh_rate>60</refresh_rate></resolution>
        <resolution><width>1366</width><height>1024</height><refresh_rate>60</refresh_rate></resolution>
        <resolution><width>1920</width><height>1080</height><refresh_rate>60</refresh_rate></resolution>
    </resolutions>
    <options>
        <CustomEdid>false</CustomEdid><PreventSpoof>false</PreventSpoof><EdidCeaOverride>false</EdidCeaOverride>
        <HardwareCursor>true</HardwareCursor><SDR10bit>false</SDR10bit><HDRPlus>false</HDRPlus>
        <logging>false</logging><debuglogging>false</debuglogging>
    </options>
</vdd_settings>
"@
    Set-Content -Path (Join-Path $Dst "vdd_settings.xml") -Value $settings -Encoding utf8
    New-Item -Path "HKLM:\SOFTWARE\MikeTheTech\VirtualDisplayDriver" -Force | Out-Null
    Set-ItemProperty -Path "HKLM:\SOFTWARE\MikeTheTech\VirtualDisplayDriver" -Name "VDDPATH" -Value $Dst

    Write-Host "3/5 Confiando el certificado de firma del driver"
    $certs = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2Collection
    $certs.Import([System.IO.File]::ReadAllBytes((Join-Path $Dst "mttvdd.cat")))
    foreach ($c in $certs) {
        $store = New-Object System.Security.Cryptography.X509Certificates.X509Store("TrustedPublisher", "LocalMachine")
        $store.Open("ReadWrite"); $store.Add($c); $store.Close()
        Write-Host "   " $c.Subject
    }

    Write-Host "4/5 Creando el dispositivo virtual Root\MttVDD"
    & $nefcon --create-device-node --hardware-id "Root\MttVDD" --class-name Display --class-guid "{4D36E968-E325-11CE-BFC1-08002BE10318}" --no-duplicates
    Write-Host "   exit=$LASTEXITCODE"

    Write-Host "5/5 Instalando el driver"
    & $nefcon --install-driver --inf-path (Join-Path $Dst "MttVDD.inf")
    Write-Host "   exit=$LASTEXITCODE"
    Start-Sleep -Seconds 5
    Get-PnpDevice | Where-Object { $_.FriendlyName -like "*Virtual Display*" } | Format-Table Status, Class, FriendlyName, InstanceId -AutoSize
    Write-Host "OK"
} catch {
    Write-Host "ERROR: $_"
} finally {
    Stop-Transcript | Out-Null
}
