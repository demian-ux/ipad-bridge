import SwiftUI
import UIKit
import AVFoundation

/// Muestra el video con AVSampleBufferDisplayLayer (decodificación por hardware) y manda Pencil y toques a la PC.
/// Pencil = lápiz de Windows con presión, inclinación y hover (en iPads que detectan el Pencil en el aire).
/// Doble toque del Pencil = alternar goma. Dedos, como en ipad.html: un dedo mueve el cursor (tap = clic, doble tap =
/// doble clic), dos dedos = scroll, tap de dos/tres dedos = atajos; dedos apoyados ANTES del Pencil y lejos de la punta
/// = gesto mientras duren (1 goma, 2 botón medio, 3 derecho, según shortcuts.json); los que llegan DESPUÉS del
/// Pencil o cerca de su punta son palma y se ignoran. Encima del video, la previsualización local del trazo.
/// La barra de teclas (KeyBar, en MyApp.swift) va encima de esta vista, por eso un dedo sí la usa mientras se dibuja.
struct VideoView: UIViewRepresentable {
    let bridge: Bridge

    func makeUIView(context: Context) -> TouchVideoView {
        let v = TouchVideoView()
        v.bridge = bridge
        bridge.onSample = { [weak v] sample in
            DispatchQueue.main.async { v?.enqueue(sample) }
        }
        bridge.onFlush = { [weak v] in
            DispatchQueue.main.async { v?.displayLayer.flush() }
        }
        bridge.onStill = { [weak v] data in
            v?.showStill(data)
        }
        bridge.onKeyboardClosed = { [weak v] in
            _ = v?.becomeFirstResponder()   // el teclado físico vuelve a esta vista cuando se cierra el campo de texto
        }
        return v
    }

    func updateUIView(_ uiView: TouchVideoView, context: Context) {}
}

final class TouchVideoView: UIView, UIPencilInteractionDelegate {
    weak var bridge: Bridge?
    let displayLayer = AVSampleBufferDisplayLayer()
    /// Imagen fija sin pérdida (PNG) encima del video mientras la pantalla de la PC está quieta.
    private let stillView = UIImageView()
    private var stillSeq = 0
    private let decodeQueue = DispatchQueue(label: "bridge.still", qos: .userInitiated)
    private var videoSize = CGSize.zero
    private let preview = StrokePreview()

    // Pencil
    private var penDown = false { didSet { bridge?.penDown = penDown } }
    private var penMode: Int?             // nil = lápiz; si no, el Pencil hace de ese botón del mouse (gesto o barra)
    private var lastPos: (Double, Double)?
    private var leaveWork: DispatchWorkItem?
    private var eraser = false            // goma del doble toque del Pencil
    private var lastRaw = 0.0
    private var hudAt: TimeInterval = 0

