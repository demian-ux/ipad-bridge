import UIKit
import QuartzCore

/// Previsualización local del trazo: el input llega a la PC antes de que vuelva el video, así que una línea fina sigue
/// al Pencil (con los puntos predichos de UIKit más tenues) y cada tramo se desvanece con su edad hasta `duration`
/// segundos, cuando el video ya lo alcanzó. Al levantar el lápiz lo predicho se borra ya y lo real se apaga solo.
/// Un CAShapeLayer por lote de puntos (una llamada a touchesMoved: todos los coalescidos con la misma hora) y un
/// CADisplayLink que baja la opacidad; sin redibujar toda la pantalla.
final class StrokePreview {
    let layer = CALayer()
    var color = UIColor.red
    var width: CGFloat = 1.5
    var duration: TimeInterval = 0.07

    private var segments: [(layer: CAShapeLayer, t: TimeInterval)] = []
    private let predicted = CAShapeLayer()
    private var last: CGPoint?
    private var link: CADisplayLink?

    init() {
        layer.isOpaque = false
        predicted.fillColor = nil
        predicted.lineCap = .round
        predicted.lineJoin = .round
        predicted.opacity = 0.45
        layer.addSublayer(predicted)
    }

    deinit { link?.invalidate() }

    private var now: TimeInterval { CACurrentMediaTime() }

    /// El Pencil tocó: punto de partida (sin tramo todavía).
    func start(at p: CGPoint) {
        clear()
        last = p
    }

    /// Un lote de puntos reales (coalescidos) y los predichos desde el último real.
    func add(points: [CGPoint], predicted pts: [CGPoint]) {
        guard let from = last, !points.isEmpty else { return }
        let path = CGMutablePath()
        path.move(to: from)
        for p in points { path.addLine(to: p) }
        let s = CAShapeLayer()
        s.path = path
        s.strokeColor = color.cgColor
        s.fillColor = nil
        s.lineWidth = width
        s.lineCap = .round
        s.lineJoin = .round
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        layer.insertSublayer(s, below: predicted)
        segments.append((layer: s, t: now))
        last = points.last
        setPredicted(pts)
        CATransaction.commit()
        startLink()
    }

    /// Pencil levantado: lo predicho se borra ya; los tramos reales se desvanecen solos.
    func end() {
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        predicted.path = nil
        CATransaction.commit()
        last = nil
    }

    /// Borrar todo (cambio de herramienta, app a segundo plano, previsualización apagada).
    func clear() {
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        for s in segments { s.layer.removeFromSuperlayer() }
        segments.removeAll()
        predicted.path = nil
        CATransaction.commit()
        last = nil
        stopLink()
    }

    private func setPredicted(_ pts: [CGPoint]) {
        guard let from = last, !pts.isEmpty else { predicted.path = nil; return }
        let path = CGMutablePath()
        path.move(to: from)
        for p in pts { path.addLine(to: p) }
        predicted.path = path
        predicted.lineWidth = width
        predicted.strokeColor = color.cgColor
    }

    private func startLink() {
        guard link == nil else { return }
        let l = CADisplayLink(target: DisplayLinkProxy(self), selector: #selector(DisplayLinkProxy.tick))
        l.add(to: .main, forMode: .common)
        link = l
    }

    private func stopLink() {
        link?.invalidate()
        link = nil
    }

    fileprivate func tick() {
        let t = now
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        var keep: [(layer: CAShapeLayer, t: TimeInterval)] = []
        for seg in segments {
            let age = t - seg.t
            if age > duration {
                seg.layer.removeFromSuperlayer()
            } else {
                seg.layer.opacity = Float(max(0, 1 - age / duration))
                keep.append(seg)
            }
        }
        segments = keep
        if segments.isEmpty { predicted.path = nil }
        CATransaction.commit()
        if segments.isEmpty { stopLink() }
    }
}

/// CADisplayLink retiene a su target: un proxy débil evita el ciclo con la previsualización.
private final class DisplayLinkProxy: NSObject {
    weak var target: StrokePreview?
    init(_ t: StrokePreview) { target = t }
    @objc func tick() { target?.tick() }
}
