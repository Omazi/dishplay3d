import XCTest

/// Keeps what one walk through the app produces: a picture of each screen and the findings of Apple's
/// accessibility audit. Both go in the test report; when the folder `SCREENS_DIR` is given (the workflow gives
/// it), they are also written there, as PNG files and one line per finding in `audit.txt`.
@MainActor
struct Recorder {
    let look: Look
    let test: XCTestCase

    private var folder: URL? {
        ProcessInfo.processInfo.environment["SCREENS_DIR"].map { URL(filePath: $0, directoryHint: .isDirectory) }
    }

    /// Picture of the whole screen, then the audit of what the app shows.
    func capture(_ screen: String, _ app: XCUIApplication, audit: Bool = true) {
        let name = "\(look.name)-\(screen)"
        let shot = XCUIScreen.main.screenshot()
        let attachment = XCTAttachment(screenshot: shot)
        attachment.name = name
        attachment.lifetime = .keepAlways
        test.add(attachment)
        if let folder {
            do {
                try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                try shot.pngRepresentation.write(to: folder.appending(path: "\(name).png"))
            } catch {
                XCTFail("Picture \(name) not written: \(error.localizedDescription)")
            }
        }
        if audit, look.audited { self.audit(name, app) }
    }

    /// Findings are written down, not counted as test failures: they are read together with the pictures.
    private func audit(_ name: String, _ app: XCUIApplication) {
        var findings: [String] = []
        do {
            try app.performAccessibilityAudit { issue in
                let element = issue.element.map { element in
                    let frame = element.frame
                    return "type \(element.elementType.rawValue) « \(element.label) » \(Int(frame.width))×\(Int(frame.height)) pt"
                } ?? "-"
                findings.append([name, Self.kind(issue.auditType), issue.compactDescription, element].joined(separator: "\t"))
                return true
            }
        } catch {
            findings.append([name, "audit", "not run: \(error.localizedDescription)", "-"].joined(separator: "\t"))
        }
        if findings.isEmpty { findings.append([name, "ok", "no finding", "-"].joined(separator: "\t")) }
        let text = findings.joined(separator: "\n") + "\n"
        let attachment = XCTAttachment(string: text)
        attachment.name = "audit-\(name)"
        attachment.lifetime = .keepAlways
        test.add(attachment)
        guard let file = folder?.appending(path: "audit.txt") else { return }
        do {
            let existing = (try? String(contentsOf: file, encoding: .utf8)) ?? ""
            try (existing + text).write(to: file, atomically: true, encoding: .utf8)
        } catch {
            XCTFail("Audit of \(name) not written: \(error.localizedDescription)")
        }
    }

    private static func kind(_ type: XCUIAccessibilityAuditType) -> String {
        let names: [(XCUIAccessibilityAuditType, String)] = [
            (.contrast, "contrast"), (.elementDetection, "element-detection"), (.hitRegion, "hit-region"),
            (.sufficientElementDescription, "description"), (.dynamicType, "dynamic-type"),
            (.textClipped, "text-clipped"), (.trait, "trait"),
        ]
        return names.first { type == $0.0 }?.1 ?? "other-\(type.rawValue)"
    }
}
