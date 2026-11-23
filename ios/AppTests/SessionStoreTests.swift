import ScanCore
import XCTest
@testable import DishPlayScan

/// The promise of `SessionStore`: a view is on the iPhone before it is sent, and a cut never loses it.
final class SessionStoreTests: StorageTestCase {
    private let jpeg = Data([0xFF, 0xD8, 0xFF, 0xD9])

    private func meta(_ frame: Int, session: String = "local") throws -> Data {
        try FrameMeta(sessionID: session, frameID: frame, epoch: 0, timestamp: Double(frame),
                      image: .init(width: 1920, height: 1440, sha256: String(repeating: "a", count: 64)),
                      intrinsics: Intrinsics(fx: 1400, fy: 1400, cx: 959.5, cy: 719.5, width: 1920, height: 1440),
                      worldFromCameraAR: .identity, tracking: .init(state: "normal", reason: nil),
                      cameraFormat: .init(width: 1920, height: 1440, fps: 30, device: "wide"),
                      quality: .init(sharpness: 1, mean_luma: 120, box_in_view: 0.9, translation_since_last_m: 0.02, angular_speed_dps: 5),
                      depth: nil).jsonData()
    }

    func testAViewWaitsUntilTheCalculatorHasIt() throws {
        let store = try SessionStore(localID: "2026-11-21T10-00-00Z")
        XCTAssertNil(store.nextPending())
        try store.save(frameID: 0, jpeg: jpeg, meta: meta(0), depth: nil, confidence: nil)
        try store.save(frameID: 1, jpeg: jpeg, meta: meta(1), depth: Data([1, 2, 3, 4]), confidence: Data([9]))
        XCTAssertEqual(store.savedCount, 2)
        XCTAssertEqual(store.pendingCount, 2)
        XCTAssertEqual(store.nextPending(), 0, "views leave in the order they were taken")
        XCTAssertTrue(exists(store.url(0, "jpg")))
        XCTAssertTrue(exists(store.url(0, "json")))
        XCTAssertTrue(exists(store.url(1, "depth")))
        XCTAssertTrue(exists(store.url(1, "conf")))

        store.markSent(0)
        XCTAssertEqual(store.nextPending(), 1)
        XCTAssertEqual(store.pendingCount, 1)
        XCTAssertEqual(store.sentCount, 1)
        XCTAssertTrue(exists(store.url(0, "sent")), "what was sent is written down, for the next opening of the app")
        XCTAssertTrue(exists(store.url(0, "jpg")), "the original stays on the iPhone after it was sent")
    }

    /// The app was closed, or the Wi-Fi cut, in the middle of a scan: only the missing views are sent again.
    func testResumingAfterACutSendsOnlyWhatIsMissing() throws {
        let first = try SessionStore(localID: "2026-11-21T10-00-00Z")
        for frame in 0..<4 { try first.save(frameID: frame, jpeg: jpeg, meta: meta(frame), depth: nil, confidence: nil) }
        first.markSent(0)
        first.markSent(2)

        let again = try SessionStore(resuming: "2026-11-21T10-00-00Z")
        XCTAssertEqual(again.savedCount, 4)
        XCTAssertEqual(again.sentCount, 2)
        XCTAssertEqual(again.pendingCount, 2)
        XCTAssertEqual(again.nextPending(), 1)
        again.markSent(1)
        XCTAssertEqual(again.nextPending(), 3)
        again.markSent(3)
        XCTAssertNil(again.nextPending())
        XCTAssertEqual(try SessionStore(resuming: "2026-11-21T10-00-00Z").pendingCount, 0)
    }

    /// The description of a view is written last: a view cut in the middle of its writing has none and is not sent.
    func testAViewWithoutItsDescriptionIsNotCounted() throws {
        let root = try makeScan("2026-11-21T10-00-00Z", views: 2)
        try FileManager.default.removeItem(at: root.appendingPathComponent("frames/000001.json"))
        let store = try SessionStore(resuming: "2026-11-21T10-00-00Z")
        XCTAssertEqual(store.savedCount, 1)
        XCTAssertEqual(store.nextPending(), 0)
    }

    /// A view is stored under the iPhone's own name for the scan and sent under the calculator's.
    func testAViewIsSentUnderTheCalculatorsNameForTheScan() throws {
        let store = try SessionStore(localID: "2026-11-21T10-00-00Z")
        try store.save(frameID: 7, jpeg: jpeg, meta: meta(7, session: "2026-11-21T10-00-00Z"), depth: Data([1, 2, 3, 4]), confidence: nil)
        let envelope = try store.envelope(frameID: 7, serverSessionID: "calc-42")
        let parts = try XCTUnwrap(FrameEnvelope.decode(envelope))
        let sent = try JSONDecoder().decode(FrameMeta.self, from: parts.meta)
        XCTAssertEqual(sent.session_id, "calc-42")
        XCTAssertEqual(sent.frame_id, 7)
        XCTAssertEqual(parts.jpeg, jpeg)
        XCTAssertEqual(parts.depth, Data([1, 2, 3, 4]))
        XCTAssertTrue(parts.confidence.isEmpty)
    }

