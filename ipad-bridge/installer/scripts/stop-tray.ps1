# Cierra todo lo que corra desde la carpeta de instalación (bandeja, servidor, puente, ffmpeg) antes de actualizar o
# desinstalar. El instalador lo llama con -App "<carpeta>".
param([Parameter(Mandatory)][string]$App)
$prefix = $App.TrimEnd("\") + "\"
Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($prefix, "OrdinalIgnoreCase") } | ForEach-Object {
    Write-Host "cerrando $($_.ProcessId) $($_.ExecutablePath)"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Milliseconds 500
