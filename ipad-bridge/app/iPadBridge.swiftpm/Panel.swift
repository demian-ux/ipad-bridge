import SwiftUI

/// Panel ⚙: presión del Pencil (presets suave/lineal/firme, gamma, mínimo, suavizado, con la presión en vivo y la
/// curva), previsualización del trazo (activa, color, grosor, duración), gestos (activos, radio de palma) y perfil
/// de la barra. Todo se guarda en Settings; la presión se manda al servidor como pencfg.
struct SettingsPanel: View {
    @ObservedObject var bridge: Bridge
    @ObservedObject var settings: Settings

    private let dim = Color(white: 0.73)
    private let faint = Color(white: 0.6)

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 6) {
                header("Presión del Pencil", first: true)
                HStack(spacing: 6) {
                    preset("Suave", 0.6)
                    preset("Lineal", 1)
                    preset("Firme", 1.6)
                }
                slider("Gamma", $settings.gamma, 0.3...2.5, 0.05) { String(format: "%.2f", $0) }
                slider("Mínimo", $settings.minPressure, 0...0.25, 0.005) { String(format: "%.3f", $0) }
                slider("Suavizado", $settings.smooth, 0...1, 0.05) { $0 > 0 ? String(format: "%.2f", $0) : "off" }
                HStack(alignment: .top, spacing: 10) {
                    PressureCurve(gamma: settings.gamma, minPressure: settings.minPressure, raw: bridge.penRaw)
                        .frame(width: 100, height: 100)
                        .background(Color.white.opacity(0.05), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                    VStack(alignment: .leading, spacing: 5) {
                        meter("iPad", bridge.penRaw, color: Color(red: 0.4, green: 0.67, blue: 1))
                        meter("a Windows", settings.outputPressure(bridge.penRaw), color: Color(red: 0.4, green: 1, blue: 0.4))
                        note("Dibujá con el Pencil para ver la presión en vivo. Menos de 1 = responde con poca fuerza; más de 1 = pide apretar.")
                    }
                }

                header("Previsualización del trazo")
                HStack(spacing: 8) {
                    Toggle("", isOn: $settings.preview).labelsHidden()
                    Text("Activa").foregroundStyle(dim)
                    Text("línea fina hasta que llega el video").foregroundStyle(faint).font(.system(size: 11))
                }
                HStack(spacing: 8) {
                    Text("Color").frame(width: 78, alignment: .leading).foregroundStyle(dim)
                    ColorPicker("", selection: colorBinding, supportsOpacity: false).labelsHidden().frame(width: 34)
                    Text("Grosor").foregroundStyle(dim)
                    Slider(value: $settings.previewWidth, in: 0.5...4, step: 0.25)
                    Text(String(format: "%.2f", settings.previewWidth)).frame(width: 40, alignment: .trailing).font(.system(size: 12, design: .monospaced))
                }
                slider("Duración", $settings.previewMs, 20...200, 5) { String(format: "%.0f ms", $0) }

                header("Gestos de dedos")
                HStack(spacing: 8) {
                    Toggle("", isOn: $settings.gestures).labelsHidden()
                    Text("Activos").foregroundStyle(dim)
                    Text(bridge.gestureConfig.summary).foregroundStyle(faint).font(.system(size: 11)).lineLimit(2)
                }
                slider("Radio palma", palmBinding, 0...400, 10) { String(format: "%.0f px", $0) }
                note("Los dedos a menos de ese radio de donde cae el Pencil se toman como palma. 0 = no distinguir.")

                header("Barra")
                HStack(spacing: 8) {
                    Text("App activa").frame(width: 78, alignment: .leading).foregroundStyle(dim)
                    Text("\(bridge.appExe.isEmpty ? "—" : bridge.appExe) → \(bridge.profile.name)\(bridge.manualProfile ? " (a mano)" : "")")
                        .lineLimit(1).minimumScaleFactor(0.7)
                }
                HStack(spacing: 8) {
                    Text("Perfil").frame(width: 78, alignment: .leading).foregroundStyle(dim)
                    actionButton("siguiente") { bridge.nextProfile() }
                    actionButton("automático") { bridge.autoProfile() }
                }
                note("Los perfiles y los gestos se editan en static/shortcuts.json de la PC; llegan a la app al reconectar el puente.")
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
        }
        .frame(width: 300, height: 640)
        .background(Color(red: 0.08, green: 0.08, blue: 0.094).opacity(0.92), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(Color.white.opacity(0.15)))
        .foregroundStyle(Color(white: 0.87))
        .font(.system(size: 13))
    }

    // MARK: - Enlaces

    private var colorBinding: Binding<Color> {
        Binding(get: { Color(uiColor: settings.previewUIColor) },
                set: { settings.previewColor = UIColor($0).hexString })
    }

    /// -1 en Settings = el radio del JSON; el deslizador muestra el efectivo y al moverlo fija el del panel.
    private var palmBinding: Binding<Double> {
        Binding(get: { settings.palmRadius >= 0 ? settings.palmRadius : bridge.gestureConfig.palmRadius },
                set: { settings.palmRadius = $0 })
    }

    // MARK: - Piezas

    private func header(_ t: String, first: Bool = false) -> some View {
        Text(t.uppercased()).font(.system(size: 11, weight: .bold)).kerning(1)
            .foregroundStyle(Color(red: 0.6, green: 0.67, blue: 0.73))
            .padding(.top, first ? 0 : 10).padding(.bottom, 2)
    }

    private func note(_ t: String) -> some View {
        Text(t).font(.system(size: 11)).foregroundStyle(faint).fixedSize(horizontal: false, vertical: true)
    }

    private func preset(_ name: String, _ gamma: Double) -> some View {
        let on = abs(settings.gamma - gamma) < 0.01
        return Button { settings.gamma = gamma } label: {
            Text(name).font(.system(size: 12, weight: .semibold))
                .frame(maxWidth: .infinity).padding(.vertical, 6)
                .background(on ? Color.yellow.opacity(0.9) : Color.white.opacity(0.08), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).strokeBorder(Color.white.opacity(on ? 0 : 0.2)))
                .foregroundStyle(on ? Color.black : Color(white: 0.93))
        }
        .buttonStyle(.plain)
    }

    private func actionButton(_ name: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(name).font(.system(size: 12, weight: .semibold))
                .frame(maxWidth: .infinity).padding(.vertical, 6)
                .background(Color.white.opacity(0.08), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).strokeBorder(Color.white.opacity(0.2)))
                .foregroundStyle(Color(white: 0.93))
        }
        .buttonStyle(.plain)
    }

    private func slider(_ name: String, _ v: Binding<Double>, _ range: ClosedRange<Double>, _ step: Double,
                        _ text: @escaping (Double) -> String) -> some View {
        HStack(spacing: 8) {
            Text(name).frame(width: 78, alignment: .leading).foregroundStyle(dim)
            Slider(value: v, in: range, step: step)
            Text(text(v.wrappedValue)).frame(width: 52, alignment: .trailing).font(.system(size: 12, design: .monospaced))
        }
    }

    private func meter(_ name: String, _ value: Double, color: Color) -> some View {
        HStack(spacing: 8) {
            Text(name).frame(width: 64, alignment: .leading).foregroundStyle(dim).font(.system(size: 12))
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.white.opacity(0.1))
                    Capsule().fill(color).frame(width: geo.size.width * CGFloat(max(0, min(1, value))))
                }
            }
            .frame(height: 10)
            Text(String(format: "%.2f", value)).frame(width: 34, alignment: .trailing).font(.system(size: 12, design: .monospaced))
        }
    }
}

/// Curva de presión: salida = max(mínimo, entrada^gamma), con el punto de la presión actual.
struct PressureCurve: View {
    let gamma: Double
    let minPressure: Double
    let raw: Double

    private func out(_ p: Double) -> Double { p > 0 ? max(minPressure, pow(p, gamma)) : 0 }

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width, h = geo.size.height
            Path { p in
                p.move(to: CGPoint(x: 0, y: h)); p.addLine(to: CGPoint(x: w, y: 0))
            }
            .stroke(Color.white.opacity(0.15), lineWidth: 1)
            Path { p in
                p.move(to: CGPoint(x: 0, y: h))
                for i in stride(from: 0.0, through: 1.0, by: 0.02) {
                    p.addLine(to: CGPoint(x: w * CGFloat(i), y: h - h * CGFloat(out(i))))
                }
            }
            .stroke(Color.yellow, lineWidth: 2)
            if raw > 0 {
                Circle().fill(Color(red: 0.4, green: 1, blue: 0.4)).frame(width: 7, height: 7)
                    .position(x: w * CGFloat(raw), y: h - h * CGFloat(out(raw)))
            }
        }
    }
}
