import Foundation
import ScanCore

struct HealthInfo: Decodable {
    var service: String
    var api: Int
    var engine: String
    var active_session: String?
    var worker_alive: Bool?
}

enum TransportError: LocalizedError {
    case http(Int, String)
    case notPaired
    case badResponse

    var errorDescription: String? {
        switch self {
        case .http(let code, let msg): return "Calculateur : erreur \(code) \(msg)"
        case .notPaired: return "Téléphone non jumelé au calculateur."
        case .badResponse: return "Réponse inattendue du calculateur."
        }
    }
}

/// HTTPS + WebSocket client of the local calculator (pinned TLS, bearer token).
/// Images/metadata go out as DPF1 envelopes; events come back as JSON, geometry as DPG1.
final class ScanTransport: NSObject, @unchecked Sendable {
    let baseURL: URL
    let fingerprint: String
    var token: String?
    private let session: URLSession
    private var socket: URLSessionWebSocketTask?
    private var socketSessionID: String?
    private var reconnectWork: DispatchWorkItem?
    var onEvent: ((ServerEvent) -> Void)?
    var onSocketState: ((Bool) -> Void)?

    init(baseURL: URL, fingerprint: String, token: String?) {
        self.baseURL = baseURL
        self.fingerprint = fingerprint
        self.token = token
        let cfg = URLSessionConfiguration.default
        cfg.timeoutIntervalForRequest = 15
        cfg.timeoutIntervalForResource = 120
        cfg.waitsForConnectivity = false
        cfg.httpMaximumConnectionsPerHost = 3
        session = URLSession(configuration: cfg, delegate: PinnedSessionDelegate(fingerprint: fingerprint), delegateQueue: nil)
        super.init()
    }

    private func request(_ path: String, method: String = "GET", body: Data? = nil, contentType: String = "application/json") -> URLRequest {
        var r = URLRequest(url: baseURL.appendingPathComponent(path))
        r.httpMethod = method
        if let token { r.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if let body {
            r.httpBody = body
            r.setValue(contentType, forHTTPHeaderField: "Content-Type")
        }
        return r
    }

    private func send(_ r: URLRequest) async throws -> Data {
        let (data, resp) = try await session.data(for: r)
        guard let http = resp as? HTTPURLResponse else { throw TransportError.badResponse }
        guard (200..<300).contains(http.statusCode) else {
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String ?? ""
            throw TransportError.http(http.statusCode, detail)
        }
        return data
    }

    func health() async throws -> (HealthInfo, Double) {
        let t0 = Date()
        let d = try await send(request("health"))
        return (try JSONDecoder().decode(HealthInfo.self, from: d), Date().timeIntervalSince(t0))
    }

    func pair(code: String, device: String) async throws -> String {
        let body = try JSONSerialization.data(withJSONObject: ["code": code, "device": device])
        let d = try await send(request("pair", method: "POST", body: body))
        guard let t = (try JSONSerialization.jsonObject(with: d) as? [String: Any])?["token"] as? String else { throw TransportError.badResponse }
        token = t
        return t
    }

    func createSession(_ body: SessionCreate) async throws -> String {
        guard token != nil else { throw TransportError.notPaired }
        let d = try await send(request("sessions", method: "POST", body: try JSONEncoder().encode(body)))
        guard let sid = (try JSONSerialization.jsonObject(with: d) as? [String: Any])?["session_id"] as? String else { throw TransportError.badResponse }
        return sid
    }

    func putFrame(sessionID: String, frameID: Int, envelope: Data) async throws {
        _ = try await send(request("sessions/\(sessionID)/frames/\(frameID)", method: "PUT", body: envelope,
                                   contentType: "application/octet-stream"))
    }

    func post(_ path: String, json: [String: Any] = [:]) async throws {
        _ = try await send(request(path, method: "POST", body: try JSONSerialization.data(withJSONObject: json)))
    }

    func postBox(sessionID: String, box: BoxSpec) async throws {
        _ = try await send(request("sessions/\(sessionID)/box", method: "POST", body: try JSONEncoder().encode(box)))
    }

    func download(_ path: String) async throws -> Data {
        try await send(request(path.hasPrefix("/") ? String(path.dropFirst()) : path))
    }

    func artifacts(sessionID: String) async throws -> [String] {
        let d = try await send(request("sessions/\(sessionID)/artifacts"))
        return (try JSONSerialization.jsonObject(with: d) as? [String: Any])?["files"] as? [String] ?? []
    }

    // MARK: events

    func connectEvents(sessionID: String) {
        socketSessionID = sessionID
        reconnectWork?.cancel()
        socket?.cancel(with: .goingAway, reason: nil)
        var comps = URLComponents(url: baseURL.appendingPathComponent("sessions/\(sessionID)/events"), resolvingAgainstBaseURL: false)!
        comps.scheme = "wss"
        var r = URLRequest(url: comps.url!)
        if let token { r.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        let ws = session.webSocketTask(with: r)
        socket = ws
        ws.resume()
        receive(ws)
        ping(ws)
    }

    func disconnectEvents() {
        socketSessionID = nil
        reconnectWork?.cancel()
        socket?.cancel(with: .normalClosure, reason: nil)
        socket = nil
    }

    private func receive(_ ws: URLSessionWebSocketTask) {
        ws.receive { [weak self] result in
            guard let self, ws === self.socket else { return }
            switch result {
            case .success(let msg):
                self.onSocketState?(true)
                if case .string(let text) = msg, let ev = ServerEvent.decode(text) { self.onEvent?(ev) }
                self.receive(ws)
            case .failure:
                self.onSocketState?(false)
                self.scheduleReconnect()
            }
        }
    }

    private func ping(_ ws: URLSessionWebSocketTask) {
        DispatchQueue.global().asyncAfter(deadline: .now() + 5) { [weak self] in
            guard let self, ws === self.socket else { return }
            ws.sendPing { error in
                if error != nil { self.onSocketState?(false) } else { self.onSocketState?(true) }
            }
            self.ping(ws)
        }
    }

    private func scheduleReconnect() {
        guard let sid = socketSessionID else { return }
        let work = DispatchWorkItem { [weak self] in self?.connectEvents(sessionID: sid) }
        reconnectWork = work
        DispatchQueue.global().asyncAfter(deadline: .now() + 2, execute: work)
    }
}
