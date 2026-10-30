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
   sola al conectarse el primer visor y se detiene con el último. http://localhost/ muestra el estado, la calidad
   actual y lo que mide el iPad. En la página, el HUD de arriba a la derecha muestra fps y latencias (ver "Medición")
   y tocarlo cambia el preset de calidad: automático → mejor para dibujar → mejor para movimiento.
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
- `tools/color_check.py`: mide ΔE entre la captura cruda y un frame decodificado (para evaluar fidelidad de color);
  `tools/color_pattern.py` muestra un patrón estático (degradados, parches, texto, trama de 1 px) para medirlo.
- `tools/stream_probe.py`: visor de medición sin iPad (fps, keyframes, Mbps, tiempo hasta la primera imagen, RTT,
  need-key, `--dump` del flujo, `--sick` para simular un visor que sufre). `tools/motion_test.py`: ventana con
  movimiento determinista. `tools/latency_clock.py` + `tools/latency_measure.py`: reloj en pantalla y lectura de ese
  reloj en los frames decodificados, para medir captura → salida del encoder.
- `winput.py`: inyección de input mapeada al monitor virtual si existe: mouse (SendInput, DPI-aware) para los dedos,
  lápiz virtual (pointer injection PT_PEN: presión, tilt, botón lateral, hover) para el Pencil, y teclas: `tap_keys`
  (pulsación de un atajo) y `hold_key`/`release_keys` (modificador mantenido, para la barra de teclas).
