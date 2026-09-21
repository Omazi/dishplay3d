import XCTest

final class CameraStartupUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }
    private func openCamera(_ mode: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchEnvironment["DISHPLAY_TEST_CAMERA"] = mode
        app.launchArguments = ["-AppleLanguages", "(fr)", "-AppleLocale", "fr_FR"]
        app.launch()
        let start = app.buttons["open-guided-scan"]
        XCTAssertTrue(start.waitForExistence(timeout: 15))
        start.tap()
        XCTAssertTrue(app.buttons["scan-close"].waitForExistence(timeout: 10), "Camera failure must not hide navigation")
        return app
    }
    private func evidence(_ name: String, app: XCUIApplication) {
        // App-region screenshots can be cropped incorrectly during a device rotation.
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name; attachment.lifetime = .keepAlways
        add(attachment)
    }
    func testMissingFramesShowsRecoveryAndCanReopen() {
        let app = openCamera("no-frames")
        let retry = app.buttons["scan-retry-camera"]
        XCTAssertTrue(retry.waitForExistence(timeout: 15), "No images must produce a bounded error, never a silent black view")
        XCTAssertTrue(retry.isHittable)
        XCTAssertTrue(app.buttons["scan-close"].isHittable)
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "Aucune image")).firstMatch.exists)
        evidence("missing-camera-frames-portrait", app: app)
        retry.tap()
        XCTAssertTrue(app.staticTexts["Ouverture de la caméra…"].waitForExistence(timeout: 3))
        XCTAssertTrue(retry.waitForExistence(timeout: 15), "Restart must remain recoverable if the device supplies no camera stream")
        app.buttons["scan-close"].tap()
        let open = app.buttons["open-guided-scan"]
        XCTAssertTrue(open.waitForExistence(timeout: 5)); open.tap()
        XCTAssertTrue(app.buttons["scan-close"].waitForExistence(timeout: 5))
        app.buttons["scan-close"].tap()
    }
    func testDeniedPermissionIsVisibleInBothOrientations() {
        let app = openCamera("denied")
        XCTAssertTrue(app.buttons["scan-retry-camera"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "accès à la caméra")).firstMatch.exists)
        evidence("camera-denied-portrait", app: app)
        XCUIDevice.shared.orientation = .landscapeLeft
        let landscape = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            app.frame.width > app.frame.height
        }, object: app)
        XCTAssertEqual(XCTWaiter.wait(for: [landscape], timeout: 5), .completed)
        XCTAssertTrue(app.buttons["scan-close"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["scan-close"].isHittable)
        XCTAssertTrue(app.buttons["scan-retry-camera"].isHittable)
        evidence("camera-denied-landscape", app: app)
        XCUIDevice.shared.orientation = .portrait
        app.buttons["scan-close"].tap()
        XCTAssertTrue(app.buttons["open-guided-scan"].waitForExistence(timeout: 5))
    }
}
