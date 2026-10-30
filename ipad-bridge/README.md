# iPad Bridge: el iPad como pantalla extendida de Windows con Apple Pencil

Sin Mac. Funciona siempre igual: Windows tiene un monitor virtual del tamaño del iPad (2732x2048 a 120 Hz), el
servidor lo captura directo de la GPU (ffmpeg ddagrab + NVENC HEVC 10 bits, sin navegador ni selector), lo manda
por USB o red y el iPad lo decodifica por hardware. Cuando la pantalla queda quieta 0.4 s, manda además el frame
exacto como PNG sin pérdida, que el iPad muestra encima del video hasta que algo se mueve: mirando una imagen
quieta se ven los píxeles exactos de Windows. El Pencil y los toques vuelven a la PC mapeados al monitor virtual.

## Uso diario

1. PC: `.\start.ps1` levanta el servidor (80/443) y el puente en modo `auto`: USB si el iPad está por cable
   (requiere la app "Dispositivos Apple" y haber tocado Confiar en el iPad), si no Wi-Fi; cambia solo.
   Bitrate automático: 100 Mbps por USB, 50 si algún visor va por red.
2. iPad: abrí https://192.168.1.15/ipad.html en Safari, o la app iPadBridge de Playgrounds. La captura arranca
   sola al conectarse el primer visor y se detiene con el último. http://localhost/ muestra el estado.
3. Pencil = lápiz de Windows (Windows Ink) con presión, inclinación, hover y botón lateral; Photoshop, Krita, Clip
   Studio (en modo Windows Ink) etc. lo ven como una tableta. Doble toque del Pencil = goma (tecla E, otro toque = B).
   Un dedo = mover cursor, tap = click. Dos dedos = scroll. Mientras el Pencil toca, los dedos se ignoran (palma).
   Mové ventanas al iPad arrastrándolas hacia la izquierda del monitor o con Win+Shift+Flecha izquierda.
4. Barra de teclas (las ExpressKeys de un Cintiq): tira vertical semitransparente en el borde izquierdo, igual en
   la app y en la página. Shift, Ctrl, Alt y Espacio se mantienen presionados mientras tocás el botón, con un dedo
   y sin soltar el Pencil (Shift = línea recta, Alt = cuentagotas, Espacio = mano). Debajo, pulsaciones: deshacer
   (Ctrl+Z), rehacer (Ctrl+Shift+Z), pincel más chico/grande ([ ]), B y E. Toque largo en ≡ la pasa al otro borde
   (se recuerda); el ojo tachado la oculta y deja una pestaña para volver a mostrarla. Las teclas van a la ventana
   activa de Windows. Si el visor se desconecta, el servidor suelta los modificadores que hubieran quedado presionados.

## Instalar en otra PC (Windows 11 + GPU NVIDIA)

1. Copiá la carpeta del proyecto (o descomprimí `ipad-bridge.zip`) en, por ejemplo, `C:\ipad-bridge`.
2. En PowerShell, dentro de esa carpeta: `powershell -ExecutionPolicy Bypass -File .\setup.ps1`.
   Instala Python, ffmpeg y "Dispositivos Apple" si faltan (winget), las librerías de Python, el monitor virtual
   (pide administrador una vez), genera los certificados para la IP de esa PC y ubica el monitor a la izquierda.
3. `.\start.ps1` (agregá la IP del iPad si querés respaldo por red). Windows pregunta por el firewall la primera
   vez: permitir en redes privadas.
4. En el iPad: `http://<IP de la PC>/` → instalar certificado y activar su confianza → app o página https.
   Por USB: conectar, tocar Confiar en el iPad y abrir la app Dispositivos Apple una vez.
Si la IP de la PC cambia, `start.ps1` reemite el certificado del servidor solo; el iPad no necesita nada nuevo.

## Primera vez

- `install-vdd.ps1` instala el monitor virtual (Virtual Display Driver, MIT, firmado por SignPath), con resoluciones
  del iPad en `C:\VirtualDisplayDriverdd_settings.xml`. Pide administrador.