    // Dedos (misma máquina de estados que ipad.html)
    private struct Finger { var x: CGFloat; var y: CGFloat; let x0: CGFloat; let y0: CGFloat; let t0: TimeInterval; var palm: Bool }
    private struct TouchGroup { let t0: TimeInterval; var maxN = 0; var moved = false; var used: Bool }   // desde el primer dedo hasta que no queda ninguno
    private struct Hold { let n: Int; let action: ShortcutAction; var pendingEnd = false }         // gesto mantenido activo
    private struct Scroll { var cx: CGFloat; var cy: CGFloat; var active = false }
    private struct Tap { let t: TimeInterval; let p: CGPoint; let nx: Double; let ny: Double }    // para que el doble clic caiga en el mismo punto
    private var fingers: [UITouch: Finger] = [:]
    private var group: TouchGroup?
    private var hold: Hold?
    private var scroll: Scroll?
    private var lastTap: Tap?

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = .black
        isMultipleTouchEnabled = true
        displayLayer.videoGravity = .resizeAspect
        displayLayer.backgroundColor = UIColor.black.cgColor
        layer.addSublayer(displayLayer)
        stillView.contentMode = .scaleAspectFit
        stillView.isHidden = true
        stillView.isUserInteractionEnabled = false
        addSubview(stillView)
        layer.addSublayer(preview.layer)   // encima del video y de la imagen fija
        // Pencil en el aire (iPad Pro M2 o más nuevo): mueve el cursor del lápiz en Windows sin tocar.
        addGestureRecognizer(UIHoverGestureRecognizer(target: self, action: #selector(hoverChanged(_:))))
        // Doble toque en el Pencil (2.ª generación / Pro): goma.
        let pencil = UIPencilInteraction()
        pencil.delegate = self
        addInteraction(pencil)
        // Al pasar a segundo plano no dejar nada pegado (gesto, botón del mouse, trazo previsualizado).
        NotificationCenter.default.addObserver(self, selector: #selector(resetState), name: UIApplication.willResignActiveNotification, object: nil)
    }
    required init?(coder: NSCoder) { fatalError() }
    deinit { NotificationCenter.default.removeObserver(self) }

    override func layoutSubviews() {
        super.layoutSubviews()
        displayLayer.frame = bounds
        stillView.frame = bounds
        preview.layer.frame = bounds
    }

    // Teclado físico sin el campo de texto activo: esta vista es primer respondedor y recibe las teclas (pressesBegan).
    override var canBecomeFirstResponder: Bool { true }
    override func didMoveToWindow() {
        super.didMoveToWindow()
        if window != nil, !(bridge?.keyboardOn ?? false) { _ = becomeFirstResponder() }
    }
    override func pressesBegan(_ presses: Set<UIPress>, with event: UIPressesEvent?) {
        var handled = false
        for p in presses {
            if let m = HardwareKeys.message(for: p, textToo: true) { bridge?.sendInput(m); handled = true }
        }
        if !handled { super.pressesBegan(presses, with: event) }
    }

    func showStill(_ data: Data?) {
        stillSeq += 1
        let seq = stillSeq
        guard let data = data else {
            DispatchQueue.main.async { self.stillView.isHidden = true }
            return
        }
        decodeQueue.async { [weak self] in
            // Decodificar fuera del hilo principal; descartar si llegó un still-clear mientras tanto.
            guard let image = UIImage(data: data)?.preparingForDisplay() else { return }
            DispatchQueue.main.async {
                guard let self = self, seq == self.stillSeq else { return }
                self.stillView.image = image
                self.stillView.isHidden = false
            }
        }
    }

    func enqueue(_ sample: CMSampleBuffer) {
        if let fmt = CMSampleBufferGetFormatDescription(sample) {
            let d = CMVideoFormatDescriptionGetDimensions(fmt)
            videoSize = CGSize(width: CGFloat(d.width), height: CGFloat(d.height))
        }
        if displayLayer.status == .failed {
            displayLayer.flush()
            bridge?.requestKeyframe()
            return
        }
        if displayLayer.isReadyForMoreMediaData {
            displayLayer.enqueue(sample)
        }
    }

    // MARK: - Coordenadas normalizadas dentro del área real del video

    /// Rectángulo donde se ve el video con resizeAspect (AVSampleBufferDisplayLayer no expone videoRect).
    private var videoRect: CGRect {
        guard videoSize.width > 0, videoSize.height > 0, bounds.width > 0, bounds.height > 0 else { return bounds }
        let s = min(bounds.width / videoSize.width, bounds.height / videoSize.height)
        let w = videoSize.width * s, h = videoSize.height * s
        return CGRect(x: (bounds.width - w) / 2, y: (bounds.height - h) / 2, width: w, height: h)
    }

    private func norm(_ p: CGPoint) -> (Double, Double) {
        let r = videoRect
        guard r.width > 0, r.height > 0 else { return (0, 0) }
        let x = min(1, max(0, (p.x - r.minX) / r.width))
        let y = min(1, max(0, (p.y - r.minY) / r.height))
        return (Double(x), Double(y))
    }

    private var now: TimeInterval { ProcessInfo.processInfo.systemUptime }
    private var settings: Settings? { bridge?.settings }
    private var gestures: GestureConfig { bridge?.gestureConfig ?? Shortcuts.fallback.gestureConfig(profileIndex: 0, palmRadius: nil) }
    private var gesturesOn: Bool { settings?.gestures ?? true }
    private func send(_ d: [String: Any]) { bridge?.sendInput(d) }

    // MARK: - Pencil

    private func pressure(_ t: UITouch) -> Double {
        t.maximumPossibleForce > 0 ? Double(t.force / t.maximumPossibleForce) : 0
    }

    /// Altitud/azimut de UIKit -> inclinación X/Y en grados como la define Windows (X positivo a la derecha,
    /// Y positivo hacia el usuario), igual que tiltX/tiltY de un Wacom.
    private func tilt(_ altitude: CGFloat, _ azimuth: CGFloat) -> (Int, Int) {
        let alt = max(0.01, min(CGFloat.pi / 2, altitude))
        let k = 1 / tan(alt)
        let tx = atan(cos(azimuth) * k) * 180 / .pi
        let ty = atan(sin(azimuth) * k) * 180 / .pi
        return (Int(tx.rounded()), Int(ty.rounded()))
    }

    private func penEvent(_ ev: String, _ t: UITouch) -> [String: Any] {
        let (x, y) = norm(t.location(in: self))
        let (tx, ty) = tilt(t.altitudeAngle, t.azimuthAngle(in: self))
        return ["ev": ev, "pen": 1, "x": x, "y": y, "p": pressure(t), "tx": tx, "ty": ty]
    }

    @objc private func hoverChanged(_ g: UIHoverGestureRecognizer) {
        switch g.state {
        case .began, .changed:
            leaveWork?.cancel(); leaveWork = nil
            guard !penDown else { return }
            let (x, y) = norm(g.location(in: self))
            var m: [String: Any] = ["ev": "hover", "pen": 1, "x": x, "y": y]
            if #available(iOS 16.4, *) {   // altitudeAngle / azimuthAngle(in:) del hover existen desde 16.4
                let (tx, ty) = tilt(g.altitudeAngle, g.azimuthAngle(in: self))
                m["tx"] = tx; m["ty"] = ty
            }
            send(m)
        case .ended, .cancelled, .failed:
            // El hover también termina justo antes de tocar: esperar un poco antes de avisar que el lápiz se alejó.
            let w = DispatchWorkItem { [weak self] in
                guard let self = self, !self.penDown else { return }
                self.send(["ev": "leave", "pen": 1])
            }
            leaveWork = w
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.15, execute: w)
        default: break
        }
    }

