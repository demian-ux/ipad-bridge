import Foundation

// Perfiles de la barra de teclas y gestos, con el mismo formato que static/shortcuts.json (la página los lee del
// archivo; a la app se los manda usb_bridge.py al conectarse como JSON de control {"type":"shortcuts",...}).
// Se parsea a mano desde [String: Any] porque "gestures" mezcla números y objetos.

/// Acción de un botón de la barra o de un gesto: key (pulsa `keys`), mod (mantiene `key`), mouse/click (`btn`),
/// toggle (alterna `keys[0]` y `keys[1]`), sep (separador).
struct ShortcutAction {
    let type: String
    let keys: [String]
    let key: String
    let btn: Int
    let label: String?
    let labels: [String]
    let caption: String?

    init?(_ json: Any?) {
        guard let d = json as? [String: Any], let type = d["type"] as? String else { return nil }
        self.type = type
        if let s = d["keys"] as? String { keys = [s] } else { keys = (d["keys"] as? [String]) ?? [] }
        key = (d["key"] as? String) ?? ""
        btn = (d["btn"] as? NSNumber)?.intValue ?? 0
        label = d["label"] as? String
        labels = (d["labels"] as? [String]) ?? []
        caption = d["caption"] as? String
    }

    var firstKeys: String { keys.first ?? "" }
    var secondKeys: String? { keys.count > 1 ? keys[1] : nil }

    /// Texto del botón. toggle: según el estado (iluminado = keys[0] activo).
    func title(on: Bool = true) -> String {
        if type == "toggle" {
            let i = on ? 0 : 1
            if labels.count > i { return labels[i] }
            return (keys.count > i ? keys[i] : firstKeys).uppercased()
        }
        if let l = label { return l }
        return (keys.first ?? key).uppercased()
    }

    /// Descripción corta para el panel: "ctrl+z", "e/b", "shift", "medio".
    var summary: String {
        switch type {
        case "key": return firstKeys
        case "toggle": return keys.joined(separator: "/")
        case "mod": return key
        case "mouse", "click": return btn == 1 ? "medio" : (btn == 2 ? "derecho" : "clic")
        default: return type
        }
    }
}

/// Un perfil: se elige por el ejecutable de la ventana activa en Windows (`match`).
struct ShortcutProfile {
    let id: String
    let name: String
    let short: String
    let match: [String]
    let gestures: [String: Any]
    let buttons: [ShortcutAction]

    init?(_ json: Any?) {
        guard let d = json as? [String: Any] else { return nil }
        id = (d["id"] as? String) ?? "?"
        name = (d["name"] as? String) ?? id
        short = (d["short"] as? String) ?? name
        match = ((d["match"] as? [String]) ?? []).map { $0.lowercased() }
        gestures = (d["gestures"] as? [String: Any]) ?? [:]
        buttons = ((d["buttons"] as? [Any]) ?? []).compactMap { ShortcutAction($0) }
    }

    func matches(exe: String) -> Bool {
        let e = exe.lowercased()
        return !e.isEmpty && match.contains(e)
    }
}

/// Gestos ya mezclados (generales + perfil) y con el radio de palma del panel si se tocó.
struct GestureConfig {
    var tapMs = 250.0
    var doubleMs = 300.0
    var tapPx = 10.0
    var palmRadius = 180.0
    var palmSize = 45.0
    var tap: [Int: ShortcutAction] = [:]
    var hold: [Int: ShortcutAction] = [:]

    init(_ d: [String: Any]) {
        func num(_ k: String, _ def: Double) -> Double { (d[k] as? NSNumber)?.doubleValue ?? def }
        tapMs = num("tapMs", tapMs); doubleMs = num("doubleMs", doubleMs); tapPx = num("tapPx", tapPx)
        palmRadius = num("palmRadius", palmRadius); palmSize = num("palmSize", palmSize)
        for n in 1...3 {
            if let a = ShortcutAction(d["tap\(n)"]) { tap[n] = a }
            if let a = ShortcutAction(d["hold\(n)"]) { hold[n] = a }
        }
    }

    /// "2☝ ctrl+z · 3☝ ctrl+y · ✎+1 e/b · ✎+2 medio · ✎+3 derecho"
    var summary: String {
        func d(_ a: ShortcutAction?) -> String { a?.summary ?? "—" }
        return "2☝ \(d(tap[2])) · 3☝ \(d(tap[3])) · ✎+1 \(d(hold[1])) · ✎+2 \(d(hold[2])) · ✎+3 \(d(hold[3]))"
    }
}

struct Shortcuts {
    let gestures: [String: Any]
    let profiles: [ShortcutProfile]

    init?(json: [String: Any]) {
        let ps = ((json["profiles"] as? [Any]) ?? []).compactMap { ShortcutProfile($0) }
        guard !ps.isEmpty else { return nil }
        profiles = ps
        gestures = (json["gestures"] as? [String: Any]) ?? [:]
    }

    /// Índice del perfil para ese ejecutable; el primero es el de respaldo.
    func profileIndex(forExe exe: String) -> Int {
        profiles.firstIndex { $0.matches(exe: exe) } ?? 0
    }

    /// Gestos generales del archivo encima de los embebidos, los del perfil encima de todo (como Object.assign).
    func gestureConfig(profileIndex i: Int, palmRadius: Double?) -> GestureConfig {
        var d = Shortcuts.fallbackGestures
        for (k, v) in gestures { d[k] = v }
        if i >= 0 && i < profiles.count { for (k, v) in profiles[i].gestures { d[k] = v } }
        if let r = palmRadius { d["palmRadius"] = r }
        return GestureConfig(d)
    }

    // Mínimo embebido por si el puente no manda shortcuts.json (puente viejo): la barra de siempre y los gestos de Astropad.
    static let fallbackGestures: [String: Any] = [
        "tapMs": 250, "doubleMs": 300, "tapPx": 10, "palmRadius": 180, "palmSize": 45,
        "tap1": ["type": "click", "btn": 0] as [String: Any],
        "tap2": ["type": "key", "keys": "ctrl+z"] as [String: Any],
        "tap3": ["type": "key", "keys": "ctrl+y"] as [String: Any],
        "hold1": ["type": "toggle", "keys": ["e", "b"]] as [String: Any],
        "hold2": ["type": "mouse", "btn": 1] as [String: Any],
        "hold3": ["type": "mouse", "btn": 2] as [String: Any],
    ]

    static let fallback: Shortcuts = Shortcuts(json: [
        "gestures": fallbackGestures,
        "profiles": [[
            "id": "generic", "name": "Genérico", "short": "···", "match": [String](),
            "buttons": [
                ["type": "mod", "key": "shift", "label": "⇧", "caption": "shift"],
                ["type": "mod", "key": "ctrl", "label": "⌃", "caption": "ctrl"],
                ["type": "mod", "key": "alt", "label": "⌥", "caption": "alt"],
                ["type": "mod", "key": "space", "label": "␣", "caption": "esp"],
                ["type": "sep"],
                ["type": "key", "keys": "ctrl+z", "label": "↶", "caption": "deshacer"],
                ["type": "key", "keys": "ctrl+shift+z", "label": "↷", "caption": "rehacer"],
                ["type": "key", "keys": "[", "label": "[", "caption": "pincel −"],
                ["type": "key", "keys": "]", "label": "]", "caption": "pincel +"],
                ["type": "key", "keys": "b", "label": "B", "caption": "pincel"],
                ["type": "key", "keys": "e", "label": "E", "caption": "goma"],
            ] as [[String: String]],
        ] as [String: Any]],
    ])!
}
