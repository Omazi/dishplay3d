import XCTest
@testable import DishPlayScan

/// Tests of what the app keeps on the iPhone. Each test gets an empty folder of dishes of its own, in place of
/// the app's documents (`SessionStore.directoryOverride`, debug builds only), and builds in it the folders it
/// needs, exactly as the app writes them.
class StorageTestCase: XCTestCase {
    private(set) var sessions = FileManager.default.temporaryDirectory

    override func setUpWithError() throws {
        try super.setUpWithError()
        sessions = FileManager.default.temporaryDirectory
            .appendingPathComponent("app-tests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: sessions, withIntermediateDirectories: true)
        SessionStore.directoryOverride = sessions
    }

    override func tearDownWithError() throws {
        SessionStore.directoryOverride = nil
        try? FileManager.default.removeItem(at: sessions)
        try super.tearDownWithError()
    }

    /// A scan folder as the app leaves it: `views` views, the first `sent` of them received by the calculator.
    @discardableResult
    func makeScan(_ id: String, views: Int, sent: Int = 0, server: String? = "calc-1", finishRequested: Bool = false,
                  abandoned: Bool = false, results: [String] = []) throws -> URL {
        let fm = FileManager.default
        let root = sessions.appendingPathComponent(id, isDirectory: true)
        let frames = root.appendingPathComponent("frames", isDirectory: true)
        try fm.createDirectory(at: frames, withIntermediateDirectories: true)
        for n in 0..<views {
            let base = String(format: "%06d", n)
            try Data([0xFF, 0xD8, 0xFF, 0xD9]).write(to: frames.appendingPathComponent(base + ".jpg"))
            try Data("{}".utf8).write(to: frames.appendingPathComponent(base + ".json"))
            if n < sent { try Data().write(to: frames.appendingPathComponent(base + ".sent")) }
        }
        if let server { try Data(server.utf8).write(to: root.appendingPathComponent("server_session.txt")) }
        if finishRequested { try Data().write(to: root.appendingPathComponent("finish.requested")) }
        // What earlier versions of the app left behind for an abandoned scan: an empty file, the views kept.
        if abandoned { try Data().write(to: root.appendingPathComponent("abandoned")) }
        if !results.isEmpty {
            let folder = root.appendingPathComponent("results", isDirectory: true)
            try fm.createDirectory(at: folder, withIntermediateDirectories: true)
            for name in results { try Data("x".utf8).write(to: folder.appendingPathComponent(name)) }
        }
        return root
    }

    func exists(_ url: URL) -> Bool { FileManager.default.fileExists(atPath: url.path) }
}
