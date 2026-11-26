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
    /// The folder was removed from the iPhone (scan abandoned): nothing may be written into it any more.
    private var removed = false

    #if DEBUG
    /// The unit tests keep their dishes in a folder of their own. Debug builds only.
    static var directoryOverride: URL?
    #endif

    static var sessionsDirectory: URL {
        #if DEBUG
        if let folder = directoryOverride ?? UITestMode.sessions { return folder }
        #endif
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        return docs.appendingPathComponent("Sessions", isDirectory: true)
    }

    init(localID: String) throws {
        self.localID = localID
        root = SessionStore.sessionsDirectory.appendingPathComponent(localID, isDirectory: true)
        let views = root.appendingPathComponent("frames", isDirectory: true)
        try FileManager.default.createDirectory(at: views, withIntermediateDirectories: true)
        SessionStore.keepOutOfBackups(views)
    }

    // MARK: backups

    /// The views of a scan weigh 100 to 300 MB and can be taken again with the dish on the table; the model made
    /// from them cannot. So only the views are left out of the iPhone's backups (iCloud or a computer): the
    /// models, names and pictures of the dishes stay in them.
    static func keepOutOfBackups(_ folder: URL) {
        var folder = folder
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try? folder.setResourceValues(values)
    }

    /// Same for the scans made with an earlier version of the app. Called once when the app starts.
    static func keepViewsOutOfBackups() {
        let fm = FileManager.default
        for name in (try? fm.contentsOfDirectory(atPath: sessionsDirectory.path)) ?? [] {
            let views = sessionsDirectory.appendingPathComponent(name, isDirectory: true)
                .appendingPathComponent("frames", isDirectory: true)
            if fm.fileExists(atPath: views.path) { keepOutOfBackups(views) }
        }
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

    // MARK: abandoning a scan

    /// Earlier versions of the app only wrote this empty file in the folder of an abandoned scan and kept its
    /// views. The app no longer writes it; it still recognises it, to remove those folders (`removeLeftovers`).
    static let abandonedMarker = "abandoned"

    private var isRemoved: Bool { lock.lock(); defer { lock.unlock() }; return removed }

    /// The person gives this scan up: its views and everything else in its folder leave the iPhone.
    func delete() {
        lock.lock()
        removed = true
        pending.removeAll()
        lock.unlock()
        try? FileManager.default.removeItem(at: root)
    }

    /// Same, for a scan that is not open (the interrupted scan offered on the home screen).
    static func delete(localID: String) {
        guard !localID.isEmpty, !localID.contains("/") else { return }
        try? FileManager.default.removeItem(at: sessionsDirectory.appendingPathComponent(localID, isDirectory: true))
    }

    /// Remove the folders the app does not show and never will: scans abandoned with an earlier version of the
    /// app (marked, but their views kept), and folders in which no view was ever saved. A folder that holds a
    /// result is always kept. Called once when the app starts. Returns how many folders were removed.
    @discardableResult
    static func removeLeftovers() -> Int {
        let fm = FileManager.default
        var count = 0
        for name in (try? fm.contentsOfDirectory(atPath: sessionsDirectory.path)) ?? [] {
            let root = sessionsDirectory.appendingPathComponent(name, isDirectory: true)
            var isFolder: ObjCBool = false
            guard fm.fileExists(atPath: root.path, isDirectory: &isFolder), isFolder.boolValue else { continue }
            let results = root.appendingPathComponent("results", isDirectory: true)
            if fm.fileExists(atPath: results.appendingPathComponent("apercu.png").path) { continue }
            if fm.fileExists(atPath: results.appendingPathComponent("model.glb").path) { continue }
            let abandoned = fm.fileExists(atPath: root.appendingPathComponent(abandonedMarker).path)
            let views = (try? fm.contentsOfDirectory(atPath: root.appendingPathComponent("frames").path)) ?? []
            guard abandoned || views.isEmpty else { continue }
            if (try? fm.removeItem(at: root)) != nil { count += 1 }
        }
        return count
    }

    // MARK: the name of the dish, on the calculator too

    private static func nameSentFile(in root: URL) -> URL { root.appendingPathComponent("name.sent") }

    /// The name the calculator last received for the dish in this folder; nil when it never received one.
    static func nameSent(in root: URL) -> String? {
        guard let text = try? String(contentsOf: nameSentFile(in: root), encoding: .utf8) else { return nil }
        let name = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return name.isEmpty ? nil : name
    }

    /// The calculator has this name for the dish: it is not sent again until the person changes it.
    static func markNameSent(_ name: String, in root: URL) {
        guard FileManager.default.fileExists(atPath: root.path) else { return }
        try? Data(name.utf8).write(to: nameSentFile(in: root), options: .atomic)
    }

    // MARK: how the final model came out

    private static func outcomeFile(in root: URL) -> URL { root.appendingPathComponent("outcome.json") }

    /// Keep the calculator's verdict on the final model, and what it had to give up, with the dish.
    func saveOutcome(_ outcome: FinalOutcome) {
        guard !outcome.isEmpty, !isRemoved, let data = try? outcome.jsonData() else { return }
        try? data.write(to: SessionStore.outcomeFile(in: root), options: .atomic)
    }

    /// What was kept by `saveOutcome` for the dish in this folder; nil when the calculator said nothing.
    static func outcome(in root: URL) -> FinalOutcome? {
        guard let data = try? Data(contentsOf: outcomeFile(in: root)) else { return nil }
        return FinalOutcome.read(data)
    }

    /// Most recent session that reached the calculator but was neither finished nor abandoned on purpose.
    static func unfinished() -> Unfinished? {
        let fm = FileManager.default
        let dirs = ((try? fm.contentsOfDirectory(atPath: sessionsDirectory.path)) ?? []).sorted(by: >)
        for d in dirs.prefix(5) {
            let root = sessionsDirectory.appendingPathComponent(d, isDirectory: true)
            if fm.fileExists(atPath: root.appendingPathComponent("finish.requested").path) { continue }
            if fm.fileExists(atPath: root.appendingPathComponent(abandonedMarker).path) { continue }
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
        // A view still being prepared when the scan was abandoned must not bring its folder back.
        guard !isRemoved else { throw CocoaError(.fileNoSuchFile) }
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
        guard !isRemoved else { throw CocoaError(.fileNoSuchFile) }
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
