import SwiftUI

@main
struct MyApp: App {
    @StateObject private var bridge = Bridge()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(bridge)
                .preferredColorScheme(.dark)
                .statusBarHidden(true)
                .persistentSystemOverlays(.hidden)
        }
    }
}

struct ContentView: View {
    @EnvironmentObject var bridge: Bridge
    // Lado de la barra de teclas: "bottom" (horizontal, abajo; no tapa la barra de herramientas de Photoshop, que va a
    // la izquierda), "left" o "right" (vertical). Toque largo en ≡ la rota: abajo → derecha → izquierda.
    @AppStorage("keyBarPos") private var keyBarPos = "bottom"
    @State private var keyBarHidden = false

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            VideoView(bridge: bridge).ignoresSafeArea()
            if !bridge.status.isEmpty {
                VStack(spacing: 8) {
                    Text("iPad Bridge").font(.title2).bold()
                    Text(bridge.status).foregroundStyle(.secondary)
                    Text("Escuchando en el puerto \(Bridge.port). Por USB: la PC se conecta sola. Por red: \(bridge.addresses)")
                        .font(.footnote).foregroundStyle(.tertiary).multilineTextAlignment(.center)
                }
                .padding(24)
                .allowsHitTesting(false)
            }
            VStack {
                HStack {
                    if !bridge.penHud.isEmpty {
                        Text(bridge.penHud).font(.system(size: 11, weight: .bold, design: .monospaced))
                            .foregroundStyle(.black).padding(.horizontal, 6).padding(.vertical, 3)
                            .background(.yellow.opacity(0.8), in: Capsule()).padding(8)
                    }
                    Spacer()
                    Text(bridge.hud).font(.system(size: 11, design: .monospaced)).foregroundStyle(.green.opacity(0.7)).padding(8)
                }
                Spacer()
            }
            .allowsHitTesting(false)
            // Barra de teclas (estilo ExpressKeys). Es una vista SwiftUI encima del video, fuera de TouchVideoView:
            // así un dedo la usa mientras el Pencil dibuja (touchesBegan ignora los dedos con penDown) y el Pencil
            // sobre un botón pulsa el botón en vez de trazar.
            if keyBarPos == "bottom" {
                VStack(spacing: 0) {
                    Spacer()
                    HStack(spacing: 0) {
                        Spacer()
                        keyBar
                        Spacer()
                    }
                }
                .padding(.bottom, 6)
            } else {
                HStack(spacing: 0) {
                    if keyBarPos == "right" { Spacer() }
                    keyBar
                    if keyBarPos != "right" { Spacer() }
                }
                .padding(.horizontal, 6)
            }
            // Panel ⚙, pegado a la barra.
            if bridge.panelOpen && !keyBarHidden {
                if keyBarPos == "bottom" {
                    VStack(spacing: 0) {
                        Spacer()
                        HStack(spacing: 0) { Spacer(); SettingsPanel(bridge: bridge, settings: bridge.settings) }
                    }
                    .padding(.trailing, 12).padding(.bottom, 64)
                } else {
                    HStack(spacing: 0) {
                        if keyBarPos == "right" { Spacer() }
                        SettingsPanel(bridge: bridge, settings: bridge.settings)
                        if keyBarPos != "right" { Spacer() }
                    }
                    .padding(.horizontal, 64)
                }
            }
            // Teclado: campo invisible que muestra el teclado del iPad y recibe el físico; cartel mientras está activo.
            KeyboardField(bridge: bridge, on: bridge.keyboardOn)
                .frame(width: 1, height: 1).opacity(0.02).allowsHitTesting(false)
            if bridge.keyboardOn {
                VStack {
                    Spacer()
                    Text("teclado → PC · tocá ⌨ o la tecla del teclado para cerrar")
                        .font(.system(size: 12, weight: .semibold)).foregroundStyle(.black)
                        .padding(.horizontal, 12).padding(.vertical, 5)
                        .background(Color.yellow.opacity(0.85), in: Capsule())
                        .padding(.bottom, keyBarPos == "bottom" ? 62 : 10)
                }
                .allowsHitTesting(false)
            }
        }
        .onAppear { bridge.start() }
        .onDisappear { bridge.stop() }
    }

    @ViewBuilder private var keyBar: some View {
        if keyBarHidden {
            KeyBarTab(pos: keyBarPos) { keyBarHidden = false }
        } else {
            KeyBar(bridge: bridge, pos: $keyBarPos, hidden: $keyBarHidden)
        }
    }
}

// MARK: - Barra de teclas

