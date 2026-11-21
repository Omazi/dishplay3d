import XCTest

/// Opens every screen of the app in the iPhone simulator, takes a picture of each and runs Apple's
/// accessibility audit on it. Started by `.github/workflows/ios-screens.yml`, or by hand with the scheme
/// ScreenCheck of `project.screens.yml`.
///
/// Nothing here judges how a screen looks: the pictures are looked at before a release. The simulator has
/// neither camera nor calculator, so the app is started with the `-uitest-…` arguments read by `UITestMode`
/// and with the sample dishes of `Fixtures/Sessions` (the project's synthetic plate, reconstructed by the
/// real engine).
@MainActor
final class ScreenCheckTests: XCTestCase {
    // Numbered so that they run in this order: the light walk is the one looked at first.
    func test1Light() { walk(.light) }
    func test2Dark() { walk(.dark) }
    func test3LargeText() { walk(.largeText) }

    private func walk(_ look: Look) {
        continueAfterFailure = true
        XCUIDevice.shared.appearance = look.isDark ? .dark : .light
        let record = Recorder(look: look, test: self)

        // First launch: the three introduction pages.
        var app = launch(look, onboarded: false)
        if appears(app.buttons["Continuer"]) {
            settle(3)
            record.capture("01-intro-1", app)
            app.buttons["Continuer"].tap()
            settle(1.5)
            record.capture("02-intro-2", app)
            app.buttons["Continuer"].tap()
            settle(1.5)
            record.capture("03-intro-3", app)
        }

        // Nothing linked, nothing scanned yet.
        app = launch(look)
        if appears(app.buttons["Relier le calculateur"]) {
            settle(3)
            record.capture("04-accueil-vide", app)
            open(tab: "Mes plats", in: app)
            record.capture("05-plats-vide", app)
            open(tab: "Réglages", in: app)
            record.capture("06-reglages-a-relier", app)
            let disclosure = app.buttons["Saisie manuelle"].firstMatch
            let manual = disclosure.exists ? disclosure : app.staticTexts["Saisie manuelle"].firstMatch
            if manual.exists {
                manual.tap()
                settle(1)
                record.capture("07-reglages-saisie", app, audit: false)
            }
        }

        // A calculator is linked (it does not answer) and three dishes are on the iPhone: one finished,
        // one being computed, one interrupted.
        app = launch(look, paired: true, sample: true)
        if appears(app.buttons["Scanner un plat"]) {
            settle(3)
            record.capture("08-accueil", app)
            app.swipeUp()
            settle(1)
            record.capture("09-accueil-bas", app, audit: false)
            // After a scroll down the tab bar of iOS 26 shrinks to the current tab alone: start again from the top.
            app = launch(look, paired: true, sample: true)
            open(tab: "Mes plats", in: app)
            settle(1.5)
            record.capture("10-plats", app)
            let finished = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Assiette")).firstMatch
            if appears(finished) {
                finished.tap()
                settle(2.5)
                record.capture("11-plat", app)
                app.swipeUp()
                settle(1)
                record.capture("12-plat-bas", app, audit: false)
                let onTable = app.buttons["Voir sur votre table"]
                if !look.isDark, look.textSize == nil, onTable.exists {
                    // iOS's own viewer opens the textured model: the simulator shows it in 3D, without the camera.
                    onTable.tap()
                    settle(8)
                    record.capture("13-plat-apercu-ios", app, audit: false)
                }
            }
            app = launch(look, paired: true, sample: true)
            open(tab: "Mes plats", in: app)
            let computing = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Couscous")).firstMatch
            if appears(computing) {
                computing.tap()
                settle(2.5)
                record.capture("14-plat-en-cours", app)
            }
            app = launch(look, paired: true, sample: true)
            open(tab: "Réglages", in: app)
            settle(1.5)
            record.capture("15-reglages", app)
        }

        // The scanner, at five moments of a scan.
        for (index, moment) in ["box", "scanning", "paused", "finishing", "done"].enumerated() {
            app = launch(look, paired: true, sample: true, scan: moment)
            if appears(app.buttons["Quitter le scan"]) {
                settle(4)
                record.capture("\(16 + index)-scan-\(moment)", app)
            }
        }
        app.terminate()
    }

    // MARK: pieces

    private func launch(_ look: Look, onboarded: Bool = true, paired: Bool = false, sample: Bool = false,
                        scan: String? = nil) -> XCUIApplication {
        let app = XCUIApplication()
        // French, as on the iPhones the app is made for: dates and numbers are then written the French way.
        var arguments = ["-AppleLanguages", "(fr)", "-AppleLocale", "fr_FR",
                         "-onboarding.done", onboarded ? "YES" : "NO",
                         "-uitest-sessions", sessions(sample: sample).path(percentEncoded: false)]
        if paired { arguments.append("-uitest-paired") }
        if let scan { arguments += ["-uitest-scan", scan] }
        if let size = look.textSize { arguments += ["-UIPreferredContentSizeCategoryName", size] }
        app.launchArguments = arguments
        app.launch()
        return app
    }

    /// A fresh folder of dishes for one launch: empty, or a copy of the sample dishes (the app writes in it).
    private func sessions(sample: Bool) -> URL {
        let folder = FileManager.default.temporaryDirectory
            .appending(path: "screen-check-\(UUID().uuidString)", directoryHint: .isDirectory)
        do {
            if sample {
                guard let fixture = Bundle(for: ScreenCheckTests.self).url(forResource: "Sessions", withExtension: nil) else {
                    XCTFail("The sample dishes are not in the test bundle")
                    return folder
                }
                try FileManager.default.copyItem(at: fixture, to: folder)
            } else {
                try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            }
        } catch {
            XCTFail("Folder of dishes not prepared: \(error.localizedDescription)")
        }
        return folder
    }

    private func appears(_ element: XCUIElement, within seconds: TimeInterval = 20) -> Bool {
        let found = element.waitForExistence(timeout: seconds)
        XCTAssertTrue(found, "Not on screen: \(element)")
        return found
    }

    private func open(tab name: String, in app: XCUIApplication) {
        let inBar = app.tabBars.buttons[name].firstMatch
        let button = inBar.waitForExistence(timeout: 8) ? inBar : app.buttons[name].firstMatch
        if appears(button, within: 8) { button.tap() }
        settle(1)
    }

    /// Lets entrance animations finish before the picture.
    private func settle(_ seconds: TimeInterval) {
        RunLoop.current.run(until: Date.now.addingTimeInterval(seconds))
    }
}
