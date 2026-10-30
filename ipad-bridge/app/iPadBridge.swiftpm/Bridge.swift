import Foundation
import Network
import CoreMedia
import AVFoundation

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

final class Bridge: ObservableObject {
    static let port: UInt16 = 7777

    @Published var status = "Esperando a la PC…"
    @Published var hud = ""
    @Published var addresses = ""
    @Published var penHud = ""      // "GOMA" mientras el doble toque del Pencil tiene la goma activa

    private var listener: NWListener?
    private var conn: NWConnection?
    private let queue = DispatchQueue(label: "bridge.net")
    private var format: CMVideoFormatDescription?
    private var nalLength = 4
    private var waitingKey = true
    private var frames = 0
    private var bytes = 0
    private var statsTimer: Timer?

    /// La vista de video se registra acá para recibir los sample buffers y las imágenes fijas.
    var onSample: ((CMSampleBuffer) -> Void)?
    var onFlush: (() -> Void)?
    var onStill: ((Data?) -> Void)?   // PNG, o nil para volver al video

    func start() {
        guard listener == nil else { return }
        addresses = localIPs().joined(separator: "  ")
        openListener()
        statsTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            guard let s = self else { return }
            let mbps = Double(s.bytes * 8) / 1e6
            s.hud = s.conn == nil ? "" : String(format: "%d fps · %.1f Mbps", s.frames, mbps)
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
        conn?.cancel(); conn = nil
        listener?.cancel(); listener = nil
        statsTimer?.invalidate(); statsTimer = nil
    }

    private func accept(_ c: NWConnection) {
        conn?.cancel()
        conn = c
        format = nil
        waitingKey = true
        c.stateUpdateHandler = { [weak self] st in
            guard let self = self else { return }
            switch st {
            case .ready:
                DispatchQueue.main.async { self.status = "PC conectada, esperando video…" }
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
            DispatchQueue.main.async { self.status = "Esperando a la PC…"; self.hud = "" }
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
                self.handle(type: b[b.startIndex], payload: b.dropFirst())
                self.readMessage()
            }
        }
    }

    private func handle(type: UInt8, payload: Data) {
        switch type {
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
        case 1:
            guard let fmt = format, payload.count > 9 else { return }
            let p = Data(payload)
            let key = p[p.startIndex] == 1
            if waitingKey { if !key { return }; waitingKey = false }
            let nal = p.dropFirst(9)
            if let sample = makeSample(data: Data(nal), format: fmt) {
                frames += 1; bytes += nal.count
                onSample?(sample)
            }
        default: break
        }
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
        guard let json = try? JSONSerialization.data(withJSONObject: dict) else { return }
        send(type: 16, payload: json)
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
