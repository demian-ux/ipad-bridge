import SwiftUI
import UIKit
import AVFoundation

/// Muestra el video con AVSampleBufferDisplayLayer (decodificación por hardware) y manda Pencil y toques a la PC.
/// Pencil = lápiz de Windows con presión, inclinación y hover (en iPads que detectan el Pencil en el aire).
/// Doble toque del Pencil = alternar goma. Un dedo = mover cursor, tap = click. Dos dedos = scroll.
/// Mientras el Pencil toca la pantalla los dedos se ignoran (palma apoyada), como un Cintiq con el touch apagado.
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
    private var fingers: [UITouch] = []
    private var tapStart: (time: TimeInterval, point: CGPoint)?
    private var lastScroll: CGPoint?
    private var penDown = false
    private var leaveWork: DispatchWorkItem?

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
        // Pencil en el aire (iPad Pro M2 o más nuevo): mueve el cursor del lápiz en Windows sin tocar.
        addGestureRecognizer(UIHoverGestureRecognizer(target: self, action: #selector(hoverChanged(_:))))
        // Doble toque en el Pencil (2.ª generación / Pro): goma.
        let pencil = UIPencilInteraction()
        pencil.delegate = self
        addInteraction(pencil)
    }
    required init?(coder: NSCoder) { fatalError() }

    override func layoutSubviews() {
        super.layoutSubviews()
        displayLayer.frame = bounds
        stillView.frame = bounds
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

    private func norm(_ p: CGPoint) -> (Double, Double)? {
        let r = videoRect
        let x = min(1, max(0, (p.x - r.minX) / r.width))
        let y = min(1, max(0, (p.y - r.minY) / r.height))
        return (Double(x), Double(y))
    }

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

    private func penEvent(_ ev: String, _ t: UITouch) -> [String: Any]? {
        guard let (x, y) = norm(t.location(in: self)) else { return nil }
        let (tx, ty) = tilt(t.altitudeAngle, t.azimuthAngle(in: self))
        return ["ev": ev, "pen": 1, "x": x, "y": y, "p": pressure(t), "tx": tx, "ty": ty]
    }

    @objc private func hoverChanged(_ g: UIHoverGestureRecognizer) {
        switch g.state {
        case .began, .changed:
            leaveWork?.cancel(); leaveWork = nil
            guard !penDown, let (x, y) = norm(g.location(in: self)) else { return }
            var m: [String: Any] = ["ev": "hover", "pen": 1, "x": x, "y": y]
            if #available(iOS 16.4, *) {   // altitudeAngle / azimuthAngle(in:) del hover existen desde 16.4
                let (tx, ty) = tilt(g.altitudeAngle, g.azimuthAngle(in: self))
                m["tx"] = tx; m["ty"] = ty
            }
            bridge?.sendInput(m)
        case .ended, .cancelled, .failed:
            // El hover también termina justo antes de tocar: esperar un poco antes de avisar que el lápiz se alejó.
            let w = DispatchWorkItem { [weak self] in
                guard let self = self, !self.penDown else { return }
                self.bridge?.sendInput(["ev": "leave", "pen": 1])
            }
            leaveWork = w
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.15, execute: w)
        default: break
        }
    }

    func pencilInteractionDidTap(_ interaction: UIPencilInteraction) {
        guard UIPencilInteraction.preferredTapAction != .ignore else { return }
        // El estado de la goma vive en el badge (penHud) para que la barra de teclas (B/E) y el doble toque coincidan.
        let on = bridge?.penHud != "GOMA"
        bridge?.sendInput(["ev": "eraser", "pen": 1, "on": on])
        bridge?.penHud = on ? "GOMA" : ""
    }

    // MARK: - Toques

    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) {
        for t in touches {
            if t.type == .pencil {
                leaveWork?.cancel(); leaveWork = nil
                penDown = true
                if let m = penEvent("down", t) { bridge?.sendInput(m) }
            } else {
                if penDown { continue }   // palma o dedo mientras se dibuja
                fingers.append(t)
                if fingers.count == 1 {
                    tapStart = (t.timestamp, t.location(in: self))
                    if let (x, y) = norm(t.location(in: self)) { bridge?.sendInput(["ev": "move", "x": x, "y": y]) }
                } else if fingers.count == 2 {
                    tapStart = nil
                    lastScroll = nil
                }
            }
        }
    }

    override func touchesMoved(_ touches: Set<UITouch>, with event: UIEvent?) {
        for t in touches {
            if t.type == .pencil {
                // Trayectoria completa: todos los toques coalescidos (hasta 240 Hz), no solo el último.
                var pts: [[Any]] = []
                for c in event?.coalescedTouches(for: t) ?? [t] {
                    if let (x, y) = norm(c.location(in: self)) {
                        let (tx, ty) = tilt(c.altitudeAngle, c.azimuthAngle(in: self))
                        pts.append([x, y, pressure(c), tx, ty])
                    }
                }
                if !pts.isEmpty { bridge?.sendInput(["ev": "moves", "pen": 1, "pts": pts]) }
            } else if fingers.count == 1, fingers.first == t {
                if let (x, y) = norm(t.location(in: self)) { bridge?.sendInput(["ev": "move", "x": x, "y": y]) }
            } else if fingers.count == 2, fingers.contains(t) {
                let pts = fingers.map { $0.location(in: self) }
                let c = CGPoint(x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2)
                if let prev = lastScroll {
                    let dy = c.y - prev.y, dx = c.x - prev.x
                    if abs(dy) > 2 || abs(dx) > 2 {
                        bridge?.sendInput(["ev": "scroll", "dy": Int(dy * 3), "dx": Int(-dx * 3)])
                        lastScroll = c
                    }
                } else {
                    lastScroll = c
                }
            }
        }
    }

    override func touchesEnded(_ touches: Set<UITouch>, with event: UIEvent?) { end(touches) }
    override func touchesCancelled(_ touches: Set<UITouch>, with event: UIEvent?) { end(touches) }

    private func end(_ touches: Set<UITouch>) {
        for t in touches {
            if t.type == .pencil {
                penDown = false
                if let (x, y) = norm(t.location(in: self)) {
                    bridge?.sendInput(["ev": "up", "pen": 1, "x": x, "y": y])
                }
            } else {
                guard fingers.contains(t) else { continue }
                fingers.removeAll { $0 == t }
                if let ts = tapStart, fingers.isEmpty {
                    let p = t.location(in: self)
                    let d = hypot(p.x - ts.point.x, p.y - ts.point.y)
                    if t.timestamp - ts.time < 0.25 && d < 12, let (x, y) = norm(p) {
                        bridge?.sendInput(["ev": "down", "x": x, "y": y, "btn": 0])
                        bridge?.sendInput(["ev": "up", "x": x, "y": y, "btn": 0])
                    }
                    tapStart = nil
                }
                if fingers.count < 2 { lastScroll = nil }
            }
        }
    }
}
