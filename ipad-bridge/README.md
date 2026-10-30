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
   Studio (en modo Windows Ink) etc. lo ven como una tableta. Doble toque del Pencil (solo en la app) = goma (tecla E,
   otro toque = B). Mientras el Pencil toca, una línea fina sigue a la punta hasta que el video la alcanza
   (previsualización local, se apaga o se cambia de color en el panel ⚙).
   Dedos (página web; configurables en `static/shortcuts.json`): un dedo mueve el cursor, tap = clic, doble tap =
   doble clic; dos dedos = scroll; tap de dos dedos = deshacer, de tres = rehacer. Dedos apoyados **antes** de que
   toque el Pencil, lejos de la punta, son un gesto mientras duren: uno = goma (E al tocar el Pencil, B al levantar
   el dedo), dos = el Pencil hace de botón medio (mover la vista), tres = botón derecho. Los dedos que llegan después
   del Pencil o a menos de 180 px de donde cae se toman como palma y se ignoran.
   Mové ventanas al iPad arrastrándolas hacia la izquierda del monitor o con Win+Shift+Flecha izquierda.
4. Barra de teclas (las ExpressKeys de un Cintiq): tira vertical semitransparente en el borde izquierdo. En la página
   web cambia sola según la aplicación activa en Windows (perfiles Photoshop, Krita, Clip Studio, Blender y genérico
   en `static/shortcuts.json`; la etiqueta de arriba muestra el perfil y tocándola se elige a mano). Shift, Ctrl, Alt
   y Espacio se mantienen presionados mientras tocás el botón, con un dedo y sin soltar el Pencil (Shift = línea
   recta, Alt = cuentagotas, Espacio = mano). Debajo, pulsaciones (deshacer, rehacer, [ ], etc.), botones que alternan
   dos atajos (E/B) y botones derecho y medio del mouse (mantenidos, el Pencil actúa como ese botón; tocados solos,
   clic donde está el cursor). Abajo, fijos: ⌨ teclado en pantalla (también reenvía un teclado físico conectado al
   iPad), ⚙ panel de presión, previsualización, gestos y perfil, ✕ ocultar (queda una pestaña para volver). Toque
   largo en ≡ la pasa al otro borde (se recuerda). Las teclas van a la ventana activa de Windows. Si el visor se
   desconecta, el servidor suelta los modificadores que hubieran quedado presionados. La app nativa conserva la barra
   fija de siempre (modificadores, deshacer, rehacer, [ ], B, E).

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

- Panel ⚙ de la página (se guarda en el iPad y se manda al servidor como `pencfg`, se aplica sin reiniciar): presets
  suave (gamma 0.6), lineal (1) y firme (1.6), gamma fino, presión mínima y suavizado, con la presión en vivo (la que
  manda el iPad y la que llega a Windows) y la curva dibujada. Mientras se dibuja, el HUD muestra `pen 0.42→0.50`.
- `PEN_GAMMA` (0.8): curva de presión inicial, salida = entrada^gamma. Menos de 1 responde más con poca fuerza (el
  Pencil pide más fuerza que un Wacom para la misma presión); 1 = lineal. Equivale a la curva "suave/firme" del driver
  de Wacom. El panel del iPad la reemplaza al conectarse.
- `PEN_MIN` (0.02): presión mínima mientras hay contacto (umbral de activación), para que el primer punto pinte.
- `PEN_SMOOTH` (0): suavizado 0..1 de posición y presión con un filtro 1€ (corte de 12 Hz en reposo con 0.05, 0.6 Hz
  con 1; se abre con la velocidad, así los trazos rápidos no se retrasan). 0 = apagado. El filtro arranca en cada
  trazo desde el punto real y levanta donde quedó la posición filtrada. Con valores altos se nota el retraso en los
  trazos lentos; probar entre 0.2 y 0.5.