/// Tira estrecha y semitransparente armada desde el perfil activo de shortcuts.json (el que manda la PC según la
/// aplicación en primer plano, o el elegido a mano tocando la etiqueta): modificadores que se mantienen mientras se
/// toca el botón (Shift = línea recta, Ctrl, Alt = cuentagotas, Espacio = mano), pulsaciones (deshacer, rehacer, [ ]…),
/// botones que alternan dos atajos (E/B) y botones del mouse (mantenidos, el Pencil actúa como ese botón; tocados
/// solos, clic). Fijos al final: ⌨ teclado, ⚙ ajustes, ocultar. Horizontal abajo o vertical en un borde; toque largo
/// en ≡ la rota (abajo → derecha → izquierda).
struct KeyBar: View {
    @ObservedObject var bridge: Bridge
    @Binding var pos: String
    @Binding var hidden: Bool

    private var horizontal: Bool { pos == "bottom" }

    var body: some View {
        let layout = horizontal ? AnyLayout(HStackLayout(spacing: 4)) : AnyLayout(VStackLayout(spacing: 4))
        let profile = bridge.profile
        layout {
            Image(systemName: "line.3.horizontal")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(.white.opacity(0.5))
                .frame(width: horizontal ? 24 : 44, height: horizontal ? 44 : 24)
                .contentShape(Rectangle())
                .onLongPressGesture(minimumDuration: 0.5) {
                    pos = pos == "bottom" ? "right" : (pos == "right" ? "left" : "bottom")
                }
            // Etiqueta del perfil: tocarla pasa al siguiente (fijado a mano hasta el próximo cambio de aplicación).
            Button { bridge.nextProfile() } label: {
                Text(profile.short)
                    .font(.system(size: 11, weight: .bold)).kerning(0.5)
                    .foregroundStyle(Color(red: 0.8, green: 0.87, blue: 0.93))
                    .lineLimit(1).minimumScaleFactor(0.6)
                    .frame(width: horizontal ? 34 : 44, height: horizontal ? 44 : 22)
                    .background(Color(red: 0.47, green: 0.7, blue: 1).opacity(bridge.manualProfile ? 0.45 : 0.25),
                                in: RoundedRectangle(cornerRadius: 9, style: .continuous))
            }
            .buttonStyle(KeyCapStyle())
            ForEach(Array(profile.buttons.enumerated()), id: \.offset) { item in
                let b = item.element
                switch b.type {
                case "sep":
                    KeyDivider(horizontal: horizontal)
                case "mod":
                    HoldKey(bridge: bridge, key: b.key, label: b.title(), caption: b.caption)
                case "key":
                    TapKey(bridge: bridge, keys: b.firstKeys, label: b.title(), caption: b.caption)
                case "toggle":
                    ToggleKey(bridge: bridge, action: b)
                case "mouse":
                    MouseKey(bridge: bridge, action: b)
                default:
                    EmptyView()
                }
            }
            KeyDivider(horizontal: horizontal)
            Button { bridge.keyboardOn.toggle() } label: { KeyCap(symbol: "keyboard", caption: "teclado", active: bridge.keyboardOn) }
                .buttonStyle(KeyCapStyle())
            Button { bridge.panelOpen.toggle() } label: { KeyCap(symbol: "gearshape", caption: "ajustes", active: bridge.panelOpen) }
                .buttonStyle(KeyCapStyle())
            Button { hidden = true; bridge.panelOpen = false } label: { KeyCap(symbol: "eye.slash", caption: "ocultar") }
                .buttonStyle(KeyCapStyle())
        }
        .id(profile.id)   // cambio de perfil: botones nuevos, estado (toggle, modificadores) desde cero
        .padding(4)
        .background(Color.black.opacity(0.45), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(Color.white.opacity(0.12)))
    }
}

/// Pestaña que queda en el borde cuando la barra está oculta.
struct KeyBarTab: View {
    let pos: String
    let show: () -> Void

    var body: some View {
        Button(action: show) {
            Image(systemName: pos == "bottom" ? "chevron.up" : (pos == "right" ? "chevron.left" : "chevron.right"))
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(.white.opacity(0.6))
                .frame(width: pos == "bottom" ? 56 : 18, height: pos == "bottom" ? 18 : 56)
                .background(Color.black.opacity(0.4), in: Capsule())
        }
        .buttonStyle(.plain)
    }
}

/// Modificador mantenido: `mod down` al apoyar el dedo, `mod up` al levantarlo (o si la barra desaparece).
/// DragGesture con distancia mínima 0 empieza en el mismo instante del toque, y cada tecla tiene su gesto,
/// así se pueden mantener dos a la vez.
struct HoldKey: View {
    let bridge: Bridge
    let key: String
    let label: String
    var caption: String? = nil
    @State private var down = false

