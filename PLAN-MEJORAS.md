# iPad Bridge: contraste con Duet Display, Astropad Studio y OpenDisplay, y plan de mejoras

Fecha: 30 de octubre de 2026. Base analizada: `ipad-bridge/` (server.py, winput.py, static/ipad.html, usb_bridge.py, app
Playgrounds), más los sitios oficiales, la documentación de soporte, los instaladores de Windows descargados y verificados
(Duet 4.0.511, Astropad Studio 5.5.3.5) y el código fuente de OpenDisplay (sender Mac oficial 1.30.1 y dos senders
Windows no oficiales).

## 1. Resumen ejecutivo

**Dónde estamos bien.** En calidad de imagen y en el canal de video nadie de los tres nos supera en Windows: HEVC 10 bits
a 100 Mbps por USB capturado directo de la GPU, 60 fps reales sobre un monitor virtual de 120 Hz, y la imagen fija PNG sin
pérdida (ΔE 0) cuando la pantalla está quieta. Astropad y OpenDisplay usan H.264 4:2:0 (Astropad: "segmentos" H.264;
OpenDisplay: 18 Mb/s máximo, HEVC solo entre Macs). El Pencil ya va como lápiz Windows Ink real con presión, inclinación,
hover, trayectoria coalescida a 240 Hz y botón lateral, que es exactamente lo que hace Astropad en Windows (Windows Ink
exclusivo) y más de lo que hace OpenDisplay oficial (Pencil solo desde la 1.15, sin Windows).

**Dónde nos ganan.** En todo lo que rodea al video: (1) la experiencia de uso en el iPad (barra de atajos por aplicación,
gestos de dedos configurables, curva de presión y suavizado editables desde el iPad, previsualización local del trazo,
teclado en pantalla); (2) la robustez de la conexión (descubrimiento automático, emparejamiento con QR o código, cambio
USB↔Wi-Fi sin cortar, reconexión al volver del fondo, calidad adaptativa); (3) la puesta en marcha (instalador único,
app en bandeja, sin certificados a mano, sin Playgrounds); (4) la goma real del Pencil: Astropad la resuelve con un driver
HID de kernel propio, nosotros con teclas; (5) la medición: OpenDisplay mide latencia extremo a extremo y de input con
sincronización de relojes, nosotros solo fps y Mbps.

**Qué no vale la pena copiar.** Cuenta obligatoria y suscripción (Duet 40–80 USD/año, Astropad 80–100 USD/año), acceso
remoto por Internet (Duet Air), Peer-to-Peer de Apple (solo Mac), QUIC para el cliente web (Safari no lo expone).