    func pencilInteractionDidTap(_ interaction: UIPencilInteraction) {
        guard UIPencilInteraction.preferredTapAction != .ignore else { return }
        eraser.toggle()
        send(["ev": "eraser", "pen": 1, "on": eraser])
        preview.clear()   // cambio de herramienta: que no quede el trazo anterior
        updatePenHud()
    }

    private func pencilBegan(_ t: UITouch) {
        leaveWork?.cancel(); leaveWork = nil
        let loc = t.location(in: self)
        let g = gestures
        // Dedos apoyados antes del Pencil: los cercanos a la punta son palma; los lejanos, un gesto.
        var gest = 0
        for k in Array(fingers.keys) {
            guard var f = fingers[k], !f.palm else { continue }
            if g.palmRadius > 0 && hypot(f.x - loc.x, f.y - loc.y) < CGFloat(g.palmRadius) {
                f.palm = true; fingers[k] = f
            } else {
                gest += 1
            }
        }
        if hold == nil, gest > 0, gesturesOn, let a = g.hold[gest] {
            startHold(gest, a)
            group?.used = true
        }
        scroll = nil
        penDown = true
        let (x, y) = norm(loc)
        lastPos = (x, y)
        let btn: Int? = (hold?.action.type == "mouse") ? hold?.action.btn : bridge?.barMouseBtn
        if let b = btn {   // el Pencil hace de botón del mouse: eventos de dedo con ese botón
            penMode = b
            bridge?.barMouseUsed = true
            send(["ev": "down", "x": x, "y": y, "btn": b])
            updatePenHud()
            return
        }
        penMode = nil
        send(penEvent("down", t))
        if settings?.preview ?? true {
            applyPreviewSettings()
            preview.start(at: loc)
        }
        showPressure(pressure(t))
    }

    private func pencilMoved(_ t: UITouch, _ event: UIEvent?) {
        guard penDown else { return }   // el hover va por el gesture recognizer
        let loc = t.location(in: self)
        let (x, y) = norm(loc)
        if penMode != nil {
            send(["ev": "move", "x": x, "y": y])
            lastPos = (x, y)
            return
        }
        // Trayectoria completa: todos los toques coalescidos (hasta 240 Hz), no solo el último.
        var pts: [[Any]] = []
        var cg: [CGPoint] = []
        for c in event?.coalescedTouches(for: t) ?? [t] {
            let l = c.location(in: self)
            let (cx, cy) = norm(l)
            let (tx, ty) = tilt(c.altitudeAngle, c.azimuthAngle(in: self))
            pts.append([cx, cy, pressure(c), tx, ty])
            cg.append(l)
        }
        if !pts.isEmpty { send(["ev": "moves", "pen": 1, "pts": pts]) }
        lastPos = (x, y)
        showPressure(pressure(t))
        if settings?.preview ?? true {
            let pred = (event?.predictedTouches(for: t) ?? []).map { $0.location(in: self) }
            preview.add(points: cg, predicted: pred)
        }
    }

