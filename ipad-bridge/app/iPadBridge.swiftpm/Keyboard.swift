import SwiftUI
import UIKit

/// Teclas de un teclado físico (UIPress) -> mensajes como los de la página: Intro, Tab, Esc, Borrar, Supr, flechas,
/// Inicio/Fin, Re/Av Pág y F1-F12 como {"ev":"key"}; cualquier tecla con Ctrl/Alt/Cmd como atajo (Cmd = Win);
/// el resto, si se pide, como texto {"ev":"text"} (cuando no hay campo de texto que lo reciba).
enum HardwareKeys {
    static let special: [UIKeyboardHIDUsage: String] = [
        .keyboardReturnOrEnter: "enter", .keypadEnter: "enter", .keyboardDeleteOrBackspace: "backspace", .keyboardTab: "tab",
        .keyboardEscape: "esc", .keyboardDeleteForward: "delete", .keyboardInsert: "insert", .keyboardHome: "home",
        .keyboardEnd: "end", .keyboardPageUp: "pageup", .keyboardPageDown: "pagedown", .keyboardLeftArrow: "left",
        .keyboardRightArrow: "right", .keyboardUpArrow: "up", .keyboardDownArrow: "down",
        .keyboardF1: "f1", .keyboardF2: "f2", .keyboardF3: "f3", .keyboardF4: "f4", .keyboardF5: "f5", .keyboardF6: "f6",
        .keyboardF7: "f7", .keyboardF8: "f8", .keyboardF9: "f9", .keyboardF10: "f10", .keyboardF11: "f11", .keyboardF12: "f12",
    ]
    static let editing: Set<String> = ["enter", "tab", "backspace"]

    /// textToo: las teclas sin modificador van como texto (vista sin campo de texto).
    /// skipEditing: Intro, Tab y Borrar sin modificador los maneja el campo (insertText/deleteBackward): no repetirlos.
    static func message(for press: UIPress, textToo: Bool, skipEditing: Bool = false) -> [String: Any]? {
        guard let key = press.key else { return nil }
        let f = key.modifierFlags
        var mods: [String] = []
        if f.contains(.control) { mods.append("ctrl") }
        if f.contains(.alternate) { mods.append("alt") }
        if f.contains(.command) { mods.append("win") }
        var name = special[key.keyCode]
        if skipEditing, mods.isEmpty, let n = name, editing.contains(n) { return nil }
        if name == nil && mods.isEmpty {
            guard textToo else { return nil }
            let t = key.characters
            // Solo modificadores (Shift, Bloq Mayús…) o caracteres de control: nada que mandar.
            guard !t.isEmpty, t.unicodeScalars.allSatisfy({ $0.value >= 0x20 }) else { return nil }
            return ["ev": "text", "text": t]
        }
        if name == nil {
            // Con Alt/Option el iPad cambia el carácter (option+a = å): usar la tecla sin modificadores.
            let base = key.charactersIgnoringModifiers.lowercased()
            if base == " " {
                name = "space"
            } else {
                guard base.count == 1, let sc = base.unicodeScalars.first, sc.value >= 0x21 else { return nil }
                name = base
            }
        }
        if f.contains(.shift) { mods.append("shift") }
        return ["ev": "key", "keys": (mods + [name ?? ""]).joined(separator: "+")]
    }
}

/// Campo invisible que muestra el teclado en pantalla del iPad (botón ⌨) y recibe también el teclado físico
/// mientras está activo. Letras y signos van como texto; Intro y Borrar por insertText/deleteBackward; lo demás
/// por pressesBegan (HardwareKeys). `on` sigue a bridge.keyboardOn.
struct KeyboardField: UIViewRepresentable {
    let bridge: Bridge
    let on: Bool

    func makeUIView(context: Context) -> KeyInputView {
        let v = KeyInputView()
        v.bridge = bridge
        return v
    }

    func updateUIView(_ v: KeyInputView, context: Context) {
        v.bridge = bridge
        if on && !v.isFirstResponder {
            _ = v.becomeFirstResponder()
        } else if !on && v.isFirstResponder {
            _ = v.resignFirstResponder()
        }
    }
}

final class KeyInputView: UIView, UIKeyInput {
    weak var bridge: Bridge?
    private var suppressUntil: TimeInterval = 0

    // UITextInputTraits: sin autocorrección ni mayúsculas automáticas, como el campo de la página.
    var autocorrectionType: UITextAutocorrectionType = .no
    var autocapitalizationType: UITextAutocapitalizationType = .none
    var spellCheckingType: UITextSpellCheckingType = .no
    var smartQuotesType: UITextSmartQuotesType = .no
    var smartDashesType: UITextSmartDashesType = .no
    var smartInsertDeleteType: UITextSmartInsertDeleteType = .no
    var keyboardAppearance: UIKeyboardAppearance = .dark

    override var canBecomeFirstResponder: Bool { true }
    var hasText: Bool { false }

    func insertText(_ text: String) {
        if ProcessInfo.processInfo.systemUptime < suppressUntil { return }   // el carácter que acompaña a un atajo ya mandado
        if text == "\n" {
            bridge?.sendInput(["ev": "key", "keys": "enter"])
        } else if text == "\t" {
            bridge?.sendInput(["ev": "key", "keys": "tab"])
        } else if !text.isEmpty {
            bridge?.sendInput(["ev": "text", "text": text])
        }
    }

    func deleteBackward() {
        bridge?.sendInput(["ev": "key", "keys": "backspace"])
    }

    override func pressesBegan(_ presses: Set<UIPress>, with event: UIPressesEvent?) {
        var handled = false
        for p in presses {
            if let m = HardwareKeys.message(for: p, textToo: false, skipEditing: true) {
                bridge?.sendInput(m); handled = true
            }
        }
        if handled { suppressUntil = ProcessInfo.processInfo.systemUptime + 0.05 }
        super.pressesBegan(presses, with: event)
    }

    override func resignFirstResponder() -> Bool {
        let r = super.resignFirstResponder()
        if r, let b = bridge {
            // Cerrado desde la tecla del teclado o desde ⌨: la vista del video vuelve a recibir el teclado físico.
            DispatchQueue.main.async {
                if b.keyboardOn { b.keyboardOn = false }
                b.onKeyboardClosed?()
            }
        }
        return r
    }
}
