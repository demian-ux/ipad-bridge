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
    @StateObject private var discovery = Discovery()
    // Lado de la barra de teclas: "bottom" (horizontal, abajo; no tapa la barra de herramientas de Photoshop, que va a
    // la izquierda), "left" o "right" (vertical). Toque largo en ≡ la rota: abajo → derecha → izquierda.
    @AppStorage("keyBarPos") private var keyBarPos = "bottom"
    @State private var keyBarHidden = false

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            VideoView(bridge: bridge).ignoresSafeArea()
            if !bridge.status.isEmpty {
                ConnectPanel(bridge: bridge, discovery: discovery)
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
        }
        .onAppear { bridge.start(); discovery.start() }
        .onDisappear { bridge.stop(); discovery.stop() }
    }

    @ViewBuilder private var keyBar: some View {
        if keyBarHidden {
            KeyBarTab(pos: keyBarPos) { keyBarHidden = false }
        } else {
            KeyBar(bridge: bridge, pos: $keyBarPos, hidden: $keyBarHidden)
        }
    }
}

// MARK: - Conexión

/// Lo que se ve mientras no hay video: estado, las PCs que publican `_ipadbridge._tcp` (tocar una le pide por red que
/// se conecte acá), una IP a mano para redes sin Bonjour, y el campo del código de 6 dígitos la primera vez con cada PC.
/// Por USB no hay nada que tocar: el puente de la PC se conecta solo.
struct ConnectPanel: View {
    @ObservedObject var bridge: Bridge
    @ObservedObject var discovery: Discovery
    @State private var code = ""
    @State private var manualIP = ""

    var body: some View {
        VStack(spacing: 10) {
            Text("iPad Bridge").font(.title2).bold()
            Text(bridge.status).foregroundStyle(.secondary).multilineTextAlignment(.center)
            if bridge.needCode, let pc = bridge.selectedPC {
                codeEntry(pc)
            } else {
                pcList
            }
            if !bridge.connectError.isEmpty {
                Text(bridge.connectError).font(.footnote).foregroundStyle(.red)
            }
            Text("Por USB la PC se conecta sola (puerto \(Bridge.port)). Este iPad: \(bridge.addresses)")
                .font(.footnote).foregroundStyle(.tertiary).multilineTextAlignment(.center)
        }
        .padding(24)
        .frame(maxWidth: 520)
        .background(Color.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }

    @ViewBuilder private var pcList: some View {
        if let pc = bridge.selectedPC {
            HStack {
                Text("PC elegida: \(pc.name) (\(pc.ip))").font(.callout)
                if bridge.requesting { ProgressView().controlSize(.small) }
                Button("Otra PC") { bridge.forgetSelection() }.buttonStyle(.bordered)
            }
        }
        if discovery.pcs.isEmpty {
            Text("Buscando PCs en la red (Bonjour)…").font(.callout).foregroundStyle(.secondary)
        } else {
            ForEach(discovery.pcs) { pc in
                Button {
                    bridge.connect(to: pc)
                } label: {
                    HStack {
                        Image(systemName: "desktopcomputer")
                        Text(pc.name).bold()
                        Text(pc.ip).foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .tint(bridge.selectedPC?.id == pc.id ? .blue : .gray)
            }
        }
        HStack {
            TextField("IP de la PC (sin Bonjour)", text: $manualIP)
                .textFieldStyle(.roundedBorder).keyboardType(.decimalPad).frame(width: 220)
            Button("Conectar") {
                let ip = manualIP.trimmingCharacters(in: .whitespaces)
                if !ip.isEmpty { bridge.connect(to: PC.manual(ip)) }
            }
            .buttonStyle(.bordered)
        }
    }

    private func codeEntry(_ pc: PC) -> some View {
        VStack(spacing: 8) {
            Text("Código de emparejamiento de \(pc.name)").font(.callout)
            Text("Está en la página de estado de la PC (http://localhost/). Cambia después de cada uso.")
                .font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
            HStack {
                TextField("000000", text: $code)
                    .textFieldStyle(.roundedBorder).keyboardType(.numberPad)
                    .font(.system(size: 28, weight: .bold, design: .monospaced)).frame(width: 180)
                Button("Emparejar") {
                    let digits = code.filter { $0.isNumber }
                    if digits.count == 6 { bridge.connect(to: pc, code: digits); code = "" }
                }
                .buttonStyle(.borderedProminent)
                Button("Cancelar") { bridge.forgetSelection() }.buttonStyle(.bordered)
            }
        }
    }
}

// MARK: - Barra de teclas

/// Tira estrecha y semitransparente: modificadores que se mantienen mientras se toca el botón (Shift = línea recta,
/// Ctrl, Alt = cuentagotas, Espacio = mano) y pulsaciones (deshacer, rehacer, tamaño de pincel, B, E). Horizontal
/// abajo o vertical en un borde; toque largo en ≡ la rota (abajo → derecha → izquierda); el ojo tachado la oculta
/// (queda una pestaña para volver).
struct KeyBar: View {
    let bridge: Bridge
    @Binding var pos: String
    @Binding var hidden: Bool

    private var horizontal: Bool { pos == "bottom" }

    var body: some View {
        let layout = horizontal ? AnyLayout(HStackLayout(spacing: 4)) : AnyLayout(VStackLayout(spacing: 4))
        layout {
            Image(systemName: "line.3.horizontal")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(.white.opacity(0.5))
                .frame(width: horizontal ? 24 : 44, height: horizontal ? 44 : 24)
                .contentShape(Rectangle())
                .onLongPressGesture(minimumDuration: 0.5) {
                    pos = pos == "bottom" ? "right" : (pos == "right" ? "left" : "bottom")
                }
            HoldKey(bridge: bridge, key: "shift", label: "⇧", caption: "shift")
            HoldKey(bridge: bridge, key: "ctrl", label: "⌃", caption: "ctrl")
            HoldKey(bridge: bridge, key: "alt", label: "⌥", caption: "alt")
            HoldKey(bridge: bridge, key: "space", label: "␣", caption: "esp")
            KeyDivider(horizontal: horizontal)
            TapKey(bridge: bridge, keys: "ctrl+z", symbol: "arrow.uturn.backward", caption: "deshacer")
            TapKey(bridge: bridge, keys: "ctrl+shift+z", symbol: "arrow.uturn.forward", caption: "rehacer")
            TapKey(bridge: bridge, keys: "[", label: "[", caption: "pincel −")
            TapKey(bridge: bridge, keys: "]", label: "]", caption: "pincel +")
            TapKey(bridge: bridge, keys: "b", label: "B", caption: "pincel") { bridge.penHud = "" }
            TapKey(bridge: bridge, keys: "e", label: "E", caption: "goma") { bridge.penHud = "GOMA" }
            KeyDivider(horizontal: horizontal)
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

/// Separador: una línea fina, horizontal en la barra vertical y vertical en la barra horizontal.
struct KeyDivider: View {
    var horizontal = false

    var body: some View {
        Rectangle().fill(Color.white.opacity(0.15))
            .frame(width: horizontal ? 1 : 32, height: horizontal ? 32 : 1)
            .padding(horizontal ? .horizontal : .vertical, 1)
    }
}
