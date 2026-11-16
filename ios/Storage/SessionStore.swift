import Foundation
import ScanCore

/// Every keyframe is written to disk BEFORE any network transfer. Uploads read from disk,
/// so a Wi-Fi cut never loses originals; they are sent when the calculator is reachable again.
final class SessionStore: @unchecked Sendable {
    let root: URL
    let localID: String
    private let lock = NSLock()
    private var pending: [Int] = []
    private(set) var savedCount = 0
    private(set) var sentCount = 0

    static var sessionsDirectory: URL {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        return docs.appendingPathComponent("Sessions", isDirectory: true)
    }

    init(localID: String) throws {
        self.localID = localID
        root = SessionStore.sessionsDirectory.appendingPathComponent(localID, isDirectory: true)
        try FileManager.default.createDirectory(at: root.appendingPathComponent("frames"), withIntermediateDirectories: true)
    }

    // MARK: resuming after the app was closed in the middle of a scan

    struct Unfinished: Equatable {
        var localID: String
        var serverSessionID: String
        var pending: Int
        var total: Int
    }

    /// Reopen a session from disk: the views not yet acknowledged by the calculator become pending again.
    init(resuming localID: String) throws {
        self.localID = localID
        root = SessionStore.sessionsDirectory.appendingPathComponent(localID, isDirectory: true)
        let (all, sent) = SessionStore.frameIDs(in: root)
        pending = all.filter { !sent.contains($0) }
        savedCount = all.count
        sentCount = sent.count
    }

    private static func frameIDs(in root: URL) -> (all: [Int], sent: Set<Int>) {
        let names = (try? FileManager.default.contentsOfDirectory(atPath: root.appendingPathComponent("frames").path)) ?? []
        var all: [Int] = [], sent = Set<Int>()
        for n in names {
            let parts = n.split(separator: ".")
            guard parts.count == 2, let id = Int(parts[0]) else { continue }
            if parts[1] == "json" { all.append(id) } else if parts[1] == "sent" { sent.insert(id) }
        }
        return (all.sorted(), sent)
    }

    private func marker(_ name: String) -> URL { root.appendingPathComponent(name) }

    func setServerSession(_ sid: String) { try? Data(sid.utf8).write(to: marker("server_session.txt"), options: .atomic) }
    func markFinishRequested() { FileManager.default.createFile(atPath: marker("finish.requested").path, contents: Data()) }
    func markAbandoned() { FileManager.default.createFile(atPath: marker("abandoned").path, contents: Data()) }

    /// Most recent session that reached the calculator but was neither finished nor abandoned on purpose.
    static func unfinished() -> Unfinished? {
        let fm = FileManager.default
        let dirs = ((try? fm.contentsOfDirectory(atPath: sessionsDirectory.path)) ?? []).sorted(by: >)
        for d in dirs.prefix(5) {
            let root = sessionsDirectory.appendingPathComponent(d, isDirectory: true)
            if fm.fileExists(atPath: root.appendingPathComponent("finish.requested").path) { continue }
            if fm.fileExists(atPath: root.appendingPathComponent("abandoned").path) { continue }
            guard let sidData = try? Data(contentsOf: root.appendingPathComponent("server_session.txt")),
                  let sid = String(data: sidData, encoding: .utf8), !sid.isEmpty else { continue }
            let (all, sent) = frameIDs(in: root)
            if all.isEmpty { continue }
            return Unfinished(localID: d, serverSessionID: sid, pending: all.filter { !sent.contains($0) }.count, total: all.count)
        }
        return nil
    }

    func url(_ frameID: Int, _ ext: String) -> URL {
        root.appendingPathComponent("frames").appendingPathComponent(String(format: "%06d.%@", frameID, ext))
    }

    func writeSessionInfo(_ object: [String: Any]) {
        if let d = try? JSONSerialization.data(withJSONObject: object, options: [.prettyPrinted, .sortedKeys]) {
            try? d.write(to: root.appendingPathComponent("session.json"), options: .atomic)
        }
    }

    func save(frameID: Int, jpeg: Data, meta: Data, depth: Data?, confidence: Data?) throws {
        try jpeg.write(to: url(frameID, "jpg"), options: .atomic)
        if let depth { try depth.write(to: url(frameID, "depth"), options: .atomic) }
        if let confidence { try confidence.write(to: url(frameID, "conf"), options: .atomic) }
        try meta.write(to: url(frameID, "json"), options: .atomic)  // written last: frame complete
        lock.lock(); pending.append(frameID); savedCount += 1; lock.unlock()
    }

    func nextPending() -> Int? {
        lock.lock(); defer { lock.unlock() }
        return pending.first
    }

    func markSent(_ frameID: Int) {
        lock.lock()
        pending.removeAll { $0 == frameID }
        sentCount += 1
        lock.unlock()
        FileManager.default.createFile(atPath: url(frameID, "sent").path, contents: Data())
    }

    var pendingCount: Int { lock.lock(); defer { lock.unlock() }; return pending.count }

    /// Envelope for upload, with the server session id filled in at send time.
    func envelope(frameID: Int, serverSessionID: String) throws -> Data {
        var meta = try JSONDecoder().decode(FrameMeta.self, from: Data(contentsOf: url(frameID, "json")))
        meta.session_id = serverSessionID
        let fm = FileManager.default
        let depth = fm.fileExists(atPath: url(frameID, "depth").path) ? try Data(contentsOf: url(frameID, "depth")) : Data()
        let conf = fm.fileExists(atPath: url(frameID, "conf").path) ? try Data(contentsOf: url(frameID, "conf")) : Data()
        return FrameEnvelope.encode(meta: try meta.jsonData(), jpeg: try Data(contentsOf: url(frameID, "jpg")), depth: depth, confidence: conf)
    }

    func saveArtifact(name: String, data: Data) throws -> URL {
        let dir = root.appendingPathComponent("results", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let safe = name.replacingOccurrences(of: "/", with: "_")
        let u = dir.appendingPathComponent(safe)
        try data.write(to: u, options: .atomic)
        return u
    }

    /// Zip of the whole session folder (frames, metadata, results) for sharing, via the system coordinator.
    func exportZip() throws -> URL {
        var result: URL?
        var coordError: NSError?
        var copyError: Error?
        NSFileCoordinator().coordinate(readingItemAt: root, options: [.forUploading], error: &coordError) { zipped in
            let dest = FileManager.default.temporaryDirectory.appendingPathComponent("dishplay-scan-\(localID).zip")
            try? FileManager.default.removeItem(at: dest)
            do { try FileManager.default.copyItem(at: zipped, to: dest); result = dest } catch { copyError = error }
        }
        if let coordError { throw coordError }
        if let copyError { throw copyError }
        guard let result else { throw CocoaError(.fileWriteUnknown) }
        return result
    }
}
