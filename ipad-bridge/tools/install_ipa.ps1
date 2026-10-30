# Baja el último iPadBridge.ipa que compiló GitHub Actions y lo deja listo para instalarlo en el iPad con SideStore.
# Uso, desde cualquier carpeta:
#   powershell -ExecutionPolicy Bypass -File C:\Users\dszkl\ipad-link\ipad-bridge\tools\install_ipa.ps1            # último build verde de esta rama
#   ... install_ipa.ps1 -Branch main                                                                              # de otra rama
#   ... install_ipa.ps1 -Release                                                                                  # último Release (tag v*)
#   ... install_ipa.ps1 -Tag v0.2.0                                                                               # un Release concreto
#   ... install_ipa.ps1 -Ipa C:\Descargas\iPadBridge.ipa                                                          # un IPA ya bajado
# Qué hace: elige la corrida verde más reciente del workflow ipa.yml (o el Release), baja iPadBridge.ipa e
# iPadBridge.json, verifica el SHA-256, los copia a static\ (el servidor los sirve en https://<IP de la PC>/) y escribe
# static\sidestore.json, una fuente de SideStore que apunta a ese IPA. En el iPad, SideStore (o AltStore) lo firma con
# el Apple ID gratuito y lo instala; ver README, "App nativa: instalar desde el IPA".
# Token de GitHub: los artifacts de Actions solo se bajan autenticado. Se usa `gh auth token` si está GitHub CLI, y si
# no el token que Git Credential Manager guardó para github.com (el mismo con el que se hace push). Los Releases de
# un repo público no necesitan token.
param(
    [string]$Repo = "",        # owner/nombre; por defecto el remoto origin del repo
    [string]$Branch = "",      # rama cuya última corrida verde se baja; por defecto la rama actual
    [switch]$Release,          # el último Release en vez del último artifact
    [string]$Tag = "",         # un Release por tag (implica -Release)
    [string]$Ipa = "",         # IPA local: no baja nada, solo lo publica en static\
    [string]$Out = "",         # carpeta destino; por defecto static\ del proyecto
    [switch]$NoSource          # no escribir static\sidestore.json
)
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Proj = Split-Path $PSScriptRoot -Parent                # ipad-bridge\
$Root = Split-Path $Proj -Parent                        # raíz del repo
if (-not $Out) { $Out = Join-Path $Proj "static" }
$Tmp = Join-Path $env:TEMP ("ipadbridge-ipa-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Force -Path $Out, $Tmp | Out-Null
$Api = "https://api.github.com"
$UA = @{ "User-Agent" = "ipad-bridge-install_ipa"; "Accept" = "application/vnd.github+json" }

function Step($t) { Write-Host "`n== $t ==" -ForegroundColor Cyan }

function Get-Repo {
    if ($Repo) { return $Repo }
    $url = git -C $Root remote get-url origin 2>$null
    if ($url -match "github\.com[:/]([^/]+)/([^/\s]+?)(\.git)?$") { return "$($Matches[1])/$($Matches[2])" }
    throw "No pude deducir el repo de GitHub del remoto origin ($url). Pasá -Repo owner/nombre."
}

function Get-Token {
    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if ($gh) {
        $t = (& gh auth token 2>$null)
        if ($LASTEXITCODE -eq 0 -and $t) { return $t.Trim() }
    }
    # Git Credential Manager: el token guardado para github.com (sin abrir diálogos si no hay ninguno).
    $env:GCM_INTERACTIVE = "never"
    $out = "protocol=https`nhost=github.com`n`n" | git credential fill 2>$null
    $pw = ($out | Where-Object { $_ -like "password=*" } | Select-Object -First 1)
    if ($pw) { return $pw.Substring(9) }
    return $null
}

# Invoke-WebRequest con un token y, si GitHub redirige al almacenamiento (artifacts, assets), segunda petición sin el
# token: el blob storage rechaza peticiones con Authorization.
function Download($url, $dest, $token) {
    # HttpWebRequest sin seguir redirecciones: Invoke-WebRequest -MaximumRedirection 0 falla en PowerShell 5.1 sin
    # devolver la respuesta, así que no se puede leer Location.
    $req = [Net.HttpWebRequest]::Create($url)
    $req.UserAgent = $UA["User-Agent"]
    $req.AllowAutoRedirect = $false
    if ($token) { $req.Headers["Authorization"] = "Bearer $token" }
    $resp = $req.GetResponse()
    $code = [int]$resp.StatusCode
    if ($code -ge 300 -and $code -lt 400) {
        $location = $resp.Headers["Location"]
        $resp.Close()
        Invoke-WebRequest -Uri $location -OutFile $dest -UseBasicParsing -Headers @{ "User-Agent" = $UA["User-Agent"] }
    } else {
        $fs = [IO.File]::Create($dest)
        try { $resp.GetResponseStream().CopyTo($fs) } finally { $fs.Close(); $resp.Close() }
    }
}

function Api($path, $token) {
    $h = $UA.Clone()
    if ($token) { $h["Authorization"] = "Bearer $token" }
    return Invoke-RestMethod -Uri "$Api$path" -Headers $h -UseBasicParsing
}

function Get-LocalIp {
    try {
        $s = New-Object System.Net.Sockets.UdpClient
        $s.Connect("8.8.8.8", 80)           # no manda nada: solo elige la interfaz con salida
        $ip = $s.Client.LocalEndPoint.Address.ToString()
        $s.Close()
        return $ip
    } catch { return "<IP de la PC>" }
}

# ---------------------------------------------------------------------------------------------------------------------
$ipaSrc = $null
$metaSrc = $null
if ($Ipa) {
    Step "IPA local"
    if (-not (Test-Path $Ipa)) { throw "No existe $Ipa" }
    $ipaSrc = (Get-Item $Ipa).FullName
    $j = Join-Path (Split-Path $ipaSrc -Parent) "iPadBridge.json"
    if (Test-Path $j) { $metaSrc = $j }
} else {
    $repo = Get-Repo
    $token = Get-Token
    if ($Tag) { $Release = $true }
    if ($Release) {
        Step "Release de $repo"
        $rel = if ($Tag) { Api "/repos/$repo/releases/tags/$Tag" $token } else { Api "/repos/$repo/releases/latest" $token }
        Write-Host "Release $($rel.tag_name) ($($rel.published_at)): $($rel.html_url)"
        $aIpa = $rel.assets | Where-Object { $_.name -eq "iPadBridge.ipa" } | Select-Object -First 1
        $aJson = $rel.assets | Where-Object { $_.name -eq "iPadBridge.json" } | Select-Object -First 1
        if (-not $aIpa) { throw "El release $($rel.tag_name) no tiene iPadBridge.ipa (¿falló la corrida de Actions del tag?)" }
        $ipaSrc = Join-Path $Tmp "iPadBridge.ipa"
        Download $aIpa.browser_download_url $ipaSrc $null
        if ($aJson) { $metaSrc = Join-Path $Tmp "iPadBridge.json"; Download $aJson.browser_download_url $metaSrc $null }
    } else {
        if (-not $Branch) { $Branch = (git -C $Root rev-parse --abbrev-ref HEAD 2>$null); if (-not $Branch) { $Branch = "main" } }
        Step "Última corrida verde de ipa.yml en $repo ($Branch)"
        if (-not $token) { throw "Para bajar artifacts hace falta un token de GitHub: instalá GitHub CLI (winget install GitHub.cli; gh auth login) o hacé un push desde esta PC para que Git guarde el token. Alternativa sin token: -Release." }
        $runs = Api "/repos/$repo/actions/workflows/ipa.yml/runs?status=success&branch=$([uri]::EscapeDataString($Branch))&per_page=1" $token
        if (-not $runs.workflow_runs -or $runs.workflow_runs.Count -eq 0) { throw "No hay corridas verdes de ipa.yml en la rama $Branch. Mirá https://github.com/$repo/actions" }
        $run = $runs.workflow_runs[0]
        Write-Host "Corrida #$($run.run_number) ($($run.head_sha.Substring(0,7)), $($run.updated_at)): $($run.html_url)"
        $arts = Api "/repos/$repo/actions/runs/$($run.id)/artifacts" $token
        $art = $arts.artifacts | Where-Object { $_.name -like "iPadBridge-ipa-*" -and -not $_.expired } | Select-Object -First 1
        if (-not $art) { throw "La corrida no tiene el artifact iPadBridge-ipa-* (¿venció? duran 30 días). Probá -Release o relanzá el workflow." }
        $zip = Join-Path $Tmp "artifact.zip"
        Download $art.archive_download_url $zip $token
        Expand-Archive -Path $zip -DestinationPath (Join-Path $Tmp "art") -Force
        $ipaSrc = Get-ChildItem (Join-Path $Tmp "art") -Recurse -Filter "iPadBridge.ipa" | Select-Object -First 1 -ExpandProperty FullName
        $metaSrc = Get-ChildItem (Join-Path $Tmp "art") -Recurse -Filter "iPadBridge.json" | Select-Object -First 1 -ExpandProperty FullName
        if (-not $ipaSrc) { throw "El artifact no trae iPadBridge.ipa" }
    }
}

Step "Verificar y publicar en $Out"
$meta = $null
if ($metaSrc -and (Test-Path $metaSrc)) {
    $meta = Get-Content $metaSrc -Raw | ConvertFrom-Json
    $sha = (Get-FileHash $ipaSrc -Algorithm SHA256).Hash.ToLower()
    if ($meta.sha256 -and $sha -ne $meta.sha256) { throw "SHA-256 distinto al de iPadBridge.json ($sha vs $($meta.sha256)): descarga corrupta" }
    Write-Host "iPadBridge.ipa versión $($meta.version) (build $($meta.build), commit $($meta.commit.Substring(0,7)), $($meta.date)) · SHA-256 ok"
} else {
    Write-Host "Sin iPadBridge.json: no se verifica el hash ni se conoce la versión"
}
$ipaDst = Join-Path $Out "iPadBridge.ipa"
Copy-Item $ipaSrc $ipaDst -Force
if ($metaSrc) { Copy-Item $metaSrc (Join-Path $Out "iPadBridge.json") -Force }
$size = (Get-Item $ipaDst).Length
Write-Host ("{0} ({1:N1} MB)" -f $ipaDst, ($size / 1MB))

$ip = Get-LocalIp
$base = "https://$ip"
if (-not $NoSource) {
    # Fuente de SideStore/AltStore que apunta al IPA servido por esta PC (el iPad ya confía en el certificado del
    # servidor si instaló la CA; si no, la misma URL por http:// también funciona).
    $ver = if ($meta -and $meta.version) { $meta.version } else { "0.0.0" }
    $build = if ($meta -and $meta.build) { "$($meta.build)" } else { "0" }
    $date = if ($meta -and $meta.date) { $meta.date } else { (Get-Date -Format "yyyy-MM-dd") }
    $bundle = if ($meta -and $meta.bundleIdentifier) { $meta.bundleIdentifier } else { "studio.oaki.ipadbridge" }
    $minOs = if ($meta -and $meta.minOSVersion) { $meta.minOSVersion } else { "16.0" }
    $desc = if ($meta -and $meta.commit) { "Commit $($meta.commit.Substring(0,7)) ($($meta.ref)) · $($meta.run)" } else { "IPA local" }
    $source = [ordered]@{
        name = "iPad Bridge (esta PC)"
        identifier = "$bundle.local"
        subtitle = "Build servido por $ip"
        description = "El IPA que bajó tools/install_ipa.ps1 en esta PC. Se actualiza cada vez que se corre el script."
        apps = @(
            [ordered]@{
                name = "iPad Bridge"
                bundleIdentifier = $bundle
                developerName = "Demian Szklarski"
                subtitle = "Pantalla extendida de Windows con Apple Pencil"
                localizedDescription = "Recibe la pantalla de la PC por USB o red y manda el Pencil y los toques."
                iconURL = "$base/app-icon.png"
                tintColor = "#4c8dff"
                category = "utilities"
                versions = @(
                    [ordered]@{
                        version = $ver
                        buildVersion = $build
                        date = $date
                        localizedDescription = $desc
                        downloadURL = "$base/iPadBridge.ipa"
                        size = $size
                        minOSVersion = $minOs
                    }
                )
            }
        )
    }
    $srcPath = Join-Path $Out "sidestore.json"
    # UTF-8 sin BOM (Out-File -Encoding utf8 lo agrega y hay parsers de JSON que no lo aceptan).
    [IO.File]::WriteAllText($srcPath, ($source | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding $false))
    Write-Host "$srcPath (fuente de SideStore, versión $ver)"
}
Remove-Item $Tmp -Recurse -Force -ErrorAction SilentlyContinue

# ¿Está el servidor? (Get-NetTCPConnection no siempre lista el socket de Python; probar a conectar es más fiable.)
$serving = $false
try { $c = New-Object Net.Sockets.TcpClient; $c.Connect("127.0.0.1", 443); $serving = $c.Connected; $c.Close() } catch { $serving = $false }
Write-Host ""
Write-Host "Listo. En el iPad (con el servidor de la PC corriendo" -NoNewline
if (-not $serving) { Write-Host "; ahora no escucha en 443: arrancalo con start.ps1 o el icono de la bandeja" -ForegroundColor Yellow -NoNewline }
Write-Host "):"
Write-Host "  · SideStore > Sources > + > $base/sidestore.json  (una vez; después la app aparece con cada versión nueva)"
Write-Host "  · o Safari > $base/iPadBridge.ipa > Descargar > Archivos > compartir con SideStore"
Write-Host "  Sin red entre el iPad y la PC: bajá el IPA del Release en GitHub (Safari) y abrilo con SideStore."
