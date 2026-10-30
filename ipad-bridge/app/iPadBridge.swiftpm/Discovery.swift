import Foundation
import Network

/// Una PC con iPad Bridge vista por Bonjour (`_ipadbridge._tcp`, lo publica server.py con zeroconf).
/// El TXT trae id (estable, el de pairing.json), name, ip y los puertos http/https.
struct PC: Identifiable, Hashable {
    let id: String
    let name: String
    let ip: String
    let httpPort: Int
    let httpsPort: Int?

    /// WebSocket del servidor: wss si la PC tiene certificados (lo normal), si no ws en el puerto http.
    var url: String {
        if let p = httpsPort { return "wss://\(ip)\(p == 443 ? "" : ":\(p)")/ws" }
        return "ws://\(ip)\(httpPort == 80 ? "" : ":\(httpPort)")/ws"
    }

    /// Para una IP escrita a mano (sin Bonjour): puertos estándar, id = la IP.
    static func manual(_ ip: String) -> PC {
        PC(id: "ip:" + ip, name: ip, ip: ip, httpPort: 80, httpsPort: 443)
    }
}

/// Lista las PCs de la red con NWBrowser. Package.swift declara `_ipadbridge._tcp` en bonjourServiceTypes
/// (sin eso iPadOS no deja ver la red local).
final class Discovery: ObservableObject {
    @Published var pcs: [PC] = []
    private var browser: NWBrowser?
    private let queue = DispatchQueue(label: "bridge.bonjour")

    func start() {
        guard browser == nil else { return }
        let params = NWParameters()
        params.includePeerToPeer = true
        let b = NWBrowser(for: .bonjourWithTXTRecord(type: "_ipadbridge._tcp", domain: nil), using: params)
        b.browseResultsChangedHandler = { [weak self] results, _ in
            var list: [PC] = []
            for r in results {
                guard case .service(let name, _, _, _) = r.endpoint else { continue }
                var txt: [String: String] = [:]
                if case .bonjour(let rec) = r.metadata { txt = rec.dictionary }
                guard let ip = txt["ip"], let id = txt["id"] else { continue }
                list.append(PC(id: id, name: txt["name"] ?? name, ip: ip,
                               httpPort: Int(txt["http"] ?? "") ?? 80,
                               httpsPort: txt["https"].flatMap { Int($0) }))
            }
            let sorted = list.sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
            DispatchQueue.main.async { self?.pcs = sorted }
        }
        b.stateUpdateHandler = { [weak self] st in
            guard let self = self else { return }
            if case .failed = st {
                b.cancel()
                self.browser = nil
                self.queue.asyncAfter(deadline: .now() + 2) { self.start() }
            }
        }
        b.start(queue: queue)
        browser = b
    }

    func stop() {
        browser?.cancel()
        browser = nil
    }
}