**Hallazgo clave de la inspección.** Astropad Studio para Windows trae dentro **el mismo Virtual Display Driver que usamos
nosotros** (MttVDD 11.30.4.434 de MikeTheTech, firmado) con un `vdd_settings.xml` casi idéntico, gestionado por un servicio
propio (`astro-display-service.exe`) que escribe en `C:\VirtualDisplayDriver\`. Eso valida nuestra elección de driver y
explica por qué no conviene instalar Astropad en esta misma PC: pisaría nuestra configuración de resoluciones y 120 Hz.

## 2. Ficha de cada competidor (lo público y lo que se ve por dentro)

### Duet Display 4.0.511 (Windows)

- **Producto:** pantalla extendida/espejo, tableta gráfica (Duet Pro), acceso remoto (Duet Air), teclado y mouse
  compartidos, "Cast & Control" del iPad en la PC. Windows 10+, macOS 11+, iPad/iPhone/Android/visionOS.
- **Pencil (Duet Pro):** presión, inclinación, hover, rechazo de palma, curva de presión personalizable y "Line Lead"
  (previsualización predictiva de la línea antes de que el video la muestre). Retina a 60 fps; no anuncian 120 Hz.
- **Precios (App Store, IAP):** Starter 3,99 USD/mes o 39,99/año; Air 5,99/mes o 49,99/año; Pro 7,99/mes o 79,99/año.
  Requiere cuenta Duet para usar la app.
- **Por dentro (instalador verificado, firmado por Duet, Inc.):** instalador propio "Kairos" (Qt6, acepta `/quiet`,
  `/passive`, `/norestart`) que embebe VC++ Redistributable 14.44 en bundles WiX y el payload de la app en un CAB que
  `expand.exe` no abre. Referencias a *AppleMobileDevice* (USB por usbmuxd vía la app "Dispositivos Apple", igual que
  nosotros) y un driver `DuetAOAP.inf` (Android Open Accessory, USB para Android). Otro proyecto que lo inspeccionó
  reporta un driver de pantalla IddCx/UMDF firmado, es decir la misma familia de driver que nuestro VDD.
- **Instalación silenciosa:** devuelve 1619 sin cuenta/UI; no se completó en esta PC.

### Astropad Studio 5.5.3.5 (Windows)

- **Producto:** iPad como tableta/pantalla para apps de escritorio. Modo espejo (con "Move & Zoom" para elegir monitor o
  acercar una zona) y, desde 5.5, modo extendido sin hardware (recomiendan USB). Windows 10 64 bits build 1809+, DirectX 11.
- **Pencil:** presión vía Windows Ink exclusivamente (sin WinTab; Photoshop CS6 queda fuera), inclinación, hover (iPad
  Pro 2022+ con tilt/azimut en hover), curva de presión suave/firme/custom con editor de puntos en el iPad, suavizado de
  presión ajustable, previsualización del trazo (stroke preview: largo y color), ocultar cursor al dibujar, Apple Pencil
  Pro: squeeze configurable y rotación del barril (giroscopio), doble toque con dos comandos alternados.
- **Gestos ("Magic Gestures", por app):** 1 dedo + Pencil = goma, 2 dedos + Pencil = botón medio u hover, 3 dedos +
  Pencil = botón derecho o atajo; 2 dedos tap = deshacer, 3 dedos tap = rehacer, 1 dedo tap = mantener modificador.
- **Sidebar:** atajos por aplicación con presets automáticos (Photoshop, Krita, Inkscape, Aseprite, Plasticity…),
  7 Quick Keys por app, modificadores en pantalla, teclado en pantalla, lanzar o cambiar de app desde la barra de tareas,
  Retina on/off, brillo y color, calidad de conexión.
- **Rendimiento:** "LIQUID", 60 fps sobre USB o Wi-Fi, "Adaptive Image Rendering" con tres modos (automático, mejor
  para dibujo, mejor para movimiento). Peer-to-Peer solo en Mac.
- **Precios:** 14,99 USD/mes o 79,99–99,99 USD/año (el sitio es inconsistente), 14 días de prueba, cuenta obligatoria.
- **Por dentro (MSI extraído con `/extract` y `msiexec /a`, firmado por Astro HQ):**
  - `Astropad Studio.exe` (194 MB, .NET/WPF autocontenido) + `liquid_ffi_server.dll` (25 MB, **motor en Rust**).
  - Captura con **DXGI Desktop Duplication** (crate `astro-monitor`), códec **H.264 por segmentos** (`liquid_codec`),
    transporte **QUIC con TLS (rustls)** por Wi-Fi, y por USB **usbmuxd** ("Apple Mobile Device service") con un socket
    TCP que simula UDP; descubrimiento Bonjour; preferencia `fps_limit` y conmutador "retina".
  - **`LiquidHidInput.sys`**: driver HID de kernel propio (KMDF, filtro inferior `vhf` = Virtual HID Framework). Expone un
    dispositivo "Astropad Tablet Device": el Pencil aparece como lápiz HID real (con goma/botones a nivel de sistema) y
    hay un **teclado HID virtual** (`keymap.hid.win.json`, códigos HID → teclas) para atajos y teclado en pantalla.
  - **`VirtualDisplayDriver\MttVDD.dll/.inf/.cat` + `vdd_settings.xml`**: el VDD de MikeTheTech, versión 11.30.4.434
    (24/12/2024), la misma que tenemos instalada (oem11.inf). `astro-display-service.exe` (servicio Windows con named
    pipe, crate `astro-edid`) lo gestiona: busca `ROOT\MTTVDD`, escribe `vdd_settings.xml` y `user_edid.bin` en
    `C:\VirtualDisplayDriver`.
  - El MSI "solo puede ejecutarse desde el bootstrapper" (Advanced Installer); la instalación silenciosa devolvió 1619.

### OpenDisplay (open source, GPL-3; sender oficial solo Mac)

- **Producto:** pantalla extendida real para Mac desde iPhone/iPad/Mac/Android, gratis, sin cuenta ni dongle, 6 000
  estrellas, un solo mantenedor. Linux en beta. **No hay sender Windows oficial.**
- **Pipeline Mac:** `CGVirtualDisplay` (API privada) + ScreenCaptureKit + VideoToolbox (H.264, HEVC si ambos lados lo
  tienen en hardware; tiempo real, sin B-frames, `MaxFrameDelayCount` 0, keyframes casi nunca periódicos: solo a pedido),
  18 Mb/s máximo, presets Best/Balanced/Fast (menos píxeles = menos latencia). Receiver iOS con
  `AVSampleBufferDisplayLayer` y un renderer Metal experimental (decodifica con `VTDecompressionSession`, cola
  "latest-wins", y mide cuándo el frame llegó al vidrio).
- **Protocolo (PROTOCOL.md, pv 3), lo más útil para nosotros:** `hello` con `panel` (píxeles, escala, puntos), `pencil`
  (fase, x/y, presión, azimut, altitud, rotación), `proximity`, `touch`/`scroll`, `kf` (pedir IDR), `stats` cada 5 s;
  `ping/pong` cada 2 s con **sincronización de reloj estilo NTP** (muestra de menor RTT) y **prefijo de telemetría**
  `{"cap","snd"}` en cada frame para medir latencia captura→pantalla e input; **canal lateral UDP para el cursor** (evita
  head-of-line blocking del TCP en Wi-Fi); `sleeping`/`closing`; `welcome`/`updateRequired` para versiones; liveness 5 s;
  "cable upgrade" automático de Wi-Fi a cable; rotación reconstruye la pantalla en vertical. Sin TLS ni autenticación
  todavía (en roadmap).
- **Senders Windows no oficiales (código leído):**
  - *opendisplay-win* (C++ + web host C#): parsec-vdd, DXGI, Media Foundation H.264, cursor compuesto en el video,
    Pencil con `InjectSyntheticPointerInput` (igual que nosotros), un **cliente PWA con WebCodecs + WSS y emparejamiento
    por código** (cookie 30 días), tres modos (Pen Tablet sin video, Mirror, Extend), **región objetivo** editable
    desde ambos lados, curva de presión soft/linear/firm, toque directo de 5 dedos (`PT_TOUCH`), modo trackpad,
    "identificar pantallas", escala de video 100/75/50 %, indicador de hover local. Roadmap: driver IddCx propio firmado
    por SignPath, USB por usbmuxd, barra flotante de atajos, squeeze del Pencil Pro.
  - *Goosekwt/OpenDisplay* (C# + SwiftUI): ffmpeg ddagrab + `h264_nvenc` p1/ull CBR 32 Mb/s (misma idea que nosotros),
    usbmux propio en C#, **canal cifrado AES-GCM con clave de emparejamiento por QR**, flechas de posición en ambas
    pantallas al conectar, auto-tamaño del monitor virtual al panel, "window fitting" (devuelve ventanas al monitor
    principal al desconectar). Medido: 33–48 fps codificados a 2420×1668, no 60.

## 3. Tabla comparativa

| Capacidad | iPad Bridge (hoy) | Duet Pro | Astropad Studio | OpenDisplay (Mac) |
|---|---|---|---|---|
| Códec / bitrate | HEVC 10b, 100 Mbps USB / 50 red | propietario, "retina 60 fps" | H.264 segmentos | H.264 o HEVC, ≤18 Mb/s |
| Imagen fija sin pérdida | **sí (PNG, ΔE 0)** | no | no | no |
| fps / refresco | 60 fps, VDD 120 Hz | 60 | 60 | ≤60 |
| Resolución nativa iPad | sí (2732×2048) | sí | sí (Retina on/off) | sí (@2x, presets) |
| Extendido / espejo | solo extendido | ambos | ambos (+ Move & Zoom) | solo extendido |
| USB | usbmuxd (Dispositivos Apple) | usbmuxd | usbmuxd | usbmuxd |
| Wi-Fi | WSS | sí | QUIC+TLS | TCP, sin cifrar |
| Descubrimiento automático | **no (IP a mano)** | sí | Bonjour + QR manual | Bonjour |
| Emparejamiento / cifrado | TLS con CA propia, sin pairing | cuenta | cuenta + TLS | ninguno (roadmap) |
| Cambio USB↔Wi-Fi sin corte | parcial (puente `auto`) | sí | sí | sí |
| Presión / tilt / hover | sí / sí / sí | sí / sí / sí | sí / sí / sí | sí / sí / sí (iOS 1.15+) |
| Goma del Pencil | **teclas E/B** | sí | sí (driver HID) | n/a |
| Curva de presión | variable de entorno | sí, custom | sí, editor + suavizado | no |
| Previsualización del trazo | **no** | sí ("Line Lead") | sí (stroke preview) | no |
| Rechazo de palma | sí (mientras toca) | sí | sí | n/a |
| Gestos de dedos configurables | **no** (1 dedo cursor, 2 scroll) | sí | sí, por app | tap/scroll |
| Barra de atajos | fija (11 botones) | sí | **por app, presets, 7 quick keys** | roadmap |
| Teclado en pantalla | **no** | sí | sí | no |
| Pencil Pro squeeze / barril | **no** | ? | sí / sí | no |
| Rotación vertical | **no** | sí | sí | sí |
| Varios iPads | sí (visores) | sí | no | sí |
| Latencia medida en pantalla | fps y cola | no | calidad de conexión | **e2e + input, reloj sincronizado** |
| Calidad adaptativa | bitrate por transporte | sí | 3 modos | presets + backpressure |
| Instalación | scripts + certificado a mano + Playgrounds | instalador + App Store | instalador + App Store | DMG/brew + App Store |
| Precio | 0 | 40–80 USD/año | 80–100 USD/año | 0 (donación) |

## 4. Qué implementar, mejorar y optimizar (por área)

### 4.1 Sensación del trazo (lo que más se nota al dibujar)

1. **Previsualización local del trazo** ("Line Lead" de Duet, "stroke preview" de Astropad). El input llega a la PC
   mucho antes que el video vuelve; mientras tanto el iPad puede dibujar una línea fina del color elegido sobre el canvas
   siguiendo el Pencil, incluyendo los puntos predichos (`getPredictedEvents` en Safari, `predictedTouches` en la app) y
   borrarla cuando el video la alcanza (por tiempo o por timestamp del frame). Reduce la latencia *percibida* sin tocar
   el pipeline. Archivos: `static/ipad.html` (capa canvas extra), app nativa.
2. **Curva de presión y suavizado desde el iPad.** Hoy `PEN_GAMMA` y `PEN_MIN` son variables de entorno; Astropad ofrece
   suave/firme/custom con editor y suavizado. Propuesta: mensaje `{"ev":"pencfg","gamma","min","smooth"}` guardado en
   `localStorage` y aplicado en `winput.Pen.curve` sin reiniciar; suavizado con un filtro 1€ sobre posición y presión
   (OpenDisplay-win usa soft=√p, linear, firm=p²). Panel en la barra de teclas con prueba en vivo.
3. **Goma real.** Windows no entrega `PEN_FLAG_ERASER` en lápices sintéticos (medido). Opciones, de menor a mayor costo:
   (a) mantener teclas pero por aplicación (ver 4.2); (b) driver HID virtual como `LiquidHidInput.sys` de Astropad: un
   KMDF sobre VHF que presente un digitalizador con goma y botones; es un driver de kernel y hay que firmarlo
   (SignPath para open source, o certificado EV + Partner Center); (c) reutilizar un driver HID virtual ya firmado y
   abierto (VMulti, que usa OpenTabletDriver) y alimentarlo desde `winput.py`. Recomiendo (a) ahora y evaluar (c) como
   experimento acotado antes de pensar en (b).
4. **Pencil Pro:** squeeze y rotación del barril solo existen en la app nativa (`UIPencilInteraction`); Safari no los
   expone. Squeeze → atajo configurable; barril → `rotation` en el evento `moves` y `POINTER_PEN_INFO.rotation`.
5. **Ocultar el cursor de Windows al dibujar** ya está (`POINTER_FEEDBACK_NONE`); agregar la opción inversa y un
   indicador de hover local en el iPad (opendisplay-win), útil en iPads sin hover para ver dónde va a caer el trazo.

### 4.2 Barra de atajos y gestos (Astropad es la referencia)

1. **Barra configurable por aplicación.** Pasar los 11 botones fijos de `ipad.html` a un JSON (`static/shortcuts.json`)
   con perfiles: Photoshop, Krita, Clip Studio, Blender, "genérico". El servidor ya sabe cuál es la ventana activa
   (`GetForegroundWindow` + nombre del proceso) y puede mandar `{"type":"app","name":"Photoshop"}` al iPad para cambiar
   de perfil solo, como hace el Sidebar de Astropad. Botones de tipo: pulsación, modificador mantenido, botón derecho/medio
   del mouse, "lanzar/cambiar app".
2. **Gestos de dedos configurables** (defaults de Astropad): 2 dedos tap = deshacer, 3 dedos tap = rehacer, 1 dedo
   mantenido + Pencil = goma (E mientras se mantiene, B al soltar), 2 dedos + Pencil = botón medio, 3 dedos + Pencil =
   botón derecho, pellizco = zoom de la app (Ctrl+rueda) o zoom de espejo. Hoy el código ignora los dedos mientras el
   Pencil toca; hay que distinguir "palma" (área grande, aparece después del Pencil) de "gesto" (toque breve antes o
   durante). La `FingerController` de opendisplay-win (tap 250 ms, doble 300 ms, umbrales 10/24 px) es un buen punto de
   partida.
3. **Teclado en pantalla** del iPad (campo de texto oculto que captura `keydown` y lo manda como `tap_keys`), más
   **teclado físico del iPad** reenviado tal cual (Astropad y el roadmap de OpenDisplay). Mapa de códigos como
   `keymap.hid.win.json`.
4. Doble toque del Pencil: ya alterna E/B; hacerlo configurable por app desde el mismo JSON.

### 4.3 Conexión y robustez

1. **Descubrimiento y emparejamiento.** Publicar `_ipadbridge._tcp` por mDNS (`zeroconf` en Python) con el `id` de la PC
   en TXT; la app nativa lista las PCs; la página web no puede hacer mDNS, así que `pc.html` muestra un **QR** con la URL
   https y un **código de emparejamiento** de 6 dígitos que da una cookie/token (como el PWA de opendisplay-win y el
   QR de Goosekwt). Hoy cualquiera en la LAN que conozca la IP puede ver la pantalla e inyectar input.
2. **Cambio de transporte sin corte.** Hoy `usb_bridge.py auto` elige al arrancar. Hacer que el puente vigile usbmux y
   migre la sesión de Wi-Fi a USB cuando aparece el cable (OpenDisplay "cable upgrade": la sonda que conecta se vuelve la
   sesión), y que la caída del cable termine la sesión en vez de resucitarla por Wi-Fi.
3. **Liveness y reconexión.** `ping` cada 2 s, se corta a los 5 s sin bytes, `need-key` automático al volver del fondo
   (hoy el decodificador queda esperando keyframe hasta 1 s), mensajes `sleeping`/`closing` para que el servidor sepa si
   detener la captura. Reconexión con backoff en la app nativa.
4. **Calidad adaptativa.** Usar lo que ya medimos (cola de decodificación > 6, Mbps reales, RTT del ping) para bajar
   bitrate o escala (100/75/50 %, `scale_cuda` después de ddagrab) en Wi-Fi y subir de nuevo cuando se estabiliza. El
   "Adaptive Image Rendering" de Astropad es esto mismo más el modo manual "mejor para dibujo / para movimiento".
5. **Keyframes.** Hoy uno por segundo: es un pulso de bitrate y de calidad visible cada segundo. NVENC permite
   `-intra-refresh 1` (refresco progresivo sin IDR) y GOP largo; los visores nuevos piden `need-key` y hoy eso ya
   reinicia la captura. Probar GOP de 4–10 s con intra-refresh y medir ΔE y Mbps con `tools/color_check.py`.
6. **Canal del cursor aparte (Wi-Fi).** OpenDisplay manda la posición del cursor por UDP para que no espere detrás de un
   frame grande. Para el cliente web no hay UDP; en la app nativa sí (socket UDP junto al TCP de usbmux no aplica por
   cable, solo por red). Baja prioridad porque por USB no hace falta.
7. **Otras GPU.** ffmpeg trae `hevc_amf`, `hevc_qsv` y `libx265`; detectar el encoder disponible en `server.py` y
   elegir perfil (AMD/Intel en 8 bits H.264 si hace falta). Hoy la instalación exige NVIDIA.

### 4.4 Pantalla y modos

1. **Rotación vertical:** rehacer el monitor virtual 2048×2732 al rotar el iPad (`place_vdd.py` ya fija modos; falta el
   mensaje desde el iPad y el cambio de modo con `ChangeDisplaySettingsEx`). Los tres competidores lo tienen.
2. **Modo espejo con Move & Zoom:** capturar un monitor físico (ddagrab `output_idx` ya se calcula) y recortar una región
   con `crop`; pellizco en el iPad = cambiar la región. Útil para quien no quiere pantalla extra y para detalle fino.
3. **Modo tableta (sin video):** el iPad como Intuos sobre el monitor principal, mapeando una región configurable (modo
   "Pen Tablet" de opendisplay-win con editor de región en ambos lados). Casi gratis con lo que ya existe en `winput.py`.
4. **Flechas de posición** al conectar (Goosekwt): un cartel efímero en cada pantalla indicando de qué lado está la otra.
5. **Window fitting:** al desconectar el iPad, devolver al monitor principal las ventanas que quedaron en el virtual (hoy
   Windows las minimiza o las deja fuera de vista).

### 4.5 Instalación y distribución

1. **Un instalador** (Inno Setup, como recomienda el roadmap de opendisplay-win; MSIX no puede instalar drivers): Python
   embebido o PyInstaller, ffmpeg, VDD con `pnputil`, certificados, regla de firewall, acceso directo. Hoy son cuatro
   pasos con PowerShell y permisos de administrador.
2. **App de bandeja** (pystray/Tk o un pequeño ejecutable) en lugar de la consola: estado, iPads conectados, Mbps, botón
   de espejo/extendido, "Iniciar con Windows". Lo que hoy muestra `pc.html`.
3. **Sin certificados a mano en el iPad:** la app nativa no necesita TLS (TCP + cifrado propio tipo AES-GCM con clave de
   emparejamiento, como Goosekwt) y la página web puede seguir con la CA solo para quien la use. Distribuir la app por
   TestFlight o con una cuenta de desarrollador gratuita en vez de Playgrounds.
4. **App nativa completa** (Xcode, no Playgrounds): decodificación con `VTDecompressionSession` y presentación Metal
   "latest-wins" (OpenDisplay mide ~1 frame menos que `AVSampleBufferDisplayLayer`), Pencil Pro, teclado, hover,
   Bonjour, reconexión, overlay de latencia.

### 4.6 Medición (sin esto no se puede optimizar)

1. **Sincronización de reloj** `ping/pong` (offset de la muestra de menor RTT, 15 muestras) y **timestamp de captura**
   en cada frame (ya mandamos `ts` f64): HUD con latencia captura→pantalla p50/p95 e input→PC.
2. `stats` del iPad al servidor cada 5 s (fps, Mbps, e2e, cola, descartes) a un log, como OpenDisplay, para diagnosticar
   Wi-Fi sin estar al lado.
3. Banco de pruebas: barra en movimiento determinista (Goosekwt midió 56 actualizaciones/s de 60 posibles) para saber si
   perdemos frames en captura, codificación o presentación.

## 5. Plan priorizado

Criterio: primero lo que cambia la sensación al dibujar y no requiere nuevos componentes; después robustez y onboarding;
al final lo que necesita driver firmado o app nativa completa. Esfuerzos estimados para una persona.

### Fase 0: medir y sentir (3–5 días)

| # | Mejora | Archivos | Esfuerzo |
|---|---|---|---|
| 0.1 | Reloj sincronizado + HUD de latencia e2e e input; `stats` al log | server.py, ipad.html | 1 día |
| 0.2 | Previsualización local del trazo con puntos predichos | ipad.html | 1 día |
| 0.3 | Curva de presión y suavizado desde el iPad (suave/lineal/firme/gamma), sin reiniciar | ipad.html, winput.py, server.py | 1 día |
| 0.4 | Experimento keyframes: GOP largo + intra-refresh, medir Mbps y ΔE | server.py, tools/color_check.py | ½ día |
| 0.5 | Gestos mínimos: 2 dedos tap deshacer, 3 dedos tap rehacer, 1 dedo + Pencil goma | ipad.html, server.py | 1 día |

### Fase 1: barra por app, conexión y onboarding (2 semanas)

| # | Mejora | Archivos | Esfuerzo |
|---|---|---|---|
| 1.1 | Barra de atajos en JSON con perfiles por app y detección de ventana activa | static/shortcuts.json, ipad.html, server.py, winput.py | 2–3 días |
| 1.2 | Botones derecho/medio y teclado en pantalla + teclado físico del iPad | ipad.html, winput.py | 1–2 días |
| 1.3 | QR + código de emparejamiento con token; rechazar visores sin token | pc.html, server.py, ipad.html | 1–2 días |
| 1.4 | mDNS `_ipadbridge._tcp` y lista de PCs en la app nativa | server.py, app | 1 día |
| 1.5 | Liveness ping/pong, `need-key` al volver del fondo, `sleeping/closing`, backoff | server.py, ipad.html, app, usb_bridge.py | 1–2 días |
| 1.6 | Migración Wi-Fi→USB en caliente y "el cable manda" | usb_bridge.py, server.py | 1–2 días |
| 1.7 | Bitrate/escala adaptativos por cola, Mbps y RTT; preset manual dibujo/movimiento | server.py, ipad.html | 2 días |
| 1.8 | Instalador único (Inno Setup) + app de bandeja con autostart | setup.ps1 → instalador, nuevo tray.py | 3 días |

### Fase 2: modos y app nativa (3–4 semanas)

| # | Mejora | Esfuerzo |
|---|---|---|
| 2.1 | Rotación vertical (VDD 2048×2732 al rotar) | 2 días |
| 2.2 | Modo tableta sin video con región configurable | 2 días |
| 2.3 | Modo espejo con Move & Zoom (recorte ddagrab + pellizco) | 3 días |
| 2.4 | App nativa en Xcode: VTDecompressionSession + Metal latest-wins, Pencil Pro (squeeze, barril), hover, teclado, Bonjour, cifrado AES-GCM con clave de QR, TestFlight | 2–3 semanas |
| 2.5 | Soporte AMD/Intel (AMF/QSV) y software como último recurso | 2 días |
| 2.6 | Flechas de posición y window fitting al desconectar | 1–2 días |

### Fase 3: diferenciadores con costo alto (evaluar antes de comprometer)

- **Goma y botones reales por HID virtual** (VMulti firmado como prueba; driver propio sobre VHF solo si la prueba
  convence y se consigue firma: SignPath si el proyecto es open source, o certificado EV + Partner Center).
- **Varios iPads con tamaños distintos** (segundo adaptador VDD o driver propio con identidad estable, el problema que
  describe el roadmap de opendisplay-win con parsec-vdd).
- **Color 4:4:4 en movimiento** no es viable en hardware de iPad; lo que sí: actualizaciones parciales PNG de regiones
  quietas (texto, paneles) mientras el lienzo se mueve, extendiendo el detector de pantalla quieta a rectángulos.

### Decisiones tomadas (30 de octubre de 2026)

- **App nativa sin cuenta Apple Developer:** se mantiene como proyecto de Swift Playgrounds (`app/iPadBridge.swiftpm`),
  compilado en el propio iPad. Sin TestFlight ni App Store; quien la quiera la abre en Playgrounds. Las fases 2.4 y 1.4
  apuntan a ese proyecto.
- **Open source:** el proyecto se publica con licencia libre. Habilita la firma gratuita de un driver por SignPath en la
  Fase 3 y obliga a no commitear claves (`certs/*.key` quedan fuera del repositorio).
- **Distribución a otras PCs:** sí; la Fase 1.8 (instalador Inno Setup + app de bandeja) se mantiene completa.
- **iPad de pruebas:** iPad Pro 12,9" 5.ª generación (M1) con Apple Pencil 2. No tiene hover ni squeeze ni barril: ese
  código se escribe según la documentación pero no se puede validar acá. El flujo "iPad sin hover" es el principal.
- **Pruebas y reinicios:** el servidor se puede reiniciar siempre que el trabajo sea sobre el proyecto; las pruebas de
  sensación (curva, suavizado, previsualización, gestos) las hace Demian al cierre de cada bloque.
- **Organización:** repositorio git; tres sesiones en paralelo por área (video y medición; input, barra y gestos;
  conexión e instalador), cada una en su copia del repositorio.

## 6. Métricas objetivo

| Métrica | Hoy | Objetivo tras Fase 1 |
|---|---|---|
| Latencia captura→pantalla (USB, 60 Hz) | no medida (estimada 2–4 frames) | medida; ≤ 50 ms p95 |
| Latencia input→PC | no medida | medida; ≤ 15 ms p95 |
| fps reales presentados | 60 (HUD) | 60 sostenidos, 0 descartes/min en USB |
| Mbps en reposo | ~constante por keyframes | cercano a 0 (PNG fijo + GOP largo) |
| Pasos de instalación en PC | 4 scripts + admin | 1 instalador |
| Pasos en iPad (primera vez) | certificado + confianza + app por Playgrounds | abrir app, escanear QR |

## 7. Estado de la instalación de las apps de la competencia

- **Duet** (`DuetDisplay-4-0-511.exe`, 179 MB, firma válida de Duet, Inc.) y **Astropad Studio**
  (`AstropadStudio-5.5.3.5.exe`, 105 MB, firma válida de Astro HQ LLC) se descargaron de los sitios oficiales a
  `C:\Users\dszkl\AppData\Local\Temp\claude\C--Users-dszkl-ipad-link\4473c358-f066-47ff-8248-93ac45a4fd6b\scratchpad\dl\`.
- Los dos intentos de instalación desatendida (`/quiet` y `/passive`, luego `/exenoui /qn` y `/exebasicui /qb`) terminaron
  con código 1619; el MSI de Astropad declara que solo corre desde su bootstrapper y ambos exigen cuenta para usarse.
- **No conviene instalar Astropad en esta PC** sin respaldar antes `C:\VirtualDisplayDriver\vdd_settings.xml`: su servicio
  usa el mismo driver MttVDD y reescribe ese archivo. Duet agrega su propio driver de pantalla. Si querés probarlas en
  funcionamiento, lo ideal es otra PC o una máquina virtual con GPU; si es acá, ejecutá el instalador a mano con el
  respaldo hecho y después `python tools/place_vdd.py left --hz=120` para restaurar.
- Lo extraído sin instalar quedó en `scratchpad\dl\astropad\layout\` (archivos de Astropad) y
  `scratchpad\dl\duet\carved\` (bundles de VC++ del instalador de Duet); el código fuente de OpenDisplay en
  `scratchpad\src\` (`opendisplay`, `opendisplay-win`, `opendisplay-goosekwt`).

## 8. Fuentes

- Duet: https://www.duetdisplay.com/es, https://www.duetdisplay.com/pro, https://www.duetdisplay.com/air,
  App Store id935754064 (precios e IAP), instalador 4.0.511 (`account.duetdisplay.com/api/download/windows`).
- Astropad: https://astropad.com/product/studio/, blog 5.4 (squeeze, barril, Adaptive Image Rendering),
  soporte: requisitos (11835972), extend vs mirror (12895992), presión en Windows (12264536), curva y suavizado
  (11835979), Sidebar (11835987), Magic Gestures (11835965), Quick Keys (11835969), Peer-to-Peer (11835988);
  instalador 5.5.3.5 (`downloads.astropad.com/studio/win/latest`).
- OpenDisplay: https://opendisplay.app/, https://github.com/peetzweg/opendisplay (README, PROTOCOL.md, CHANGELOG,
  Mac/MacSender.swift, iOS/MetalVideoRenderer.swift), https://github.com/Benson5650/opendisplay-win (README, ROADMAP,
  HANDOFF, src/input, web-host), https://github.com/Goosekwt/OpenDisplay (PRODUCT, docs/capture-validation.md,
  windows/OpenDisplay.Core).
