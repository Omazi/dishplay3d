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
        XCTAssertNil(counted.advice, "what the calculator says needs no second line")
    }

    /// With the calculator switched off every unfinished dish used to read "Calculateur injoignable": which one
    /// still had views to send could not be told, nor what to do.
    @MainActor
    func testADishKeepsItsOwnStateWhenTheCalculatorIsAway() throws {
        try makeScan("2026-11-19T19-05-00Z", views: 3, sent: 3, finishRequested: true)
        try makeScan("2026-11-20T20-15-00Z", views: 5, sent: 2)
        try makeScan("2026-11-21T08-00-00Z", views: 4, sent: 4)
        let dishes = DishLibrary.all()
        XCTAssertEqual(dishes.map(\.ownStateText), ["Calcul à lancer", "3 vues à envoyer", "Calcul demandé"])

        let asked = AppModel.DishProgress.withoutCalculator(dishes[2], linked: true)
        XCTAssertEqual(asked.text, "Calcul demandé")
        XCTAssertEqual(asked.advice, "Calculateur injoignable. Allumez-le : le modèle arrivera tout seul.")
        XCTAssertFalse(asked.canComplete)

        let toSend = AppModel.DishProgress.withoutCalculator(dishes[1], linked: true)
        XCTAssertEqual(toSend.text, "3 vues à envoyer")
        XCTAssertEqual(toSend.advice, "Calculateur injoignable. Allumez-le pour terminer ce plat.")

        let unlinked = AppModel.DishProgress.withoutCalculator(dishes[1], linked: false)
        XCTAssertEqual(unlinked.text, "3 vues à envoyer")
        XCTAssertEqual(unlinked.advice, "Reliez le calculateur dans Réglages pour terminer ce plat.")

        let lost = AppModel.DishProgress.lost("Inconnu du calculateur")
        XCTAssertEqual(lost.text, "Inconnu du calculateur")
        XCTAssertNotNil(lost.advice, "the person is told the scan can only be deleted")
        XCTAssertFalse(lost.canComplete)
    }

    /// What the app says when the calculator refuses a request.
    @MainActor
    func testRefusalsOfTheCalculatorAreSaidInPlainWords() {
        // Its disk is full: the calculator's own French sentence is shown as it is.
        let full = TransportError.http(507, "Le disque du PC est plein : libérez de la place sur le PC, l'envoi reprendra tout seul.")
        XCTAssertEqual(AppModel.explain(full, brief: true), "Le disque du PC est plein : libérez de la place sur le PC, l'envoi reprendra tout seul.")
        XCTAssertFalse(AppModel.explain(TransportError.http(507, "")).isEmpty)
        // Too many wrong codes: it says how long to wait. An older calculator stays closed until restarted.
        XCTAssertEqual(AppModel.explain(TransportError.http(429, "Trop d'essais : attendez 42 s avant de réessayer.")),
                       "Trop d'essais : attendez 42 s avant de réessayer.")
        XCTAssertTrue(AppModel.explain(TransportError.http(429, "too many attempts")).contains("redémarrez le calculateur"))
        // Its other refusals are written in English for developers: never shown.
        let odd = AppModel.explain(TransportError.http(422, "box.size_m.height: ensure this value is greater than 0.01"))
        XCTAssertFalse(odd.contains("size_m"))
        XCTAssertFalse(odd.contains("422"))
        XCTAssertEqual(AppModel.explain(TransportError.http(409, "another session is being finished")), AppModel.busyText)
        // The calculator is away: one line for a card, the things to check for the settings screen.
        let away = URLError(.timedOut)
        XCTAssertEqual(AppModel.explain(away, brief: true), "Le calculateur ne répond pas.")
        XCTAssertTrue(AppModel.explain(away).contains("Réseau local"))
        XCTAssertFalse(AppModel.explain(away).contains("code"), "no error number in a sentence the app understands")
        for sentence in [AppModel.explain(away), AppModel.explain(URLError(.cannotConnectToHost)), AppModel.explain(URLError(.secureConnectionFailed))] {
            XCTAssertFalse(sentence.contains("ordinateur"), "one name for the machine: calculateur (on the PC)")
            XCTAssertFalse(sentence.lowercased().contains("jumel"), "one verb: relier")
        }
    }
}