- Previsualización local del trazo (página web): el input llega a la PC antes de que vuelva el video, así que el iPad
  dibuja una línea fina (color, grosor y duración en el panel; 70 ms por defecto, unos 4 frames) sobre el video
  siguiendo al Pencil, con los puntos predichos de Safari (`getPredictedEvents`) más tenues; cada tramo se desvanece
  con su edad y al levantar el lápiz o cambiar de herramienta no queda nada.
- `PEN_TAP_KEYS` ("e,b"): atajos del doble toque del Pencil, "activar goma,volver". Windows no deja emular el lado goma
  de un lápiz sintético (las banderas INVERTED/ERASER no llegan a la app, medido), por eso va por teclado a la ventana activa.
- Photoshop: usa Windows Ink de fábrica; si alguna vez se forzó WinTab, en PSUserConfig.txt debe decir `UseSystemStylus 1`.
- Windows > Ajustes > Lápiz y Windows Ink: apagar "Mantener presionado para clic derecho" si el inicio del trazo se
  siente retrasado, y las animaciones visuales del lápiz (el dispositivo sintético ya pide `POINTER_FEEDBACK_NONE`).
- Si Windows no tiene pointer injection, el Pencil vuelve a comportarse como mouse izquierdo (sin presión).

## Barra de atajos por aplicación, gestos y teclado

`static/shortcuts.json` define los perfiles de la barra y los gestos; se edita a mano y se recarga la página. Cada
perfil tiene `id`, `name`, `short` (etiqueta de la barra), `match` (ejecutables de Windows, sin distinguir mayúsculas;
el primer perfil es el de respaldo) y `buttons`. Tipos de botón: `key` (pulsa `keys`), `mod` (mantiene `key` mientras
se toca), `mouse` (`btn` 1 = medio, 2 = derecho), `toggle` (alterna `keys[0]` y `keys[1]`, iluminado = el primero
activo, `labels` opcionales), `sep`. Nombres de teclas: letras, dígitos, signos (`{`, `+`: el servidor agrega shift o
AltGr según el teclado de Windows), f1-f24, esc, tab, space, enter, backspace, delete, insert, home, end, pageup,
pagedown, left/right/up/down, num0-num9, num+ num- num* num/ num., y ctrl/shift/alt/win como modificadores.
Más de 14 botones no entran en la pantalla del iPad.

El servidor mira la ventana activa cada 0.5 s (`GetForegroundWindow` + nombre del ejecutable) y manda
`{"type":"app","exe":"Photoshop.exe","title":"…"}` a los visores cuando cambia (y al conectarse). La página cambia de
perfil sola; tocar la etiqueta del perfil lo fija a mano hasta el próximo cambio de aplicación. La app nativa no
recibe este mensaje por ahora (el puente USB no lo reenvía) y conserva su barra fija.

Gestos (`gestures` en el JSON, los del perfil se mezclan con los generales): `tapMs` 250, `doubleMs` 300, `tapPx` 10,
`palmRadius` 180 (dedos a menos de esos px CSS de donde cae el Pencil son palma; 0 = no distinguir; también en el
panel), `palmSize` 45 (contacto más grande que eso = palma, si Safari informa el tamaño). `tap1` clic, `tap2`/`tap3`
toques de dos y tres dedos (acción `key`), `hold1`/`hold2`/`hold3` dedos apoyados antes del Pencil: `toggle`
(`keys[0]` cuando toca el Pencil, `keys[1]` cuando se levanta el dedo; si el Pencil sigue abajo, al levantarlo),
`mod` (modificador mantenido mientras dure el dedo) o `mouse` (el Pencil hace de ese botón). Mientras un gesto dura,
sus dedos no mueven el cursor ni hacen scroll. El pellizco (zoom) queda para el modo espejo, más adelante.

