import ScanCore
import XCTest
@testable import DishPlayScan

/// What the app's model does with the scans kept on the iPhone. No calculator is linked in these tests.
final class AppModelTests: StorageTestCase {
    /// The card of the home screen says "Les vues prises pour ce plat seront effacées de l'iPhone".
    @MainActor
    func testAbandoningTheInterruptedScanDeletesItsViews() throws {
        let kept = try makeScan("2026-11-20T09-00-00Z", views: 2, sent: 2, finishRequested: true)
        let interrupted = try makeScan("2026-11-21T09-00-00Z", views: 4, sent: 1)
        let model = AppModel()
        XCTAssertEqual(model.pendingScan?.localID, "2026-11-21T09-00-00Z")
        XCTAssertEqual(model.pendingScan?.pending, 3)

        model.discardPending()
        XCTAssertFalse(exists(interrupted), "the views are gone, not only hidden")
        XCTAssertNil(model.pendingScan)
        XCTAssertTrue(exists(kept), "another dish is not touched")
        XCTAssertEqual(DishLibrary.all().map(\.id), ["2026-11-20T09-00-00Z"])
    }

    /// Scans abandoned with an earlier version were only hidden: opening the app removes them.
    @MainActor
    func testOpeningTheAppRemovesScansAbandonedEarlier() throws {
        let abandoned = try makeScan("2026-11-19T09-00-00Z", views: 6, sent: 2, abandoned: true)
        let interrupted = try makeScan("2026-11-21T09-00-00Z", views: 4, sent: 1)
        let model = AppModel()
        XCTAssertFalse(exists(abandoned))
        XCTAssertTrue(exists(interrupted))
        XCTAssertEqual(model.pendingScan?.localID, "2026-11-21T09-00-00Z")
    }

    /// What the dish screen shows comes from `DishStanding` (tested in ScanCore): the button, and which one.
    @MainActor
    func testWhatTheDishScreenOffers() {
        let queued = AppModel.DishProgress(DishStanding.queued(position: 2))
        XCTAssertEqual(queued.text, "En attente, 2e dans la file")
        XCTAssertFalse(queued.canComplete)
        XCTAssertFalse(queued.restart)

        let failed = AppModel.DishProgress(DishStanding.failed(message: "Le modèle n’a pas pu être construit."))
        XCTAssertEqual(failed.text, "Le modèle n’a pas pu être construit.")
        XCTAssertTrue(failed.canComplete)
        XCTAssertTrue(failed.restart, "after a failure the button asks for the calculation again")

        let toSend = AppModel.DishProgress(DishStanding.viewsToSend(3))
        XCTAssertTrue(toSend.canComplete)
        XCTAssertFalse(toSend.restart)

        let counted = AppModel.DishProgress(DishStanding.computing(step: "depth", done: 10, total: 40))
        XCTAssertEqual(counted.fraction ?? 0, 0.25, accuracy: 1e-9)
        XCTAssertFalse(counted.canComplete)
    }
}
