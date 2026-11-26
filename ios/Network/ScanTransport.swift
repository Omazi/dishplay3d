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
        case .notPaired: return "L’iPhone n’est pas relié au calculateur."
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
    /// Guards the three properties below: they are used from the main thread, from URLSession's own queue and
    /// from the timer that reconnects.
    private let socketLock = NSLock()
    private var socket: URLSessionWebSocketTask?
    private var socketSessionID: String?
    private var reconnectWork: DispatchWorkItem?
    var onEvent: ((ServerEvent) -> Void)?
    var onSocketState: ((Bool) -> Void)?

    init(baseURL: URL, fingerprint: String, token: String?, requestTimeout: TimeInterval = 15) {
        self.baseURL = baseURL
        self.fingerprint = fingerprint
        self.token = token
        let cfg = URLSessionConfiguration.default
        cfg.timeoutIntervalForRequest = requestTimeout
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

    /// Create the scan on the calculator. `waiting` in the answer: it is finishing another dish, the views are
    /// kept and the live preview starts by itself afterwards.
    func createSession(_ body: SessionCreate) async throws -> SessionCreated {
        guard token != nil else { throw TransportError.notPaired }
        let d = try await send(request("sessions", method: "POST", body: try JSONEncoder().encode(body)))
        guard let created = SessionCreated.decode(d) else { throw TransportError.badResponse }
        return created
    }

    /// Send one view. The answer says whether a live calculation took it at once (see `FrameAnswer`).
    @discardableResult
    func putFrame(sessionID: String, frameID: Int, envelope: Data) async throws -> FrameAnswer {
        let d = try await send(request("sessions/\(sessionID)/frames/\(frameID)", method: "PUT", body: envelope,
                                       contentType: "application/octet-stream"))
        return FrameAnswer.decode(d)
    }

    private func postJSON(_ path: String, json: [String: Any]) async throws -> Data {
        try await send(request(path, method: "POST", body: try JSONSerialization.data(withJSONObject: json)))
    }

    func post(_ path: String, json: [String: Any] = [:]) async throws {
        _ = try await postJSON(path, json: json)
    }

    /// Ask for the final model of a scan. A calculator that keeps a queue accepts this at any time (the answer
    /// says whether the dish waits its turn); an older one answers 409 when it is not working on this scan.
    func finish(sessionID: String, referenceWidth: Double? = nil) async throws -> FinishAnswer {
        var body: [String: Any] = [:]
        if let referenceWidth { body["reference_width_m"] = referenceWidth }
        let d = try await postJSON("sessions/\(sessionID)/finish", json: body)
        return FinishAnswer.decode(d)
    }

    /// Ask the calculator to work on this scan again (after it was restarted, or to finish a dish later).
    /// An older calculator answers 409 while it is finishing another dish.
    func resumeWorker(sessionID: String) async throws -> WorkerAnswer {
        let d = try await postJSON("sessions/\(sessionID)/resume_worker", json: [:])
        return WorkerAnswer.decode(d)
    }

    /// Tell the calculator the name the person gave this dish, so that its folder can be recognised on the PC.
    /// A calculator that does not keep names yet answers 404, like for a dish it no longer knows.
    func setName(sessionID: String, name: String) async throws {
        _ = try await postJSON("sessions/\(sessionID)/name", json: ["name": name])
    }

    func postBox(sessionID: String, box: BoxSpec) async throws {
        _ = try await send(request("sessions/\(sessionID)/box", method: "POST", body: try JSONEncoder().encode(box)))
    }

    func download(_ path: String) async throws -> Data {
        try await send(request(path.hasPrefix("/") ? String(path.dropFirst()) : path))
    }

    /// What the calculator says about one scan: finished, waiting its turn, being calculated (and how far),
    /// failed or stopped.
    func sessionInfo(sessionID: String) async throws -> SessionStatus {
        let d = try await send(request("sessions/\(sessionID)"))
        guard let status = try? SessionStatus.decode(d) else { throw TransportError.badResponse }
        return status
    }

    func artifacts(sessionID: String) async throws -> [String] {
        let d = try await send(request("sessions/\(sessionID)/artifacts"))
        return (try JSONSerialization.jsonObject(with: d) as? [String: Any])?["files"] as? [String] ?? []
    }

    // MARK: events

    /// Listen to the events of one scan. Replaces the connection to any other scan.
    func connectEvents(sessionID: String) {
        var comps = URLComponents(url: baseURL.appendingPathComponent("sessions/\(sessionID)/events"), resolvingAgainstBaseURL: false)!
        comps.scheme = "wss"
        var r = URLRequest(url: comps.url!)
        if let token { r.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        let ws = session.webSocketTask(with: r)
        socketLock.lock()
        socketSessionID = sessionID
        reconnectWork?.cancel()
        reconnectWork = nil
        let previous = socket
        socket = ws
        socketLock.unlock()
        previous?.cancel(with: .goingAway, reason: nil)
        ws.resume()
        receive(ws)
        ping(ws)
    }

    /// Stop listening: no event of the scan that was listened to arrives after this, and nothing reconnects.
    func disconnectEvents() {
        socketLock.lock()
        socketSessionID = nil
        reconnectWork?.cancel()
        reconnectWork = nil
        let previous = socket
        socket = nil
        socketLock.unlock()
        previous?.cancel(with: .normalClosure, reason: nil)
    }

    /// Whether `ws` is still the connection in use (an older one may still deliver a last message or an error).
    private func isCurrent(_ ws: URLSessionWebSocketTask) -> Bool {
        socketLock.lock()
        defer { socketLock.unlock() }
        return ws === socket
    }

    private func receive(_ ws: URLSessionWebSocketTask) {
        ws.receive { [weak self] result in
            guard let self, self.isCurrent(ws) else { return }
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
            guard let self, self.isCurrent(ws) else { return }
            ws.sendPing { error in
                if error != nil { self.onSocketState?(false) } else { self.onSocketState?(true) }
            }
            self.ping(ws)
        }
    }

    private func scheduleReconnect() {
        socketLock.lock()
        guard let sid = socketSessionID else {
            socketLock.unlock()
            return
        }
        let work = DispatchWorkItem { [weak self] in self?.reconnect(sessionID: sid) }
        reconnectWork?.cancel()
        reconnectWork = work
        socketLock.unlock()
        DispatchQueue.global().asyncAfter(deadline: .now() + 2, execute: work)
    }

    /// The reconnection planned two seconds earlier, unless the events were disconnected or pointed at
    /// another scan in the meantime.
    private func reconnect(sessionID: String) {
        socketLock.lock()
        let stillWanted = socketSessionID == sessionID
        socketLock.unlock()
        if stillWanted { connectEvents(sessionID: sessionID) }
    }
}