Teclado: el botón ⌨ enfoca un campo oculto; el iPad muestra su teclado en pantalla y un teclado físico conectado
escribe en él. Letras y signos van como texto (`{"ev":"text"}`, el servidor los escribe con `KEYEVENTF_UNICODE`, así
no dependen de la distribución de Windows ni de Bloq Mayús); Intro, Tab, Esc, flechas, Supr, Inicio/Fin, Re/Av Pág,
F1-F12 y cualquier tecla con Ctrl/Alt/Cmd van como atajo (`{"ev":"key"}`, Cmd = Win). Un cartel abajo avisa que el
teclado está activo; ⌨ de nuevo lo cierra.

Sin iPad: `python tools/pen_probe.py` abre una ventana en el monitor objetivo que muestra lo que Windows entrega por
WM_POINTER (presión 0..1024, inclinación, banderas), los botones del mouse, la rueda y las teclas que llegan, y dibuja
los trazos con grosor según la presión. `ipad.html?pen=mouse` en un navegador de PC hace que el mouse actúe como
Pencil (presión 0.5) para probar la previsualización y el panel.

## Archivos

- `server.py`: captura el monitor virtual (ffmpeg ddagrab -> hevc_nvenc Main10, Annex B -> muestras con largo de
  4 bytes + hvcC), detector de pantalla quieta (segundo ddagrab a 30 fps comparando bytes) que manda PNG, reparte
  todo a los visores por WebSocket, sirve las páginas por http/https y aplica el input. Requiere ffmpeg (build "full"
  de gyan.dev, instalado con winget), GPU NVIDIA y Pillow; `FFMPEG=ruta` para otro binario.
- `hevc.py`: parser mínimo de HEVC (tipos de NAL, SPS) y armado del hvcC y del codec string.
- `tools/color_check.py`: mide ΔE entre la captura cruda y un frame decodificado (para evaluar fidelidad de color).
- `winput.py`: inyección de input mapeada al monitor virtual si existe: mouse (SendInput, DPI-aware) para los dedos,
  lápiz virtual (pointer injection PT_PEN: presión, tilt, botón lateral, hover) para el Pencil con curva, umbral y
  filtro 1€ configurables en caliente (`Pen.configure`), teclas: `tap_keys` (pulsación de un atajo; agrega shift/AltGr
  si el carácter lo pide), `hold_key`/`release_keys` (modificador mantenido, para la barra de teclas), `type_text`
  (texto Unicode), y `foreground_app()` (ejecutable y título de la ventana activa, para la barra por aplicación).
