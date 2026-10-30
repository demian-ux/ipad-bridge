import Foundation
import Network
import CoreMedia
import AVFoundation
import UIKit

// Protocolo por TCP (la PC se conecta al iPad, por USB vía usbmux o por IP):
//   cada mensaje = u32 big-endian (largo) + u8 tipo + payload
//   tipo 1 PC->iPad video:  u8 keyframe + f64 timestamp + datos H.264 en formato AVCC (como los da WebCodecs)
//   tipo 2 PC->iPad config: u8 códec (1 = avcC/H.264, 2 = hvcC/HEVC) + record con los parameter sets
//   tipo 3 PC->iPad imagen fija: PNG con los píxeles exactos (pantalla quieta); se muestra encima del video
//   tipo 4 PC->iPad still-clear: volver a mostrar el video
//   tipo 16 iPad->PC input: JSON. Dedos: {"ev":"move|down|up|scroll","x":0..1,"y":0..1,"btn":0|2,"dy":..,"dx":..}
//     Pencil ("pen":1): {"ev":"hover|down|up","x","y","p":presión 0..1,"tx","ty":inclinación en grados},
//     {"ev":"moves","pts":[[x,y,p,tx,ty],...]} (toques coalescidos), {"ev":"leave"}, {"ev":"eraser","on":bool}
//     Barra de teclas (sin "pen"): {"ev":"key","keys":"ctrl+z"} pulsación, {"ev":"mod","key":"shift|ctrl|alt|space","down":bool}
//   tipo 17 iPad->PC need-key: pedir keyframe
//   tipo 18 iPad->PC JSON de control: {"type":"ping","t":reloj iPad ms,"q","d","rtt"} cada 2 s, {"type":"stats",...} cada 5 s,
//     {"type":"sleeping"} al irse al fondo (la PC detiene la captura), {"type":"wake"} al volver, {"type":"closing"} al cerrar
//   tipo 19 PC->iPad JSON de control: {"type":"pong","t","mt":reloj PC ms,"inp50","inp95",...}, {"type":"welcome",name,id},
//     {"type":"transport","transport":"usb|net"} (el puente migró la sesión), {"type":"app",exe,title} (ventana activa)
//   tipo 0 PC->iPad latido cada 2 s: se devuelve tal cual (tipo 0, sin payload). 5 s sin bytes de la PC = conexión muerta.
//   Reloj sincronizado estilo NTP (offset de la muestra de menor RTT de las últimas 15); el input lleva "t" en el reloj
//   de la PC para medir la latencia de input, y cada frame trae ts (f64, reloj de la PC en ms al salir del encoder).
// Por red la PC no sabe dónde está el iPad: la app la encuentra por Bonjour (Discovery.swift) y le pide por http
// (GET /connect) que su puente se conecte acá, con el token guardado o con el código de 6 dígitos que muestra la PC.

final class Bridge: ObservableObject {
    static let port: UInt16 = 7777

    @Published var status = "Esperando a la PC…"
    @Published var hud = ""
    @Published var addresses = ""
    @Published var penHud = ""      // "GOMA" mientras el doble toque del Pencil tiene la goma activa
    @Published var pcName = ""      // nombre de la PC (welcome)
    @Published var transport = ""   // "usb" o "net" según el puente
    // Conexión por red pedida desde la app (/connect): PC elegida, si la PC pide el código y el último error.
    @Published var selectedPC: PC?
    @Published var needCode = false
    @Published var connectError = ""
    @Published var requesting = false

    private var listener: NWListener?
    private var conn: NWConnection?
    private var lastRx = Date()
    private var inBackground = false
    private var connectRetry = 0
    private var connectWork: DispatchWorkItem?
    private let queue = DispatchQueue(label: "bridge.net")
    private var format: CMVideoFormatDescription?
    private var nalLength = 4
    private var waitingKey = true
    private var frames = 0
    private var bytes = 0
    private var statsTimer: Timer?
    // Medición: reloj sincronizado con la PC y latencia de llegada de los frames (encoder -> app, antes de decodificar).
    private var clockSamples: [(rtt: Double, offset: Double)] = []
    private var clockOffset: Double?           // reloj PC - reloj iPad, en ms
    private var lastRtt: Double?
    private var inp50: Double?, inp95: Double?
    private var arrival: [Double] = []         // ms entre ts del frame y su llegada a la app
    private var tick = 0