    /// The scan offered again on the home screen: the newest one that reached the calculator and was neither
    /// finished nor abandoned.
    func testWhichInterruptedScanIsOffered() throws {
        XCTAssertNil(SessionStore.unfinished())
        try makeScan("2026-11-20T09-00-00Z", views: 3, sent: 3, server: "calc-a")
        XCTAssertEqual(SessionStore.unfinished(),
                       SessionStore.Unfinished(localID: "2026-11-20T09-00-00Z", serverSessionID: "calc-a", pending: 0, total: 3),
                       "every view was sent but the model was never asked for")
        try makeScan("2026-11-21T09-00-00Z", views: 4, sent: 1, server: "calc-b")
        XCTAssertEqual(SessionStore.unfinished(),
                       SessionStore.Unfinished(localID: "2026-11-21T09-00-00Z", serverSessionID: "calc-b", pending: 3, total: 4))
        // A scan that never reached the calculator cannot be sent from the home screen.
        try makeScan("2026-11-22T09-00-00Z", views: 2, server: nil)
        XCTAssertEqual(SessionStore.unfinished()?.localID, "2026-11-21T09-00-00Z")
        // Once its model was asked for, a scan is no longer "interrupted".
        try SessionStore(resuming: "2026-11-21T09-00-00Z").markFinishRequested()
        XCTAssertEqual(SessionStore.unfinished()?.localID, "2026-11-20T09-00-00Z")
    }

    /// "Les vues prises pour ce plat seront effacées de l'iPhone": they are, and nothing brings the folder back.
    func testAbandoningAScanReallyDeletesIt() throws {
        let store = try SessionStore(localID: "2026-11-21T10-00-00Z")
        try store.save(frameID: 0, jpeg: jpeg, meta: meta(0), depth: nil, confidence: nil)
        store.setServerSession("calc-1")
        XCTAssertTrue(exists(store.root))

        store.delete()
        XCTAssertFalse(exists(store.root), "the views are gone from the iPhone")
        XCTAssertNil(store.nextPending())
        XCTAssertNil(SessionStore.unfinished())
        // A view that was still being prepared when the person abandoned, a file that arrives late:
        XCTAssertThrowsError(try store.save(frameID: 1, jpeg: jpeg, meta: meta(1), depth: nil, confidence: nil))
        XCTAssertThrowsError(try store.saveArtifact(name: "model.glb", data: Data("x".utf8)))
        store.markSent(0)
        store.saveOutcome(FinalOutcome(verdict: ScanVerdict(level: "good")))
        XCTAssertFalse(exists(store.root), "nothing writes into an abandoned scan again")

        // The interrupted scan of the home screen is deleted by its name.
        let other = try makeScan("2026-11-22T10-00-00Z", views: 3, sent: 1)
        SessionStore.delete(localID: "2026-11-22T10-00-00Z")
        XCTAssertFalse(exists(other))
        SessionStore.delete(localID: "")
        XCTAssertTrue(exists(sessions), "an empty name never deletes the folder of all the dishes")
    }

    /// Earlier versions only marked an abandoned scan and kept its views, out of reach: removed when the app starts.
    func testWhatEarlierVersionsLeftBehindIsRemoved() throws {
        let abandoned = try makeScan("2026-11-18T10-00-00Z", views: 5, sent: 2, abandoned: true)
        let empty = try makeScan("2026-11-19T10-00-00Z", views: 0)
        let interrupted = try makeScan("2026-11-20T10-00-00Z", views: 3, sent: 1)
        let computing = try makeScan("2026-11-21T10-00-00Z", views: 3, sent: 3, finishRequested: true)
        let finished = try makeScan("2026-11-22T10-00-00Z", views: 3, sent: 3, finishRequested: true, results: ["model.glb", "apercu.png"])
        // Marked abandoned but holding a model: the library shows it, so it is kept.
        let odd = try makeScan("2026-11-23T10-00-00Z", views: 2, abandoned: true, results: ["model.glb"])
        let shown = DishLibrary.all().map(\.id)

        XCTAssertEqual(SessionStore.removeLeftovers(), 2)
        XCTAssertFalse(exists(abandoned))
        XCTAssertFalse(exists(empty))
        XCTAssertTrue(exists(interrupted))
        XCTAssertTrue(exists(computing))
        XCTAssertTrue(exists(finished))
        XCTAssertTrue(exists(odd))
        XCTAssertEqual(DishLibrary.all().map(\.id), shown, "only folders the library did not show were removed")
        XCTAssertEqual(SessionStore.removeLeftovers(), 0)
    }

    func testTheFinalOutcomeIsKeptWithTheDish() throws {
        let store = try SessionStore(localID: "2026-11-21T10-00-00Z")
        XCTAssertNil(SessionStore.outcome(in: store.root))
        store.saveOutcome(FinalOutcome(verdict: nil))
        XCTAssertNil(SessionStore.outcome(in: store.root), "nothing to say is not written")
        let outcome = FinalOutcome(verdict: ScanVerdict(level: "fair", score: 70, issues: ["holes"]),
                                   fallbacks: [Fallback(code: "texture_failed", message: "Les photos n’ont pas pu être appliquées.")])
        store.saveOutcome(outcome)
        XCTAssertEqual(SessionStore.outcome(in: store.root), outcome)
    }
}
