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
    @AppStorage("keyBarRight") private var keyBarRight = false   // lado de la barra de teclas (toque largo en ≡)
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
            HStack(spacing: 0) {
                if keyBarRight { Spacer() }
                if keyBarHidden {
                    KeyBarTab(right: keyBarRight) { keyBarHidden = false }
                } else {
                    KeyBar(bridge: bridge, right: $keyBarRight, hidden: $keyBarHidden)
                }
                if !keyBarRight { Spacer() }
            }
            .padding(.horizontal, 6)
        }
        .onAppear { bridge.start() }
        .onDisappear { bridge.stop() }
    }
}

// MARK: - Barra lateral de teclas

/// Tira vertical estrecha y semitransparente: modificadores que se mantienen mientras se toca el botón
/// (Shift = línea recta, Ctrl, Alt = cuentagotas, Espacio = mano) y pulsaciones (deshacer, rehacer, tamaño de
/// pincel, B, E). Toque largo en ≡ la cambia de lado; el ojo tachado la oculta (queda una pestaña para volver).
struct KeyBar: View {
    let bridge: Bridge
    @Binding var right: Bool
    @Binding var hidden: Bool

    var body: some View {
        VStack(spacing: 4) {
            Image(systemName: "line.3.horizontal")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(.white.opacity(0.5))
                .frame(width: 44, height: 24)
                .contentShape(Rectangle())
                .onLongPressGesture(minimumDuration: 0.5) { right.toggle() }
            HoldKey(bridge: bridge, key: "shift", label: "⇧", caption: "shift")
            HoldKey(bridge: bridge, key: "ctrl", label: "⌃", caption: "ctrl")
            HoldKey(bridge: bridge, key: "alt", label: "⌥", caption: "alt")
            HoldKey(bridge: bridge, key: "space", label: "␣", caption: "esp")
            KeyDivider()
            TapKey(bridge: bridge, keys: "ctrl+z", symbol: "arrow.uturn.backward", caption: "deshacer")
            TapKey(bridge: bridge, keys: "ctrl+shift+z", symbol: "arrow.uturn.forward", caption: "rehacer")
            TapKey(bridge: bridge, keys: "[", label: "[", caption: "pincel −")
            TapKey(bridge: bridge, keys: "]", label: "]", caption: "pincel +")
            TapKey(bridge: bridge, keys: "b", label: "B", caption: "pincel") { bridge.penHud = "" }
            TapKey(bridge: bridge, keys: "e", label: "E", caption: "goma") { bridge.penHud = "GOMA" }
            KeyDivider()
            Button { hidden = true } label: { KeyCap(symbol: "eye.slash", caption: "ocultar") }
                .buttonStyle(KeyCapStyle())
        }
        .padding(4)
        .background(Color.black.opacity(0.45), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(Color.white.opacity(0.12)))
    }
}

/// Pestaña que queda en el borde cuando la barra está oculta.
struct KeyBarTab: View {
    let right: Bool
    let show: () -> Void

    var body: some View {
        Button(action: show) {
            Image(systemName: right ? "chevron.left" : "chevron.right")
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(.white.opacity(0.6))
                .frame(width: 18, height: 56)
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
    let caption: String
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
    var after: (() -> Void)? = nil
    @State private var down = false

    var body: some View {
        KeyCap(label: label, symbol: symbol, caption: caption, active: down)
            .gesture(DragGesture(minimumDistance: 0)
                .onChanged { _ in
                    if !down {
                        down = true
                        bridge.sendInput(["ev": "key", "keys": keys])
                        after?()
                    }
                }
                .onEnded { _ in down = false })
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

struct KeyDivider: View {
    var body: some View {
        Rectangle().fill(Color.white.opacity(0.15)).frame(width: 32, height: 1).padding(.vertical, 1)
    }
}
