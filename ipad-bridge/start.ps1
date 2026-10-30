# Levanta iPad Bridge: servidor (80/443) + puente a la app nativa.
#   .\start.ps1              -> puente solo por USB
#   .\start.ps1 192.168.1.63 -> puente por USB y, si no hay cable, por red a esa IP del iPad
param([string]$IpadIp = "")
Set-Location $PSScriptRoot
python tools\make_certs.py | Out-Null          # reemite el certificado si cambió la IP de la PC
$bridgeArgs = @('-u', 'usb_bridge.py', 'auto', 'ws://localhost/ws')
if ($IpadIp) { $bridgeArgs += $IpadIp }
# El puente corre oculto: su salida queda en bridge.log / bridge.err. El servidor escribe en consola y en server.log.
Start-Process python -ArgumentList $bridgeArgs -WindowStyle Hidden -RedirectStandardOutput bridge.log -RedirectStandardError bridge.err
python server.py 80 443