    private func pencilEnded(_ t: UITouch) {
        guard penDown else { return }
        penDown = false
        let (x, y) = norm(t.location(in: self))
        if let b = penMode {
            send(["ev": "up", "x": x, "y": y, "btn": b])
            penMode = nil
        } else {
            send(["ev": "up", "pen": 1, "x": x, "y": y])
            preview.end()
            showPressure(0)
        }
        if hold?.pendingEnd == true { endHold() }
        updatePenHud()
    }

    private func applyPreviewSettings() {
        guard let s = settings else { return }
        preview.color = s.previewUIColor
        preview.width = CGFloat(s.previewWidth)
        preview.duration = s.previewMs / 1000
    }

    // MARK: - Dedos

    private var liveCount: Int { fingers.values.filter { !$0.palm }.count }
    private var liveCenter: CGPoint? {
        let live = fingers.values.filter { !$0.palm }
        guard live.count == 2 else { return nil }
        return CGPoint(x: (live[0].x + live[1].x) / 2, y: (live[0].y + live[1].y) / 2)
    }

    private func fingerBegan(_ t: UITouch) {
        if penDown { return }   // palma o dedo mientras se dibuja
        let g = gestures
        let loc = t.location(in: self)
        // Contacto grande = palma (majorRadius es el radio en puntos; palmSize viene como "tamaño", se compara con el radio).
        let palm = Double(t.majorRadius) > g.palmSize
        fingers[t] = Finger(x: loc.x, y: loc.y, x0: loc.x, y0: loc.y, t0: now, palm: palm)
        if palm { return }
        let live = liveCount
        if group == nil { group = TouchGroup(t0: now, used: hold != nil) }
        let prevMax = group?.maxN ?? 0            // leer antes de escribir: Swift exige acceso exclusivo a `group`
        group?.maxN = max(prevMax, live)
        if live == 1 && hold == nil {
            let (x, y) = norm(loc)
            send(["ev": "move", "x": x, "y": y]); lastPos = (x, y)
        }
        if live == 2 && hold == nil, let c = liveCenter { scroll = Scroll(cx: c.x, cy: c.y) }
        if live > 2 { scroll = nil }
    }

    private func fingerMoved(_ t: UITouch) {
        guard var f = fingers[t], !f.palm else { return }
        let loc = t.location(in: self)
        f.x = loc.x; f.y = loc.y
        fingers[t] = f
        let g = gestures
        if hypot(f.x - f.x0, f.y - f.y0) > CGFloat(g.tapPx) { group?.moved = true }
        if hold != nil || penDown { return }   // los dedos del gesto no mueven el cursor ni hacen scroll
        let live = liveCount
        if live == 1 {
            let (x, y) = norm(loc)
            send(["ev": "move", "x": x, "y": y]); lastPos = (x, y)
        } else if live == 2, var sc = scroll, let c = liveCenter, let gr = group {
            // Hasta moverse tapPx (o pasar tapMs) puede ser un toque de dos dedos: no hacer scroll todavía.
            if !sc.active && (hypot(c.x - sc.cx, c.y - sc.cy) > CGFloat(g.tapPx) || now - gr.t0 > g.tapMs / 1000) {
                sc.active = true; sc.cx = c.x; sc.cy = c.y
            }
            if sc.active {
                let dy = c.y - sc.cy, dx = c.x - sc.cx
                if abs(dy) > 2 || abs(dx) > 2 {
                    send(["ev": "scroll", "dy": Int(dy * 3), "dx": Int(-dx * 3)])
                    sc.cx = c.x; sc.cy = c.y
                }
            }
            scroll = sc
        }
    }

    private func fingerEnded(_ t: UITouch, cancelled: Bool) {
        guard let f = fingers.removeValue(forKey: t) else { return }
        let live = liveCount, g = gestures, t1 = now
        if live == 0 && hold != nil { endHold() }
        // iPadOS cancela los toques que decide que son palma: nunca son un clic.
        if !f.palm, live == 0, let gr = group, !cancelled {
            // Toque corto de 1, 2 o 3 dedos sin moverse: 1 = clic (en el punto del toque), 2 y 3 = atajos de shortcuts.json.
            // Tres dedos no caen a la vez: un poco más de margen que para uno.
            let isTap = !gr.used && !gr.moved && t1 - gr.t0 < (g.tapMs + (gr.maxN > 1 ? 100 : 0)) / 1000
            if isTap && (gr.maxN == 1 || gesturesOn) {
                let loc = t.location(in: self)
                var (tx, ty) = norm(loc)
                // Segundo toque de un doble clic: mismo punto que el primero, para que Windows lo tome como doble clic.
                if gr.maxN == 1, let lt = lastTap, t1 - lt.t < g.doubleMs / 1000,
                   hypot(loc.x - lt.p.x, loc.y - lt.p.y) < CGFloat(g.tapPx * 2.4) {
                    tx = lt.nx; ty = lt.ny
                }
                if gr.maxN == 1 { lastTap = Tap(t: t1, p: loc, nx: tx, ny: ty) }
                runTap(g.tap[gr.maxN], at: gr.maxN == 1 ? (tx, ty) : nil)
            }
        }
        if live == 0 { group = nil; scroll = nil } else if live < 2 { scroll = nil }
    }

