; Instalador de iPad Bridge (Inno Setup 6). Lo construye installer\build.ps1, que antes arma payload\ con el Python
; embebido y sus paquetes, ffmpeg, el driver del monitor virtual, nefcon y el código. Instala en Archivos de programa
; (pide administrador una vez: también instala el driver y la regla de firewall); con /CURRENTUSER instala por usuario y
; el driver se eleva solo. Los datos que cambian (certificados, config, logs) van a %LOCALAPPDATA%\iPad Bridge.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "iPad Bridge"

[Setup]
AppId={{8F1C2E7A-6B3D-4A9E-9C21-5D7F0B3E6A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Demian Szklarski
DefaultDirName={autopf}\iPad Bridge
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=iPadBridge-Setup-{#AppVersion}
SetupIconFile=payload\ipad-bridge.ico
UninstallDisplayIcon={app}\ipad-bridge.ico
UninstallDisplayName={#AppName}
; ffmpeg y el runtime pesan ~500 MB: lzma2/fast tarda poco y comprime bien lo que es comprimible
Compression=lzma2/fast
SolidCompression=yes
LZMAUseSeparateProcess=yes
WizardStyle=modern
CloseApplications=no
ShowLanguageDialog=no

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "startup"; Description: "Iniciar iPad Bridge con Windows (icono en la bandeja)"
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; Flags: unchecked
Name: "vdd"; Description: "Instalar el monitor virtual (Virtual Display Driver, firmado; pide administrador)"
Name: "placevdd"; Description: "Ubicar el monitor virtual a la izquierda del principal, a 120 Hz y escala 225 %"
Name: "appledevices"; Description: "Instalar ""Dispositivos Apple"" desde Microsoft Store (iPad por USB; usa winget)"
Name: "firewall"; Description: "Permitir los puertos 80 y 443 en redes privadas (firewall de Windows)"

[Files]
Source: "payload\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "scripts\stop-tray.ps1"; Flags: dontcopy

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\tray.py"""; WorkingDir: "{app}"; IconFilename: "{app}\ipad-bridge.ico"; Comment: "Servidor y puente del iPad en la bandeja"
Name: "{group}\Panel de estado de {#AppName}"; Filename: "http://localhost/pc.html"
Name: "{group}\Carpeta de datos y logs"; Filename: "{localappdata}\iPad Bridge"
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\tray.py"""; WorkingDir: "{app}"; IconFilename: "{app}\ipad-bridge.ico"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\tray.py"""; WorkingDir: "{app}"; IconFilename: "{app}\ipad-bridge.ico"; Tasks: startup

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\postinstall.ps1"" -App ""{app}"" -Firewall"; StatusMsg: "Regla de firewall para los puertos 80 y 443..."; Tasks: firewall; Flags: runhidden waituntilterminated
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\postinstall.ps1"" -App ""{app}"" -AppleDevices"; StatusMsg: "Instalando Dispositivos Apple (Microsoft Store)..."; Tasks: appledevices; Flags: runhidden waituntilterminated
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\postinstall.ps1"" -App ""{app}"" -Vdd"; StatusMsg: "Instalando el monitor virtual..."; Tasks: vdd; Flags: runhidden waituntilterminated
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\postinstall.ps1"" -App ""{app}"" -PlaceVdd"; StatusMsg: "Ubicando el monitor virtual..."; Tasks: placevdd; Flags: runhidden waituntilterminated
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\tray.py"""; WorkingDir: "{app}"; Description: "Iniciar {#AppName} ahora (icono en la bandeja)"; Flags: postinstall nowait skipifsilent runascurrentuser

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\stop-tray.ps1"" -App ""{app}"""; RunOnceId: "stoptray"; Flags: runhidden waituntilterminated
Filename: "netsh.exe"; Parameters: "advfirewall firewall delete rule name=""iPad Bridge"""; RunOnceId: "firewall"; Flags: runhidden waituntilterminated

[UninstallDelete]
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\tools\__pycache__"
Type: files; Name: "{app}\install.log"

[Code]
// Antes de copiar archivos: cerrar la bandeja, el servidor, el puente y ffmpeg de una instalación anterior.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  R: Integer;
begin
  Result := '';
  ExtractTemporaryFile('stop-tray.ps1');
  Exec('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{tmp}\stop-tray.ps1') + '" -App "' + ExpandConstant('{app}') + '"',
       '', SW_HIDE, ewWaitUntilTerminated, R);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  R: Integer;
begin
  if CurUninstallStep = usUninstall then begin
    if SuppressibleMsgBox('¿Quitar también el monitor virtual (driver Virtual Display Driver)?' + #13#10 +
                          'Si lo dejás, otra instalación de iPad Bridge lo reutiliza.', mbConfirmation, MB_YESNO, IDNO) = IDYES then
      Exec('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\scripts\uninstall-vdd.ps1') + '"',
           '', SW_HIDE, ewWaitUntilTerminated, R);
    if SuppressibleMsgBox('¿Borrar también los datos de ' + ExpandConstant('{localappdata}\iPad Bridge') + ' (certificados, configuración y logs)?' + #13#10 +
                          'Si los borrás, el iPad tendrá que instalar el certificado de nuevo.', mbConfirmation, MB_YESNO, IDNO) = IDYES then
      DelTree(ExpandConstant('{localappdata}\iPad Bridge'), True, True, True);
  end;
end;
