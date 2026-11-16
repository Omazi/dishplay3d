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