    // MARK: - Acciones de gestos: {type: key | click | mouse | toggle | mod}

    private func runTap(_ a: ShortcutAction?, at: (Double, Double)?) {
        guard let a = a else { return }
        switch a.type {
        case "key", "toggle":
            send(["ev": "key", "keys": a.firstKeys])
        case "click", "mouse":
            var d: [String: Any] = ["btn": a.btn]
            if let p = at ?? lastPos { d["x"] = p.0; d["y"] = p.1 }
            d["ev"] = "down"; send(d)
            d["ev"] = "up"; send(d)
        case "mod":
            send(["ev": "mod", "key": a.key, "down": true])
            send(["ev": "mod", "key": a.key, "down": false])
        default: break
        }
    }

    /// Gesto mantenido: empieza cuando el Pencil toca con n dedos apoyados, termina al levantar los dedos (si el Pencil
    /// sigue abajo, al levantarlo). toggle: keys[0] al empezar, keys[1] al terminar. mod: mantenido. mouse: el Pencil
    /// hace de ese botón durante el gesto.
    private func startHold(_ n: Int, _ a: ShortcutAction) {
        hold = Hold(n: n, action: a)
        switch a.type {
        case "toggle", "key": send(["ev": "key", "keys": a.firstKeys])
        case "mod": send(["ev": "mod", "key": a.key, "down": true])
        default: break
        }
        updatePenHud()
    }

    private func endHold() {
        guard let h = hold else { return }
        if penDown { hold?.pendingEnd = true; return }
        hold = nil
        let a = h.action
        if a.type == "toggle", let k = a.secondKeys { send(["ev": "key", "keys": k]) }
        else if a.type == "mod" { send(["ev": "mod", "key": a.key, "down": false]) }
        updatePenHud()
    }

    @objc private func resetState() {
        penDown = false; penMode = nil
        fingers.removeAll(); group = nil; scroll = nil
        if hold != nil { endHold() }
        preview.clear()
        updatePenHud()
    }

    // MARK: - HUD y presión en vivo

    private func showPressure(_ p: Double) {
        lastRaw = p
        let t = now
        // Publicar a ~12 Hz (la vista SwiftUI se redibuja con cada cambio), y siempre al soltar.
        guard p == 0 || t - hudAt > 0.08 else { return }
        hudAt = t
        updatePenHud()
        if let b = bridge, b.panelOpen, b.penRaw != p { b.penRaw = p }
    }

    private func updatePenHud() {
        guard let b = bridge else { return }
        let s: String
        if let h = hold {
            let a = h.action
            let what: String
            switch a.type {
            case "toggle": what = a.firstKeys.uppercased()
            case "mod": what = a.key
            case "mouse": what = a.btn == 1 ? "medio" : "derecho"
            default: what = a.firstKeys
            }
            s = "\(h.n)☝ \(what)"
        } else if penDown && penMode == nil {
            let out = settings?.outputPressure(lastRaw) ?? lastRaw
            s = String(format: "pen %.2f→%.2f", lastRaw, out)
        } else if eraser {
            s = "GOMA"
        } else {
            s = ""
        }
        if b.penHud != s { b.penHud = s }
    }

    // MARK: - Toques

    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) {
        for t in touches {
            if t.type == .pencil { pencilBegan(t) } else { fingerBegan(t) }
        }
    }

    override func touchesMoved(_ touches: Set<UITouch>, with event: UIEvent?) {
        for t in touches {
            if t.type == .pencil { pencilMoved(t, event) } else { fingerMoved(t) }
        }
    }

    override func touchesEnded(_ touches: Set<UITouch>, with event: UIEvent?) {
        for t in touches {
            if t.type == .pencil { pencilEnded(t) } else { fingerEnded(t, cancelled: false) }
        }
    }

    override func touchesCancelled(_ touches: Set<UITouch>, with event: UIEvent?) {
        for t in touches {
            if t.type == .pencil { pencilEnded(t) } else { fingerEnded(t, cancelled: true) }
        }
    }
}
