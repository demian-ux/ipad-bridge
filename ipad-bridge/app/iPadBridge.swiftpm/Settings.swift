import Foundation
import UIKit

/// Ajustes del panel ⚙ (presión, previsualización, gestos), con los mismos valores por defecto que la página.
/// Persisten en UserDefaults (lo mismo que hace @AppStorage, pero accesibles desde la vista UIKit del video sin
/// pasar por SwiftUI). Los de presión se mandan al servidor como pencfg (Bridge se engancha en onPenChange).
final class Settings: ObservableObject {
    @Published var gamma = 0.8 { didSet { save("gamma", gamma); penChanged() } }
    @Published var minPressure = 0.02 { didSet { save("min", minPressure); penChanged() } }
    @Published var smooth = 0.0 { didSet { save("smooth", smooth); penChanged() } }
    @Published var preview = true { didSet { save("preview", preview) } }
    @Published var previewColor = "#ff3b30" { didSet { save("pvColor", previewColor) } }
    @Published var previewWidth = 1.5 { didSet { save("pvWidth", previewWidth) } }
    @Published var previewMs = 70.0 { didSet { save("pvMs", previewMs) } }
    @Published var gestures = true { didSet { save("gestures", gestures); gestureChanged() } }
    /// Radio de palma del panel; -1 = usar el de shortcuts.json.
    @Published var palmRadius = -1.0 { didSet { save("palmRadius", palmRadius); gestureChanged() } }

    var onPenChange: (() -> Void)?
    var onGestureChange: (() -> Void)?

    private let defaults = UserDefaults.standard
    private var loading = true

    init() {
        if let v = defaults.object(forKey: "pencfg.gamma") as? Double { gamma = v }
        if let v = defaults.object(forKey: "pencfg.min") as? Double { minPressure = v }
        if let v = defaults.object(forKey: "pencfg.smooth") as? Double { smooth = v }
        if let v = defaults.object(forKey: "pencfg.preview") as? Bool { preview = v }
        if let v = defaults.object(forKey: "pencfg.pvColor") as? String { previewColor = v }
        if let v = defaults.object(forKey: "pencfg.pvWidth") as? Double { previewWidth = v }
        if let v = defaults.object(forKey: "pencfg.pvMs") as? Double { previewMs = v }
        if let v = defaults.object(forKey: "pencfg.gestures") as? Bool { gestures = v }
        if let v = defaults.object(forKey: "pencfg.palmRadius") as? Double { palmRadius = v }
        loading = false
    }

    /// Lo que va al servidor: curva, umbral y suavizado (se aplica en caliente).
    var penConfigMessage: [String: Any] {
        ["ev": "pencfg", "pen": 1, "gamma": gamma, "min": minPressure, "smooth": smooth]
    }

    /// Presión que verá Windows para una presión cruda del Pencil (misma fórmula que el servidor, para el panel y el HUD).
    func outputPressure(_ raw: Double) -> Double {
        raw > 0 ? max(minPressure, pow(raw, gamma)) : 0
    }

    var previewUIColor: UIColor { UIColor(hex: previewColor) ?? UIColor(red: 1, green: 0.23, blue: 0.19, alpha: 1) }

    private func save(_ key: String, _ value: Any) {
        guard !loading else { return }
        defaults.set(value, forKey: "pencfg." + key)
    }
    private func penChanged() { if !loading { onPenChange?() } }
    private func gestureChanged() { if !loading { onGestureChange?() } }
}

extension UIColor {
    /// "#rrggbb" -> color; nil si no es un hex válido.
    convenience init?(hex: String) {
        var s = hex.trimmingCharacters(in: .whitespaces)
        if s.hasPrefix("#") { s.removeFirst() }
        guard s.count == 6, let v = UInt32(s, radix: 16) else { return nil }
        self.init(red: CGFloat((v >> 16) & 0xff) / 255, green: CGFloat((v >> 8) & 0xff) / 255, blue: CGFloat(v & 0xff) / 255, alpha: 1)
    }

    /// Color -> "#rrggbb" (sin alfa), para guardarlo como texto igual que la página.
    var hexString: String {
        var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        guard getRed(&r, green: &g, blue: &b, alpha: &a) else { return "#ff3b30" }
        let c = { (x: CGFloat) -> Int in Int((max(0, min(1, x)) * 255).rounded()) }
        return String(format: "#%02x%02x%02x", c(r), c(g), c(b))
    }
}