- `static/pc.html`: página de estado (http://localhost/): captura, visores, fps y Mbps.
- `static/ipad.html`: decodificador WebCodecs + Pencil/toques. `static/setup.html`: guía del iPad.
- `app/iPadBridge.swiftpm`: app nativa (AVSampleBufferDisplayLayer + Network). `usb_bridge.py`: su puente.
- `certs/`: CA propia y certificado del servidor para 192.168.1.15. Si cambia la IP, reemitir `server.crt`.
- `tools/fake_app.py`: simula la app nativa en la PC para probar el puente sin iPad.

Protocolo visores: WebSocket, JSON `vconfig` (hvcC en base64, codec `hvc1.…`, `width`/`height` codificados: pueden
ser menores que el monitor si la calidad adaptativa escaló), JSON `still-clear`, binario u8 0|1 (delta|key) + f64 ts +
muestra, o u8 2 + PNG (imagen fija). `ts` es el reloj del servidor en ms de época (`now_ms()`: perf_counter anclado a
`time.time()`) tomado cuando la muestra sale del encoder.
Medición (todo aditivo, un visor viejo lo ignora): el visor manda `{"type":"ping","t":su reloj,"q":cola de
decodificación,"d":descartes desde el último ping,"rtt":último RTT}` cada 2 s y el servidor contesta
`{"type":"pong","t":el mismo,"mt":reloj del servidor,"inp50","inp95":latencia de input p50/p95 en ms,"br","scale",
"fps","mode","level"}`; el visor manda `{"type":"stats",fps,pfps,mbps,e2e50,e2e95,pres50,pres95,rtt,q,drops,transport,
mode}` cada 5 s (va al log del servidor y a pc.html), `{"type":"quality","mode":"auto|draw|motion"}` para el preset y
`{"type":"need-key"}` para pedir un IDR. Cada `input` lleva `t` = reloj del servidor estimado por el visor.
Protocolo app nativa: TCP, u32 largo + u8 tipo + payload (0 ping, 1 video, 2 config = u8 códec 1 avcC/2 hvcC + record,
3 imagen fija PNG, 4 still-clear, 16 input JSON, 17 need-key, 18 JSON de control iPad→PC: ping/stats/quality tal cual,
19 JSON de control PC→iPad: pong).
Input JSON (igual por WebSocket, con `"type":"input"`): dedos `{"ev":"move|down|up|scroll","x","y","btn","dy","dx"}`;
Pencil con `"pen":1`: `{"ev":"hover|down|up","x","y","p":0..1,"tx","ty":grados,"btn":2 = botón lateral}`,
`{"ev":"moves","pts":[[x,y,p,tx,ty],...]}`, `{"ev":"leave"}`, `{"ev":"eraser","on":bool}`.
Barra de teclas (sin `"pen"`, se procesan aunque el Pencil esté en contacto): `{"ev":"key","keys":"ctrl+z"}` pulsa
un atajo (`tap_keys`: modificadores ctrl/shift/alt/win + letra, F1-F12, `[`, `]`, esc, tab, space, enter...);
`{"ev":"mod","key":"shift|ctrl|alt|space|win","down":true|false}` mantiene esa tecla presionada hasta el `down:false`
(el cliente lo manda al soltar el botón; el servidor suelta todo al desconectarse el visor).

## Medición: cómo leer el HUD

El HUD de `ipad.html` (arriba a la derecha) dice, por ejemplo:
`60 fps (59 pres) · e2e 24/31 pres 29/38 · in 4/7 · rtt 3 · cola 0 · desc 0 · 48.2 Mbps · 100%/50M auto`

- `60 fps (59 pres)`: frames decodificados por segundo y frames que llegaron a presentarse (uno por refresco; si hay
  más decodificados que presentados, el iPad va más lento que el flujo).
- `e2e 24/31`: latencia desde que la muestra salió del encoder de la PC hasta que el decodificador del iPad la entregó,
  p50/p95 en ms de los últimos 5 s. `pres 29/38`: lo mismo pero medido al presentar (en el `requestAnimationFrame`
  posterior al dibujo: lo más cerca del vidrio que permite Safari). A eso hay que sumarle lo que ddagrab + NVENC tardan
  antes del `ts`, que no se ve desde el iPad: medido con `tools/latency_clock.py` (ver más abajo).
- `in 4/7`: latencia de input (del Pencil o el dedo hasta que Windows lo inyecta) p50/p95; la mide el servidor con el
  `t` que estampa el iPad en cada evento usando el reloj sincronizado, y la devuelve en el pong.
- `rtt 3`: ida y vuelta del ping en ms. `cola`: muestras esperando en el decodificador. `desc`: muestras descartadas
  desde que se abrió la página (cola > 6, o deltas sin keyframe previo).
- `48.2 Mbps`: lo que está llegando. `100%/50M auto`: escala y bitrate que el servidor está usando y el preset
  (`n1`, `n2`… si la calidad adaptativa bajó de nivel). Tocar el HUD cambia el preset.

Reloj sincronizado (como OpenDisplay): el ping lleva el reloj del iPad, el pong devuelve ese valor y el del servidor;
offset = servidor − (iPad + RTT/2) de la muestra con menor RTT entre las últimas 15 (RTT inválidos descartados).
Con eso cada frame (`ts` del servidor) y cada evento de input se comparan en el mismo reloj.

Medido en esta PC (RTX 4060, monitor 3840x2160 a 60 Hz, sin iPad; `tools/latency_clock.py` dibuja el reloj en una
ventana, `tools/latency_measure.py` lo lee en los frames decodificados): desde que la ventana dibuja hasta que la muestra
sale del encoder, p50 38 ms, p95 58 ms, mínimo 23 ms (dos corridas: 38,9/60,1 y 38,3/57,1). Incluye la composición de
DWM, la espera de ddagrab a 60 fps y NVENC. Con el `-delay` por defecto de ffmpeg (NVENC retiene frames en su cola
asíncrona) era p50 60 ms, p95 75; por eso `NVENC_DELAY=0` es el predeterminado (`NVENC_DELAY=` vacío deja el de
ffmpeg). La latencia total hasta el vidrio del iPad es ese valor más el `pres` del HUD; con el iPad la mide Demian.
`stats` cada 5 s queda en el log del servidor (`stats 192.168.1.63: fps=60 ... e2e50=24 ...`) y en pc.html, para
diagnosticar Wi-Fi sin estar al lado del iPad.

## Keyframes y calidad adaptativa

- `KEYFRAMES=refresh` (predeterminado): un solo IDR al arrancar y después intra-refresh de NVENC (`-intra-refresh 1`,
  GOP de `GOP_S` segundos, 10 por defecto): cada frame lleva una tira de bloques intra en vez de un keyframe entero por
  segundo. Sin pulso de bitrate ni de calidad. Un visor nuevo (o uno que perdió el hilo) manda `need-key` y el servidor
  reinicia el encoder para emitir un IDR, conservando la salida DXGI ya detectada: ~0,3 s hasta la imagen nueva
  (antes, esperar al próximo keyframe: hasta 1 s). Los visores que ya estaban ven una congelación de ese tiempo.
  `KEYFRAMES=idr` vuelve al comportamiento anterior (IDR cada segundo, `need-key` solo espera).
  Medido (monitor 3840x2160 a 60 Hz, CBR 50 Mbps, visor `tools/stream_probe.py` por localhost; 30 de octubre de 2026):

  | | IDR cada 1 s (`KEYFRAMES=idr`) | intra-refresh GOP 10 s | intra-refresh GOP 4 s |
  |---|---|---|---|
  | Mbps en reposo (patrón estático) | 5,1 (un IDR de ~300-500 KB por segundo) | 0,2 | 0,2 |
  | Mbps en movimiento (`tools/motion_test.py`) | 15,6 | 13,3 | 11,0 |
  | need-key hasta el IDR nuevo | 0,52 s (espera al próximo; hasta 1 s) | 0,30 s (reinicio) | 0,34 s (reinicio) |
  | Primer visor, hasta la primera imagen | 0,96 s | 0,97 s | 0,97 s |
  | ΔE medio / p95 vs. captura cruda, frame IDR | 1,21 / 4,7 | 1,23 / 4,7 | 1,23 / 4,8 |
  | ΔE medio / p95, frames P (30…600) | 1,03 / 3,4 | 1,03 / 3,4 | 1,00-1,03 / 3,4 |

  La calidad estática es la misma en los tres (el 4:2:0 manda); el primer IDR es un poco peor que los P que lo
  siguen, y con IDR por segundo ese pulso vuelve cada segundo (en CBR los IDR siguientes ya salen con historia y no se
  notan en el ΔE, pero sí en el bitrate). Queda intra-refresh con GOP de 10 s: menos bits que con 4 s y sin diferencia
  de calidad. El tiempo hasta la primera imagen del primer visor lo domina el sondeo de la salida DXGI (~0,7 s) más el
  arranque de ffmpeg; los visores siguientes ven imagen a los ~0,3 s de pedir el keyframe.
- `ADAPTIVE=1` (predeterminado): el servidor mira lo que reportan los visores en cada ping/stats (cola ≥ 4, descartes,
  RTT 40 ms por encima de su mínimo, fps recibidos < 75 % de los capturados) y, si un visor sufre dos ticks seguidos
  (4 s), baja un nivel; como mucho cada 8 s; tras 30 s estables sube uno. Por USB solo cuenta la cola. Cada nivel es
  (escala, factor de bitrate sobre el del transporte, tope de fps): automático 100 %/1.0 → 100 %/0.6 → 75 %/0.45 →
  50 %/0.3; mejor para dibujar nunca baja la escala (100 %/1.0 → 100 %/0.7 → 100 %/0.5 a 30 fps → 100 %/0.35 a 30 fps);
  mejor para movimiento nunca baja los fps (100 %/1.0 → 75 %/0.6 → 50 %/0.35 → 50 %/0.25). Cada cambio reinicia ffmpeg
  (~0,3 s de congelación). `ADAPTIVE=0` lo apaga (queda el preset manual y el bitrate por transporte).
  Probado con `tools/stream_probe.py --sick=4` (un visor que reporta cola 5 y descartes de los 4 a los 24 s): baja a
  nivel 1 a los 8 s, 2 a los 16, 3 a los 24 (3840x2160 → 2880x1620 → 1920x1080, 50 → 30 → 22 → 15 Mbps, siempre
  60 fps) y vuelve a nivel 2 a los 55 s, 30 s después de que el visor dejó de quejarse.
- Escala reducida: este ffmpeg (8.1, build de gyan.dev) no puede escalar sin salir de la GPU: `scale_d3d11` falla al
  crear la textura de salida y no hay mapeo D3D11 → CUDA (`hwmap` devuelve "no implementado"), así que el frame baja a
  RAM (`hwdownload`) y sube a CUDA (`hwupload_cuda,scale_cuda`). Medido: sostiene 60 fps a 2560x1440 igual que el
  pipeline directo, a costa de ~0,9 GB/s de PCIe y un hilo; por eso solo se usa cuando un visor por red sufre o con el
  preset de movimiento bajo carga.

## Por qué puertos 80 y 443

Safari en iPadOS convierte solo las direcciones http en https. Con puertos no estándar esa conversión cae en el
puerto sin TLS y falla incluso la página http. Con 80/443 aterriza en el 443, donde sí hay TLS.

## Límites

- Goma: Windows no permite emular el lado goma de un lápiz sintético, así que el doble toque manda teclas (E/B) en vez
  de cambiar el extremo del lápiz; si la ventana activa no es Photoshop, esas teclas van a lo que esté activo.
- Latencia: al trazo se le suma el camino captura -> NVENC -> USB -> decodificación -> pantalla (unos 2-4 frames a
  60 Hz), más que un Cintiq cableado. El input vuelve mucho más rápido que el video, así que el trazo aparece un poco
  después de la punta; Photoshop lo compensa con sus propios puntos, no con el video. Ahora se mide (sección
  "Medición"): el HUD da el tramo encoder → pantalla y la latencia de input; el tramo captura → encoder se mide con
  `tools/latency_clock.py`.
- Sin teclado completo desde el iPad: solo la barra de teclas (modificadores, deshacer/rehacer, [ ], B, E) y el
  doble toque del Pencil.
- La app tiene que estar en primer plano en el iPad; iOS la suspende en segundo plano.
- Keyframes: con intra-refresh no hay IDR periódicos; un visor nuevo pide uno y el encoder se reinicia (~0,3 s
  hasta la imagen), lo que congela ese instante a los demás visores. `KEYFRAMES=idr` si se prefiere el keyframe por
  segundo (sin reinicios, pero con el pulso de bitrate y hasta 1 s de espera).
- Color (medido con ΔE contra la captura cruda): el video HEVC 10b 4:2:0 tiene ΔE medio 0.9 y p95 3.0; la
  compresión casi no pesa, la pérdida es el 4:2:0 (el iPad no decodifica 4:4:4 en hardware). Por eso la imagen fija
  PNG: ΔE 0 cuando la pantalla está quieta. NVENC convierte con BT.601 rango de video y lo declara; iPadOS gestiona
  el color según esas etiquetas. El monitor virtual es sRGB: un JPG en P3 se recorta a sRGB en Windows.