- `python tools/place_vdd.py left|right [--hz=120]` ubica el monitor virtual y fija su refresco. Para 120 Hz primero
  `set-vdd-120.ps1` (admin) agrega el modo al driver. El servidor captura a los fps del refresco, con tope 60 (MAX_FPS):
  NVENC no sostiene 2732x2048 HEVC 10b a 120 fps con movimiento real y el video se traba.
- iPad: abrí http://192.168.1.15/ y seguí los pasos: instalar el certificado (perfil) y activar su confianza en
  Ajustes > General > Información > Ajustes de confianza de certificados. WebCodecs solo existe en https.
- App nativa (opcional, para cable): desde esa misma página bajá iPadBridge.swiftpm.zip, descomprimilo en Archivos
  y abrilo con Swift Playgrounds. Escucha TCP en 7777; `usb_bridge.py` la conecta al servidor por IP o por USB
  (USB requiere la app "Dispositivos Apple" de Microsoft Store).

## Pencil como tableta (lápiz virtual)

El servidor crea un lápiz sintético con `CreateSyntheticPointerDevice(PT_PEN)` e inyecta cada evento del Pencil con
`InjectSyntheticPointerInput` (Windows 10 1809+, sin driver ni administrador). Windows lo entrega a las apps como
WM_POINTER de lápiz con presión (0..1024), inclinación X/Y y botón lateral, y genera el mouse equivalente para las apps
sin soporte de lápiz (medido con una ventana de prueba: presión y tilt llegan; el contacto produce clic izquierdo marcado
como tableta y el botón lateral clic derecho). Lo que manda el iPad: la trayectoria completa del Pencil (toques
coalescidos, hasta 240 Hz, no solo el último de cada frame), presión 0..1, altitud/azimut convertidos a tiltX/tiltY en
grados como los define Windows, hover si el iPad detecta el Pencil en el aire (iPad Pro M2 o más nuevo: el cursor del
pincel sigue al lápiz sin tocar), `leave` cuando se aleja, y la goma del doble toque.

- `PEN_GAMMA` (0.8): curva de presión, salida = entrada^gamma. Menos de 1 responde más con poca fuerza (el Pencil pide
  más fuerza que un Wacom para la misma presión); 1 = lineal. Equivale a la curva "suave/firme" del driver de Wacom.
- `PEN_MIN` (0.02): presión mínima mientras hay contacto (umbral de activación), para que el primer punto pinte.
- `PEN_TAP_KEYS` ("e,b"): atajos del doble toque del Pencil, "activar goma,volver". Windows no deja emular el lado goma
  de un lápiz sintético (las banderas INVERTED/ERASER no llegan a la app, medido), por eso va por teclado a la ventana activa.
- Photoshop: usa Windows Ink de fábrica; si alguna vez se forzó WinTab, en PSUserConfig.txt debe decir `UseSystemStylus 1`.
- Windows > Ajustes > Lápiz y Windows Ink: apagar "Mantener presionado para clic derecho" si el inicio del trazo se
  siente retrasado, y las animaciones visuales del lápiz (el dispositivo sintético ya pide `POINTER_FEEDBACK_NONE`).
- Si Windows no tiene pointer injection, el Pencil vuelve a comportarse como mouse izquierdo (sin presión).

## Archivos

- `server.py`: captura el monitor virtual (ffmpeg ddagrab -> hevc_nvenc Main10, Annex B -> muestras con largo de
  4 bytes + hvcC), detector de pantalla quieta (segundo ddagrab a 30 fps comparando bytes) que manda PNG, reparte
  todo a los visores por WebSocket, sirve las páginas por http/https y aplica el input. Requiere ffmpeg (build "full"
  de gyan.dev, instalado con winget), GPU NVIDIA y Pillow; `FFMPEG=ruta` para otro binario.
- `hevc.py`: parser mínimo de HEVC (tipos de NAL, SPS) y armado del hvcC y del codec string.
- `tools/color_check.py`: mide ΔE entre la captura cruda y un frame decodificado (para evaluar fidelidad de color).
- `winput.py`: inyección de input mapeada al monitor virtual si existe: mouse (SendInput, DPI-aware) para los dedos,
  lápiz virtual (pointer injection PT_PEN: presión, tilt, botón lateral, hover) para el Pencil, y teclas: `tap_keys`
  (pulsación de un atajo) y `hold_key`/`release_keys` (modificador mantenido, para la barra de teclas).
