#if DEBUG
import Foundation

/// What the automated screen check asks of the app, through launch arguments. The check runs in the iPhone
/// simulator, which has neither camera nor calculator. Debug builds only: none of this is in the app sent to
/// TestFlight.
enum UITestMode {
    /// `-uitest-paired`: behave as if a calculator was linked.
    static var paired: Bool { arguments.contains("-uitest-paired") }

    /// `-uitest-sessions <folder>`: read the dishes from this folder instead of the app's own documents.
    /// Always given by the screen check, which is recognised by it: the app then also behaves like an
    /// iPhone that can follow its own movement, which the simulator cannot.
    static var sessions: URL? {
        value(after: "-uitest-sessions").map { URL(filePath: $0, directoryHint: .isDirectory) }
    }

    /// `-uitest-scan <moment>`: open the scanner at this moment of a scan (see `ScanController.stage`).
    static var scanMoment: String? { value(after: "-uitest-scan") }

    private static let arguments = ProcessInfo.processInfo.arguments

    private static func value(after flag: String) -> String? {
        guard let index = arguments.firstIndex(of: flag), arguments.indices.contains(index + 1) else { return nil }
        return arguments[index + 1]
    }
}
#endif