    private var localMs: Double { ProcessInfo.processInfo.systemUptime * 1000 }
    /// Reloj de la PC estimado (ms), o nil si todavía no hubo pong.
    var serverNow: Double? { clockOffset.map { localMs + $0 } }

    /// La vista de video se registra acá para recibir los sample buffers y las imágenes fijas.
    var onSample: ((CMSampleBuffer) -> Void)?
    var onFlush: (() -> Void)?
    var onStill: ((Data?) -> Void)?   // PNG, o nil para volver al video

    func start() {
        guard listener == nil else { return }
        addresses = localIPs().joined(separator: "  ")
        openListener()
        observeLifecycle()
        if let id = UserDefaults.standard.string(forKey: "lastPC"), let pc = storedPC(id) {
            selectedPC = pc                       // la última PC usada por red: pedirle conexión apenas abre la app
            scheduleConnectRequest(after: 1)
        }
        statsTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            guard let s = self else { return }
            // Liveness: la PC manda un latido cada 2 s (y video); 5 s sin nada = el cable se soltó o el puente murió.
            // Se corta acá para que el puente, al volver, encuentre el puerto libre (no sobre una conexión zombi).
            if let c = s.conn, Date().timeIntervalSince(s.lastRx) > 5 {
                DispatchQueue.main.async { s.status = "La PC dejó de responder; esperando que vuelva…" }
                c.cancel()
            }
            let mbps = Double(s.bytes * 8) / 1e6
            let a = s.arrival.sorted()
            let p50 = a.isEmpty ? -1 : a[a.count / 2], p95 = a.isEmpty ? -1 : a[min(a.count - 1, a.count * 95 / 100)]
            s.hud = s.conn == nil ? "" : String(format: "%d fps · %.1f Mbps · llegada %.0f/%.0f ms · in %.0f/%.0f · rtt %.0f",
                                                s.frames, mbps, p50, p95, s.inp50 ?? -1, s.inp95 ?? -1, s.lastRtt ?? -1)
            s.tick += 1
            if s.tick % 2 == 0 {   // ping cada 2 s: reloj + cola (la capa no la expone: 0) + descartes (0) + último RTT
                var m: [String: Any] = ["type": "ping", "t": s.localMs, "q": 0, "d": 0]
                if let r = s.lastRtt { m["rtt"] = r }
                s.sendJSON(m)
            }
            if s.tick % 5 == 0 {   // stats cada 5 s al log de la PC y a pc.html
                s.sendJSON(["type": "stats", "fps": s.frames, "mbps": (mbps * 10).rounded() / 10, "e2e50": p50.rounded(), "e2e95": p95.rounded(),
                            "rtt": (s.lastRtt ?? -1).rounded(), "q": 0, "drops": 0, "transport": "app", "note": "llegada, no presentación"])
                s.arrival.removeAll(keepingCapacity: true)
            }
            s.frames = 0; s.bytes = 0
        }
    }

    /// Abre el puerto; si está ocupado (otra instancia de la app todavía viva), reintenta cada 2 s hasta lograrlo.
    private func openListener() {
        do {
            let params = NWParameters.tcp
            params.allowLocalEndpointReuse = true
            if let tcp = params.defaultProtocolStack.transportProtocol as? NWProtocolTCP.Options { tcp.noDelay = true }
            let l = try NWListener(using: params, on: NWEndpoint.Port(rawValue: Bridge.port)!)
            l.newConnectionHandler = { [weak self] c in self?.accept(c) }
            l.stateUpdateHandler = { [weak self] st in
                guard let self = self else { return }
                switch st {
                case .ready:
                    DispatchQueue.main.async { if self.conn == nil { self.status = "Esperando a la PC…" } }
                case .failed(let e):
                    DispatchQueue.main.async { self.status = "Puerto \(Bridge.port) ocupado (\(e)). Cerrá la otra copia de la app; reintento…" }
                    l.cancel()
                    if self.listener === l { self.listener = nil }
                    self.queue.asyncAfter(deadline: .now() + 2) { [weak self] in
                        guard let self = self, self.listener == nil else { return }
                        self.openListener()
                    }
                default: break
                }
            }
            l.start(queue: queue)
            listener = l
        } catch {
            DispatchQueue.main.async { self.status = "No pude escuchar en \(Bridge.port): \(error)" }
            queue.asyncAfter(deadline: .now() + 2) { [weak self] in
                guard let self = self, self.listener == nil else { return }
                self.openListener()
            }
        }
    }

    func stop() {
        sendJSON(["type": "closing"])
        conn?.cancel(); conn = nil
        listener?.cancel(); listener = nil
        statsTimer?.invalidate(); statsTimer = nil
        connectWork?.cancel(); connectWork = nil
    }

    // MARK: - Fondo / primer plano

    /// Al irse al fondo avisa `sleeping` (la PC detiene la captura si no queda otro visor); al volver, `wake` y pide un
    /// keyframe (el decodificador perdió el hilo mientras tanto). iOS suele matar el TCP de una app suspendida: si la
    /// conexión murió, el puente de la PC la vuelve a abrir solo (por USB) o la app vuelve a pedir /connect (por red).
    private func observeLifecycle() {
        let nc = NotificationCenter.default
        nc.addObserver(forName: UIApplication.didEnterBackgroundNotification, object: nil, queue: nil) { [weak self] _ in
            guard let self = self else { return }
            self.inBackground = true
            self.sendJSON(["type": "sleeping"])
        }
        nc.addObserver(forName: UIApplication.willEnterForegroundNotification, object: nil, queue: nil) { [weak self] _ in
            guard let self = self else { return }
            self.inBackground = false
            self.lastRx = Date()
            if self.conn != nil {
                self.sendJSON(["type": "wake"])
                self.requestKeyframe()
                self.onFlush?()
            } else {
                self.scheduleConnectRequest(after: 0.5)
            }
        }
    }

    // MARK: - Pedido de conexión por red (/connect)

    private func storedPC(_ id: String) -> PC? {
        guard let d = UserDefaults.standard.dictionary(forKey: "pc." + id) as? [String: String],
              let name = d["name"], let ip = d["ip"] else { return nil }
        return PC(id: id, name: name, ip: ip, httpPort: Int(d["http"] ?? "") ?? 80, httpsPort: d["https"].flatMap { Int($0) })
    }

    /// El usuario eligió una PC (de la lista de Bonjour o por IP): pedirle que se conecte acá. `code` solo la primera vez.
    func connect(to pc: PC, code: String? = nil) {
        selectedPC = pc
        connectError = ""
        UserDefaults.standard.set(pc.id, forKey: "lastPC")
        UserDefaults.standard.set(["name": pc.name, "ip": pc.ip, "http": String(pc.httpPort),
                                   "https": pc.httpsPort.map { String($0) } ?? ""], forKey: "pc." + pc.id)
        connectRetry = 0
        requestConnect(code: code)
    }

    /// Dejar de insistir con esa PC (botón "otra PC").
    func forgetSelection() {
        connectWork?.cancel(); connectWork = nil
        selectedPC = nil
        needCode = false
        connectError = ""
        UserDefaults.standard.removeObject(forKey: "lastPC")
    }

    private func requestConnect(code: String?) {
        guard let pc = selectedPC, conn == nil, !inBackground else { return }
        var comps = URLComponents(string: pc.httpBase + "/connect")!
        var items = [URLQueryItem(name: "name", value: UIDevice.current.name), URLQueryItem(name: "port", value: String(Bridge.port))]
        if let code = code, !code.isEmpty {
            items.append(URLQueryItem(name: "code", value: code))
        } else if let tok = UserDefaults.standard.string(forKey: "token." + pc.id) {
            items.append(URLQueryItem(name: "token", value: tok))
        }
        comps.queryItems = items
        guard let url = comps.url else { return }
        requesting = true
        var req = URLRequest(url: url)
        req.timeoutInterval = 4
        URLSession.shared.dataTask(with: req) { [weak self] data, resp, err in
            guard let self = self else { return }
            DispatchQueue.main.async { self.handleConnectReply(pc: pc, data: data, http: (resp as? HTTPURLResponse)?.statusCode, error: err) }
        }.resume()
    }

    private func handleConnectReply(pc: PC, data: Data?, http: Int?, error: Error?) {
        requesting = false
        let m = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } ?? [:]
        if let error = error {
            connectError = "No llego a \(pc.name): \(error.localizedDescription)"
            scheduleConnectRequest(after: backoff())
            return
        }
        let serverError = (m["error"] as? String) ?? ""
        if http == 401 {
            // Hace falta el código (nunca emparejado, o el token venció): la vista muestra el campo.
            if serverError.isEmpty { UserDefaults.standard.removeObject(forKey: "token." + pc.id) }
            needCode = true
            connectError = serverError
            return
        }
        guard m["ok"] as? Bool == true else {
            connectError = "Respuesta rara de la PC (\(http ?? 0))"
            scheduleConnectRequest(after: backoff())
            return
        }
        needCode = false
        if let tok = m["token"] as? String { UserDefaults.standard.set(tok, forKey: "token." + pc.id) }
        if let name = m["name"] as? String { pcName = name }
        status = "\(pcName.isEmpty ? pc.name : pcName) avisada; esperando que su puente se conecte…"
        // Si en unos segundos no llegó la conexión (puente caído, otra red), volver a pedir con espera creciente.
        scheduleConnectRequest(after: max(3, backoff()))
    }

    private func backoff() -> TimeInterval {
        connectRetry += 1
        return min(16, 2 * pow(2, Double(connectRetry - 1)))
    }

    private func scheduleConnectRequest(after s: TimeInterval) {
        connectWork?.cancel()
        let w = DispatchWorkItem { [weak self] in self?.requestConnect(code: nil) }
        connectWork = w
        DispatchQueue.main.asyncAfter(deadline: .now() + s, execute: w)
    }

    private func accept(_ c: NWConnection) {
        conn?.cancel()
        conn = c
        format = nil
        waitingKey = true
        lastRx = Date()
        connectWork?.cancel(); connectWork = nil
        connectRetry = 0
        c.stateUpdateHandler = { [weak self] st in
            guard let self = self else { return }
            switch st {
            case .ready:
                DispatchQueue.main.async { self.status = "PC conectada, esperando video…"; self.needCode = false }
                self.send(type: 17, payload: Data())
                self.readMessage()
            case .failed(let e):
                DispatchQueue.main.async { self.status = "Conexión falló: \(e)" }
                self.disconnected(c)
            case .cancelled:
                self.disconnected(c)
            default: break
            }
        }
        c.start(queue: queue)
    }

    private func disconnected(_ c: NWConnection) {
        if conn === c {
            conn = nil
            onFlush?()
            DispatchQueue.main.async {
                self.status = "Esperando a la PC…"; self.hud = ""; self.transport = ""
                // Por red, la PC no vuelve sola: pedirle de nuevo (por USB el puente reconecta por su cuenta).
                if self.selectedPC != nil && !self.inBackground { self.scheduleConnectRequest(after: 2) }
            }
        }
    }

    // MARK: - Recepción

    private func readMessage() {
        guard let c = conn else { return }
        c.receive(minimumIncompleteLength: 4, maximumLength: 4) { [weak self] data, _, _, err in
            guard let self = self, let d = data, d.count == 4, err == nil else { self?.conn?.cancel(); return }
            let len = Int(d[0]) << 24 | Int(d[1]) << 16 | Int(d[2]) << 8 | Int(d[3])
            guard len > 0 && len < 32_000_000 else { self.conn?.cancel(); return }
            c.receive(minimumIncompleteLength: len, maximumLength: len) { [weak self] body, _, _, err2 in
                guard let self = self, let b = body, b.count == len, err2 == nil else { self?.conn?.cancel(); return }
                self.lastRx = Date()
                self.handle(type: b[b.startIndex], payload: b.dropFirst())
                self.readMessage()
            }
        }
    }

    private func handle(type: UInt8, payload: Data) {
        switch type {
        case 0:
            send(type: 0, payload: Data())     // latido del puente: devolverlo (así sabe que seguimos acá)
        case 2:
            let p = Data(payload)
            guard p.count > 1 else { return }
            let record = p.dropFirst()
            format = p[p.startIndex] == 2 ? makeFormatHEVC(hvcC: Data(record)) : makeFormat(avcC: Data(record))
            waitingKey = true
            onFlush?()
            send(type: 17, payload: Data())
            DispatchQueue.main.async { self.status = self.format == nil ? "Config de video inválida" : "" }
        case 3:
            onStill?(Data(payload))
        case 4:
            onStill?(nil)
        case 19:
            if let m = try? JSONSerialization.jsonObject(with: Data(payload)) as? [String: Any] {
                handleControl(m)
            }
        case 1:
            guard let fmt = format, payload.count > 9 else { return }
            let p = Data(payload)
            let key = p[p.startIndex] == 1
            if waitingKey { if !key { return }; waitingKey = false }
            if let now = serverNow {
                // ts f64 big-endian en los bytes 1..8: reloj de la PC (ms) al salir del encoder
                let bits = p[p.startIndex + 1 ..< p.startIndex + 9].reduce(UInt64(0)) { ($0 << 8) | UInt64($1) }
                let ts = Double(bitPattern: bits)
                if ts > 0 { arrival.append(now - ts); if arrival.count > 600 { arrival.removeFirst(arrival.count - 600) } }
            }
            let nal = p.dropFirst(9)
            if let sample = makeSample(data: Data(nal), format: fmt) {
                frames += 1; bytes += nal.count
                onSample?(sample)
            }
        default: break
        }
    }

    /// JSON de control de la PC (tipo 19): pong, welcome, transport, app, auth.
    private func handleControl(_ m: [String: Any]) {
        switch m["type"] as? String {
        case "pong":
            handlePong(m)
        case "welcome":
            let name = m["name"] as? String ?? ""
            DispatchQueue.main.async { self.pcName = name; self.needCode = false }
        case "transport":
            let t = m["transport"] as? String ?? ""
            DispatchQueue.main.async { self.transport = t }
        case "auth":
            // La PC pide emparejar al puente: no debería pasar (el puente corre en la PC); avisar y seguir esperando.
            DispatchQueue.main.async { self.status = "La PC pide emparejamiento al puente (revisá PAIRING en server.py)" }
        default:
            break   // "app" (ventana activa) y lo que venga: la barra fija de la app no lo usa todavía
        }
    }

    /// pong de la PC: RTT y offset de reloj (muestra de menor RTT de las últimas 15, RTT inválidos descartados).
    private func handlePong(_ m: [String: Any]) {
        guard let t = m["t"] as? Double, let s = m["mt"] as? Double else { return }
        let now = localMs, rtt = now - t
        guard rtt >= 0, rtt < 2000 else { return }
        clockSamples.append((rtt: rtt, offset: s - (t + rtt / 2)))
        if clockSamples.count > 15 { clockSamples.removeFirst() }
        if let best = clockSamples.min(by: { $0.rtt < $1.rtt }) { clockOffset = best.offset }
        lastRtt = rtt
        inp50 = m["inp50"] as? Double
        inp95 = m["inp95"] as? Double
    }

    // MARK: - Envío

    func send(type: UInt8, payload: Data) {
        guard let c = conn else { return }
        var msg = Data(capacity: 5 + payload.count)
        let len = UInt32(1 + payload.count)
        msg.append(contentsOf: [UInt8(len >> 24), UInt8((len >> 16) & 0xff), UInt8((len >> 8) & 0xff), UInt8(len & 0xff)])
        msg.append(type)
        msg.append(payload)
        c.send(content: msg, completion: .contentProcessed { _ in })
    }

    func sendInput(_ dict: [String: Any]) {
        var d = dict
        if let now = serverNow { d["t"] = now }   // reloj de la PC estimado: la PC mide la latencia hasta inyectar
        guard let json = try? JSONSerialization.data(withJSONObject: d) else { return }
        send(type: 16, payload: json)
    }

    /// Mensaje JSON de control (ping, stats, quality) a la PC, tipo 18.
    func sendJSON(_ dict: [String: Any]) {
        guard let json = try? JSONSerialization.data(withJSONObject: dict) else { return }
        send(type: 18, payload: json)
    }

    func requestKeyframe() {
        waitingKey = true
        send(type: 17, payload: Data())
    }

    // MARK: - H.264

    private func makeFormat(avcC: Data) -> CMVideoFormatDescription? {
        let b = [UInt8](avcC)
        guard b.count > 7, b[0] == 1 else { return nil }
        nalLength = Int(b[4] & 0x03) + 1
        var sets: [[UInt8]] = []
        var i = 5
        let nSPS = Int(b[i] & 0x1F); i += 1
        for _ in 0..<nSPS {
            guard i + 2 <= b.count else { return nil }
            let len = Int(b[i]) << 8 | Int(b[i + 1]); i += 2
            guard i + len <= b.count else { return nil }
            sets.append(Array(b[i..<i + len])); i += len
        }
        guard i < b.count else { return nil }
        let nPPS = Int(b[i]); i += 1
        for _ in 0..<nPPS {
            guard i + 2 <= b.count else { return nil }
            let len = Int(b[i]) << 8 | Int(b[i + 1]); i += 2
            guard i + len <= b.count else { return nil }
            sets.append(Array(b[i..<i + len])); i += len
        }
        var keep: [UnsafeMutablePointer<UInt8>] = []
        var ptrs: [UnsafePointer<UInt8>] = []
        var sizes: [Int] = []
        for s in sets {
            let p = UnsafeMutablePointer<UInt8>.allocate(capacity: s.count)
            p.initialize(from: s, count: s.count)
            keep.append(p); ptrs.append(UnsafePointer(p)); sizes.append(s.count)
        }
        defer { keep.forEach { $0.deallocate() } }
        var fmt: CMVideoFormatDescription?
        let st = CMVideoFormatDescriptionCreateFromH264ParameterSets(
            allocator: kCFAllocatorDefault, parameterSetCount: sets.count,
            parameterSetPointers: &ptrs, parameterSetSizes: &sizes,
            nalUnitHeaderLength: Int32(nalLength), formatDescriptionOut: &fmt)
        return st == noErr ? fmt : nil
    }

    /// hvcC (HEVCDecoderConfigurationRecord): saltar la cabecera de 22 bytes y leer los arrays de VPS/SPS/PPS.
    private func makeFormatHEVC(hvcC: Data) -> CMVideoFormatDescription? {
        let b = [UInt8](hvcC)
        guard b.count > 23, b[0] == 1 else { return nil }
        nalLength = Int(b[21] & 0x03) + 1
        var sets: [[UInt8]] = []
        var i = 23
        let numArrays = Int(b[22])
        for _ in 0..<numArrays {
            guard i + 3 <= b.count else { return nil }
            i += 1                                           // array_completeness + NAL type
            let n = Int(b[i]) << 8 | Int(b[i + 1]); i += 2
            for _ in 0..<n {
                guard i + 2 <= b.count else { return nil }
                let len = Int(b[i]) << 8 | Int(b[i + 1]); i += 2
                guard i + len <= b.count else { return nil }
                sets.append(Array(b[i..<i + len])); i += len
            }
        }
        guard sets.count >= 3 else { return nil }
        var keep: [UnsafeMutablePointer<UInt8>] = []
        var ptrs: [UnsafePointer<UInt8>] = []
        var sizes: [Int] = []
        for s in sets {
            let p = UnsafeMutablePointer<UInt8>.allocate(capacity: s.count)
            p.initialize(from: s, count: s.count)
            keep.append(p); ptrs.append(UnsafePointer(p)); sizes.append(s.count)
        }
        defer { keep.forEach { $0.deallocate() } }
        var fmt: CMVideoFormatDescription?
        let st = CMVideoFormatDescriptionCreateFromHEVCParameterSets(
            allocator: kCFAllocatorDefault, parameterSetCount: sets.count,
            parameterSetPointers: &ptrs, parameterSetSizes: &sizes,
            nalUnitHeaderLength: Int32(nalLength), extensions: nil, formatDescriptionOut: &fmt)
        return st == noErr ? fmt : nil
    }

    private func makeSample(data: Data, format: CMVideoFormatDescription) -> CMSampleBuffer? {
        var block: CMBlockBuffer?
        let count = data.count
        guard CMBlockBufferCreateWithMemoryBlock(allocator: kCFAllocatorDefault, memoryBlock: nil, blockLength: count,
                                                 blockAllocator: kCFAllocatorDefault, customBlockSource: nil, offsetToData: 0,
                                                 dataLength: count, flags: 0, blockBufferOut: &block) == noErr, let bb = block else { return nil }
        let copied = data.withUnsafeBytes { raw -> OSStatus in
            CMBlockBufferReplaceDataBytes(with: raw.baseAddress!, blockBuffer: bb, offsetIntoDestination: 0, dataLength: count)
        }
        guard copied == noErr else { return nil }
        var sample: CMSampleBuffer?
        var timing = CMSampleTimingInfo(duration: .invalid, presentationTimeStamp: .invalid, decodeTimeStamp: .invalid)
        var size = count
        guard CMSampleBufferCreateReady(allocator: kCFAllocatorDefault, dataBuffer: bb, formatDescription: format, sampleCount: 1,
                                        sampleTimingEntryCount: 1, sampleTimingArray: &timing, sampleSizeEntryCount: 1,
                                        sampleSizeArray: &size, sampleBufferOut: &sample) == noErr, let s = sample else { return nil }
        // Mostrar apenas decodificado, sin esperar a un reloj de presentación.
        if let arr = CMSampleBufferGetSampleAttachmentsArray(s, createIfNecessary: true), CFArrayGetCount(arr) > 0 {
            let dict = unsafeBitCast(CFArrayGetValueAtIndex(arr, 0), to: CFMutableDictionary.self)
            CFDictionarySetValue(dict,
                                 Unmanaged.passUnretained(kCMSampleAttachmentKey_DisplayImmediately).toOpaque(),
                                 Unmanaged.passUnretained(kCFBooleanTrue).toOpaque())
        }
        return s
    }

    private func localIPs() -> [String] {
        var out: [String] = []
        var ifaddr: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&ifaddr) == 0, let first = ifaddr else { return out }
        defer { freeifaddrs(ifaddr) }
        for ptr in sequence(first: first, next: { $0.pointee.ifa_next }) {
            let ifa = ptr.pointee
            guard ifa.ifa_addr.pointee.sa_family == UInt8(AF_INET) else { continue }
            let name = String(cString: ifa.ifa_name)
            guard name.hasPrefix("en") else { continue }
            var host = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            if getnameinfo(ifa.ifa_addr, socklen_t(ifa.ifa_addr.pointee.sa_len), &host, socklen_t(host.count), nil, 0, NI_NUMERICHOST) == 0 {
                out.append(String(cString: host))
            }
        }
        return out
    }
}