- `static/pc.html`: página de estado (http://localhost/): captura, visores, fps y Mbps.
- `static/ipad.html`: decodificador WebCodecs + Pencil/toques, previsualización del trazo, gestos, barra por
  aplicación, panel de presión y teclado. `static/shortcuts.json`: perfiles de la barra y gestos.
  `static/setup.html`: guía del iPad.
- `app/iPadBridge.swiftpm`: app nativa (AVSampleBufferDisplayLayer + Network). `usb_bridge.py`: su puente.
- `certs/`: CA propia y certificado del servidor para 192.168.1.15. Si cambia la IP, reemitir `server.crt`.
- `tools/fake_app.py`: simula la app nativa en la PC para probar el puente sin iPad.
- `tools/pen_probe.py`: ventana que muestra el lápiz (WM_POINTER), botones, rueda y teclas que llegan a Windows.

Protocolo visores: WebSocket, JSON `vconfig` (hvcC en base64, codec `hvc1.…`), JSON `still-clear`, binario
u8 0|1 (delta|key) + f64 ts + muestra, o u8 2 + PNG (imagen fija), JSON `app` (`exe`, `title` de la ventana activa
de Windows, al conectarse y al cambiar).
Protocolo app nativa: TCP, u32 largo + u8 tipo + payload (0 ping, 1 video, 2 config = u8 códec 1 avcC/2 hvcC + record,
3 imagen fija PNG, 4 still-clear, 16 input JSON, 17 need-key).
Input JSON (igual por WebSocket, con `"type":"input"`): dedos `{"ev":"move|down|up|scroll","x","y","btn","dy","dx"}`
(`btn` 0 izquierdo, 1 medio, 2 derecho; `down`/`up` sin `x`,`y` = en la posición actual del cursor);
Pencil con `"pen":1`: `{"ev":"hover|down|up","x","y","p":0..1,"tx","ty":grados,"btn":2 = botón lateral}`,
`{"ev":"moves","pts":[[x,y,p,tx,ty],...]}`, `{"ev":"leave"}`, `{"ev":"eraser","on":bool}`,
`{"ev":"pencfg","gamma","min","smooth"}` (curva, umbral y suavizado 0..1; se aplica en caliente). Cuando un gesto o
la barra hacen que el Pencil actúe como botón del mouse, el cliente manda eventos de dedos (`down`/`move`/`up` con
`btn` 1 o 2) en vez de eventos `pen`.
Barra de teclas (sin `"pen"`, se procesan aunque el Pencil esté en contacto): `{"ev":"key","keys":"ctrl+z"}` pulsa
un atajo (`tap_keys`: modificadores ctrl/shift/alt/win + letra, F1-F12, `[`, `]`, esc, tab, space, enter...);
`{"ev":"mod","key":"shift|ctrl|alt|space|win","down":true|false}` mantiene esa tecla presionada hasta el `down:false`
(el cliente lo manda al soltar el botón; el servidor suelta todo al desconectarse el visor);
`{"ev":"text","text":"hola"}` escribe texto tal cual (teclado del iPad). Un servidor viejo ignora `pencfg` y `text`;
un cliente viejo o la app nativa siguen funcionando igual con el servidor nuevo.

## Por qué puertos 80 y 443

Safari en iPadOS convierte solo las direcciones http en https. Con puertos no estándar esa conversión cae en el
puerto sin TLS y falla incluso la página http. Con 80/443 aterriza en el 443, donde sí hay TLS.

## Límites

- Goma: Windows no permite emular el lado goma de un lápiz sintético, así que el doble toque y el gesto de un dedo
  mandan teclas (E/B, por perfil en `shortcuts.json`) en vez de cambiar el extremo del lápiz; van a la ventana activa.
- Palma: los dedos que llegan después del Pencil o cerca de su punta se ignoran; iPadOS además cancela los que
  reconoce como palma. Una palma que se apoya antes del Pencil y lejos de donde va a caer puede mover el cursor un
  instante o contar como un dedo del gesto; si molesta, subir `palmRadius` o apagar los gestos en el panel.
- Latencia: al trazo se le suma el camino captura -> NVENC -> USB -> decodificación -> pantalla (unos 2-4 frames a
  60 Hz), más que un Cintiq cableado. El input vuelve mucho más rápido que el video, así que el trazo aparece un poco
  después de la punta; Photoshop lo compensa con sus propios puntos, no con el video.
- Teclado: el campo oculto recibe lo que el iPad decide mandar; la autocorrección está apagada pero algunos atajos
  del sistema (Cmd+H, Cmd+Tab) no llegan a Safari. La app nativa no tiene teclado ni gestos nuevos todavía.
- La app tiene que estar en primer plano en el iPad; iOS la suspende en segundo plano.
- Keyframe cada segundo: un visor nuevo tarda hasta 1 s en ver imagen.
- Color (medido con ΔE contra la captura cruda): el video HEVC 10b 4:2:0 tiene ΔE medio 0.9 y p95 3.0; la
  compresión casi no pesa, la pérdida es el 4:2:0 (el iPad no decodifica 4:4:4 en hardware). Por eso la imagen fija
  PNG: ΔE 0 cuando la pantalla está quieta. NVENC convierte con BT.601 rango de video y lo declara; iPadOS gestiona
  el color según esas etiquetas. El monitor virtual es sRGB: un JPG en P3 se recorta a sRGB en Windows.
