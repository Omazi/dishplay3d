import Foundation

/// The version a calculator gives for its engine in `GET /health`, written like "p1-0.11.0": a phase, then
/// numbers separated by dots.
public struct EngineVersion: Comparable, Sendable {
    public var phase: Int
    public var numbers: [Int]

    public init(phase: Int, numbers: [Int]) {
        self.phase = phase
        self.numbers = numbers
    }

    /// nil when the text is not written like "p1-0.11.0" (or "0.11.0"). Letters after a number are ignored
    /// ("0.11.0-beta" reads as 0.11.0).
    public init?(_ text: String) {
        var rest = Substring(text.trimmingCharacters(in: .whitespacesAndNewlines))
        var readPhase = 0
        if rest.hasPrefix("p"), let dash = rest.firstIndex(of: "-") {
            guard let value = Int(rest[rest.index(after: rest.startIndex)..<dash]), value >= 0 else { return nil }
            readPhase = value
            rest = rest[rest.index(after: dash)...]
        }
        var readNumbers: [Int] = []
        for part in rest.split(separator: ".", omittingEmptySubsequences: false) {
            let digits = part.prefix(while: { $0.isASCII && $0.isNumber })
            guard let value = Int(digits) else { return nil }
            readNumbers.append(value)
        }
        guard !readNumbers.isEmpty else { return nil }
        phase = readPhase
        numbers = readNumbers
    }

    /// A missing number counts as zero: 0.11 and 0.11.0 are the same version.
    public static func < (a: EngineVersion, b: EngineVersion) -> Bool {
        if a.phase != b.phase { return a.phase < b.phase }
        for i in 0..<max(a.numbers.count, b.numbers.count) {
            let x = i < a.numbers.count ? a.numbers[i] : 0
            let y = i < b.numbers.count ? b.numbers[i] : 0
            if x != y { return x < y }
        }
        return false
    }

    public static func == (a: EngineVersion, b: EngineVersion) -> Bool { !(a < b) && !(b < a) }

    /// The first engine that keeps a queue of calculations: a dish being finished is never stopped by a new
    /// scan, and finish requests wait their turn.
    public static let firstWithQueue = EngineVersion(phase: 1, numbers: [0, 11, 0])

    /// Whether the calculator that gives this engine text keeps a queue. A text that cannot be read counts
    /// as an older calculator: the careful choice, because an older one stops a calculation when a scan starts.
    public static func hasQueue(_ engine: String) -> Bool {
        guard let version = EngineVersion(engine) else { return false }
        return version >= firstWithQueue
    }
}

/// What the app must not do with a calculator older than the queue.
public enum OlderCalculator {
    /// Such a calculator works on one scan at a time. Before starting a scan, must the app ask it what that
    /// scan is doing? (`activeSession` and `workerAlive` come from `GET /health`.)
    public static func mustLookAtActiveSession(engine: String, activeSession: String?, workerAlive: Bool?) -> Bool {
        if EngineVersion.hasQueue(engine) { return false }
        guard let activeSession, !activeSession.isEmpty else { return false }
        return workerAlive == true
    }

    /// True when starting a scan now would stop the dish the calculator is finishing. `activeState` is the
    /// state of the scan it works on (`GET /sessions/{id}`), `activeReady` whether that scan already has its model.
    public static func newScanWouldStopACalculation(engine: String, activeState: String, activeReady: Bool) -> Bool {
        if EngineVersion.hasQueue(engine) { return false }
        return activeState == "finishing" && !activeReady
    }
}