    var body: some View {
        KeyCap(label: label, caption: caption, active: down)
            .gesture(DragGesture(minimumDistance: 0)
                .onChanged { _ in
                    if !down { down = true; bridge.sendInput(["ev": "mod", "key": key, "down": true]) }
                }
                .onEnded { _ in release() })
            .onDisappear { release() }
    }

    private func release() {
        guard down else { return }
        down = false
        bridge.sendInput(["ev": "mod", "key": key, "down": false])
    }
}

/// Pulsación: manda el atajo al apoyar (como una ExpressKey), no al soltar.
struct TapKey: View {
    let bridge: Bridge
    let keys: String
    var label: String? = nil
    var symbol: String? = nil
    var caption: String? = nil
    @State private var down = false

    var body: some View {
        KeyCap(label: label, symbol: symbol, caption: caption, active: down)
            .gesture(DragGesture(minimumDistance: 0)
                .onChanged { _ in
                    if !down {
                        down = true
                        bridge.sendInput(["ev": "key", "keys": keys])
                    }
                }
                .onEnded { _ in down = false })
    }
}

/// Alterna dos atajos: keys[0] al primer toque (iluminado = el primero activo, p. ej. la goma), keys[1] al siguiente.
struct ToggleKey: View {
    let bridge: Bridge
    let action: ShortcutAction
    @State private var on = false
    @State private var pressed = false

    var body: some View {
        KeyCap(label: action.title(on: on), caption: action.caption, active: on)
            .opacity(pressed ? 0.5 : 1)
            .gesture(DragGesture(minimumDistance: 0)
                .onChanged { _ in
                    if !pressed {
                        pressed = true
                        on.toggle()
                        bridge.sendInput(["ev": "key", "keys": on ? action.firstKeys : (action.secondKeys ?? action.firstKeys)])
                    }
                }
                .onEnded { _ in pressed = false })
    }
}

/// Botón del mouse (1 medio, 2 derecho): mantenido, el Pencil actúa como ese botón (mover la vista, menú de pinceles);
/// soltado sin haber dibujado, clic de ese botón donde está el cursor.
struct MouseKey: View {
    let bridge: Bridge
    let action: ShortcutAction
    @State private var down = false

    var body: some View {
        KeyCap(label: action.title(), caption: action.caption, active: down)
            .gesture(DragGesture(minimumDistance: 0)
                .onChanged { _ in
                    if !down {
                        down = true
                        bridge.barMouseBtn = action.btn
                        bridge.barMouseUsed = false
                    }
                }
                .onEnded { _ in release() })
            .onDisappear { release() }
    }

    private func release() {
        guard down else { return }
        down = false
        if !bridge.barMouseUsed && !bridge.penDown { bridge.clickAtCursor(action.btn) }
        bridge.barMouseBtn = nil
    }
}

struct KeyCap: View {
    var label: String? = nil
    var symbol: String? = nil
    var caption: String? = nil
    var active = false

    var body: some View {
        VStack(spacing: 1) {
            if let symbol = symbol {
                Image(systemName: symbol).font(.system(size: 16, weight: .medium))
            }
            if let label = label {
                Text(label).font(.system(size: caption == nil ? 19 : 17, weight: .semibold, design: .rounded))
                    .lineLimit(1).minimumScaleFactor(0.6)
            }
            if let caption = caption {
                Text(caption).font(.system(size: 8, weight: .medium)).opacity(0.7).lineLimit(1).minimumScaleFactor(0.7)
            }
        }
        .foregroundStyle(active ? Color.black : Color.white.opacity(0.9))
        .frame(width: 44, height: 44)
        .background(active ? Color.yellow.opacity(0.9) : Color.white.opacity(0.10),
                    in: RoundedRectangle(cornerRadius: 9, style: .continuous))
        .contentShape(Rectangle())
    }
}

struct KeyCapStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .opacity(configuration.isPressed ? 0.5 : 1)
            .scaleEffect(configuration.isPressed ? 0.94 : 1)
    }
}

/// Separador: una línea fina, horizontal en la barra vertical y vertical en la barra horizontal.
struct KeyDivider: View {
    var horizontal = false

    var body: some View {
        Rectangle().fill(Color.white.opacity(0.15))
            .frame(width: horizontal ? 1 : 32, height: horizontal ? 32 : 1)
            .padding(horizontal ? .horizontal : .vertical, 1)
    }
}