- `static/pc.html`: página de estado (http://localhost/): captura, visores, fps y Mbps.
- `static/ipad.html`: decodificador WebCodecs + Pencil/toques. `static/setup.html`: guía del iPad.
- `app/iPadBridge.swiftpm`: app nativa (AVSampleBufferDisplayLayer + Network). `usb_bridge.py`: su puente.
- `certs/`: CA propia y certificado del servidor para 192.168.1.15. Si cambia la IP, reemitir `server.crt`.
- `tools/fake_app.py`: simula la app nativa en la PC para probar el puente sin iPad.

Protocolo visores: WebSocket, JSON `vconfig` (hvcC en base64, codec `hvc1.…`), JSON `still-clear`, binario
u8 0|1 (delta|key) + f64 ts + muestra, o u8 2 + PNG (imagen fija).
Protocolo app nativa: TCP, u32 largo + u8 tipo + payload (0 ping, 1 video, 2 config = u8 códec 1 avcC/2 hvcC + record,
3 imagen fija PNG, 4 still-clear, 16 input JSON, 17 need-key).
Input JSON (igual por WebSocket, con `"type":"input"`): dedos `{"ev":"move|down|up|scroll","x","y","btn","dy","dx"}`;
Pencil con `"pen":1`: `{"ev":"hover|down|up","x","y","p":0..1,"tx","ty":grados,"btn":2 = botón lateral}`,
`{"ev":"moves","pts":[[x,y,p,tx,ty],...]}`, `{"ev":"leave"}`, `{"ev":"eraser","on":bool}`.
Barra de teclas (sin `"pen"`, se procesan aunque el Pencil esté en contacto): `{"ev":"key","keys":"ctrl+z"}` pulsa
un atajo (`tap_keys`: modificadores ctrl/shift/alt/win + letra, F1-F12, `[`, `]`, esc, tab, space, enter...);
`{"ev":"mod","key":"shift|ctrl|alt|space|win","down":true|false}` mantiene esa tecla presionada hasta el `down:false`
(el cliente lo manda al soltar el botón; el servidor suelta todo al desconectarse el visor).

## Por qué puertos 80 y 443

Safari en iPadOS convierte solo las direcciones http en https. Con puertos no estándar esa conversión cae en el
puerto sin TLS y falla incluso la página http. Con 80/443 aterriza en el 443, donde sí hay TLS.

## Límites

- Goma: Windows no permite emular el lado goma de un lápiz sintético, así que el doble toque manda teclas (E/B) en vez
  de cambiar el extremo del lápiz; si la ventana activa no es Photoshop, esas teclas van a lo que esté activo.
- Latencia: al trazo se le suma el camino captura -> NVENC -> USB -> decodificación -> pantalla (unos 2-4 frames a
  60 Hz), más que un Cintiq cableado. El input vuelve mucho más rápido que el video, así que el trazo aparece un poco
  después de la punta; Photoshop lo compensa con sus propios puntos, no con el video.
- Sin teclado completo desde el iPad: solo la barra de teclas (modificadores, deshacer/rehacer, [ ], B, E) y el
  doble toque del Pencil.
- La app tiene que estar en primer plano en el iPad; iOS la suspende en segundo plano.
- Keyframe cada segundo: un visor nuevo tarda hasta 1 s en ver imagen.
- Color (medido con ΔE contra la captura cruda): el video HEVC 10b 4:2:0 tiene ΔE medio 0.9 y p95 3.0; la
  compresión casi no pesa, la pérdida es el 4:2:0 (el iPad no decodifica 4:4:4 en hardware). Por eso la imagen fija
  PNG: ΔE 0 cuando la pantalla está quieta. NVENC convierte con BT.601 rango de video y lo declara; iPadOS gestiona
  el color según esas etiquetas. El monitor virtual es sRGB: un JPG en P3 se recorta a sRGB en Windows.
