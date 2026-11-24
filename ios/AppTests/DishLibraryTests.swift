import ScanCore
import XCTest
@testable import DishPlayScan

/// What "Mes plats" reads from the folders on the iPhone.
final class DishLibraryTests: StorageTestCase {
    func testADishIsReadyBeingCalculatedOrInterrupted() throws {
        try makeScan("2026-11-18T12-30-00Z", views: 3, sent: 3, server: "calc-a", finishRequested: true,
                     results: ["apercu.png", "model.glb", "model.usdz", "final_preview.dpg"])
        try makeScan("2026-11-19T19-05-00Z", views: 3, sent: 3, server: "calc-b", finishRequested: true)
        let interrupted = try makeScan("2026-11-20T20-15-00Z", views: 3, sent: 1, server: "calc-c")
        try Data("  Couscous royal \n".utf8).write(to: interrupted.appendingPathComponent("name.txt"))
        // Not shown: a scan without any view, and what an earlier version left of an abandoned scan.
        try makeScan("2026-11-21T08-00-00Z", views: 0)
        try makeScan("2026-11-21T09-00-00Z", views: 4, abandoned: true)

        let dishes = DishLibrary.all()
        XCTAssertEqual(dishes.map(\.id), ["2026-11-20T20-15-00Z", "2026-11-19T19-05-00Z", "2026-11-18T12-30-00Z"], "newest first")

        let waiting = dishes[0]
        XCTAssertEqual(waiting.state, .interrupted)
        XCTAssertEqual(waiting.name, "Couscous royal")
        XCTAssertEqual(waiting.frames, 3)
        XCTAssertEqual(waiting.pendingViews, 2, "two views never reached the calculator")
        XCTAssertEqual(waiting.serverSessionID, "calc-c")
        XCTAssertNotNil(waiting.photo, "a dish always has a face: one of its views")
        XCTAssertNil(waiting.model)
        XCTAssertNil(waiting.arModel)

        let computing = dishes[1]
        XCTAssertEqual(computing.state, .processing)
        XCTAssertEqual(computing.pendingViews, 0)
        XCTAssertTrue(computing.name.hasPrefix("Plat du "), "without a name of its own, a dish is named after its date")

        let ready = dishes[2]
        XCTAssertEqual(ready.state, .ready)
        XCTAssertNotNil(ready.picture)
        XCTAssertNotNil(ready.model)
        XCTAssertNotNil(ready.arModel)
        XCTAssertNotNil(ready.geometry)
        XCTAssertNil(ready.outcome, "this calculator gave no verdict")
        XCTAssertNil(ready.scaleCheck, "no real width was typed for this dish")
    }

    /// The width typed in Réglages before a scan: the calculator's report says what the model measures.
    func testTheCheckOfTheRealWidthComesWithAReadyDish() throws {
        let root = try makeScan("2026-11-18T12-30-00Z", views: 3, sent: 3, finishRequested: true, results: ["model.glb"])
        let report = #"{"schema":"dishplay.report/1","mesh":{"triangles":9000},"scale_check":{"reference_width_m":0.26,"measured_width_m":0.2631,"error_pct":1.19}}"#
        try Data(report.utf8).write(to: root.appendingPathComponent("results/report.json"))
        let dish = try XCTUnwrap(DishLibrary.all().first)
        XCTAssertEqual(dish.scaleCheck?.text, "26,3 cm pour 26 cm saisis")
        XCTAssertEqual(dish.scaleCheck?.matches, true)
    }

    /// Before any view left for the calculator, the dish has no name there.
    func testADishThatNeverReachedTheCalculator() throws {
        try makeScan("2026-11-20T20-15-00Z", views: 2, server: nil)
        let dish = try XCTUnwrap(DishLibrary.all().first)
        XCTAssertNil(dish.serverSessionID)
        XCTAssertEqual(dish.pendingViews, 2)
        XCTAssertEqual(dish.state, .interrupted)
    }

    func testTheFinalOutcomeComesWithAReadyDish() throws {
        let outcome = FinalOutcome(verdict: ScanVerdict(level: "poor", score: 30, issues: ["sides_missing"]),
                                   fallbacks: [Fallback(code: "table_kept", message: "La table n’a pas pu être retirée autour du plat.")])
        try makeScan("2026-11-18T12-30-00Z", views: 3, sent: 3, finishRequested: true, results: ["model.glb"])
        try SessionStore(resuming: "2026-11-18T12-30-00Z").saveOutcome(outcome)
        // Kept for a dish still being calculated too, but only a finished model has a verdict to show.
        try makeScan("2026-11-19T19-05-00Z", views: 3, sent: 3, finishRequested: true)
        try SessionStore(resuming: "2026-11-19T19-05-00Z").saveOutcome(outcome)

        let dishes = DishLibrary.all()
        XCTAssertEqual(dishes.count, 2)
        XCTAssertNil(dishes[0].outcome)
        XCTAssertEqual(dishes[1].outcome, outcome)
        XCTAssertEqual(dishes[1].outcome?.verdict?.level, "poor")
        XCTAssertEqual(dishes[1].outcome?.fallbacks.first?.message, "La table n’a pas pu être retirée autour du plat.")
    }

    func testRenamingAndDeleting() throws {
        let root = try makeScan("2026-11-20T20-15-00Z", views: 2)
        var dish = try XCTUnwrap(DishLibrary.all().first)
        DishLibrary.rename(dish, to: "  Tajine aux pruneaux ")
        dish = try XCTUnwrap(DishLibrary.all().first)
        XCTAssertEqual(dish.name, "Tajine aux pruneaux")
        DishLibrary.rename(dish, to: "   ")
        XCTAssertEqual(DishLibrary.all().first?.name, "Tajine aux pruneaux", "an empty name changes nothing")

        DishLibrary.delete(dish)
        XCTAssertFalse(exists(root), "the views and the model leave the iPhone")
        XCTAssertTrue(DishLibrary.all().isEmpty)
    }

    func testTheDateOfADishIsReadFromItsFolder() throws {
        let date = try XCTUnwrap(DishLibrary.parseDate("2026-11-16T19-52-03Z"))
        var utc = Calendar(identifier: .gregorian)
        utc.timeZone = try XCTUnwrap(TimeZone(identifier: "UTC"))
        let parts = utc.dateComponents([.year, .month, .day, .hour, .minute, .second], from: date)
        XCTAssertEqual(parts.year, 2026)
        XCTAssertEqual(parts.month, 11)
        XCTAssertEqual(parts.day, 16)
        XCTAssertEqual(parts.hour, 19)
        XCTAssertEqual(parts.minute, 52)
        XCTAssertEqual(parts.second, 3)
        XCTAssertNil(DishLibrary.parseDate("screen-check"))
    }
}
