import Foundation

// What the calculator answers to the app, read from JSON. Every type here reads leniently: a field that is
// missing, null or of another kind than expected is taken as absent, so that one odd value never hides the
// rest of an answer. A calculator older than the queue (engine before p1-0.11.0) does not send the newer
// fields at all.

extension KeyedDecodingContainer {
    /// The value under `key`, or nil when it is missing, null or of another kind.
    func lenient<T: Decodable>(_ type: T.Type, _ key: Key) -> T? {
        guard let value = try? decodeIfPresent(type, forKey: key) else { return nil }
        return value
    }

    /// A whole number, also accepted when it is written with a decimal point (2.0).
    func lenientInt(_ key: Key) -> Int? {
        if let whole = lenient(Int.self, key) { return whole }
        if let real = lenient(Double.self, key), real.isFinite, abs(real) < 1e12 { return Int(real.rounded()) }
        return nil
    }
}

/// The calculator's judgement of a model: the same block as the live quality sent with each preview.
public struct ScanVerdict: Codable, Equatable, Hashable, Sendable {
    /// good, fair, poor or too_early.
    public var level: String
    /// 0 to 100.
    public var score: Int?
    /// sides_missing, holes, fragmented, uniform_or_shiny, few_views, box_too_low.
    public var issues: [String]

    public init(level: String, score: Int? = nil, issues: [String] = []) {
        self.level = level
        self.score = score
        self.issues = issues
    }

    private enum CodingKeys: String, CodingKey { case level, score, issues }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        level = try c.decode(String.self, forKey: .level)
        score = c.lenientInt(.score)
        issues = c.lenient([String].self, .issues) ?? []
    }
}

/// Something the final calculation could not do as planned, and what it did instead (photos not applied as a
/// texture, table left around the dish…).
public struct Fallback: Codable, Equatable, Hashable, Sendable {
    public var code: String
    /// One French sentence written by the calculator, shown as it is.
    public var message: String

    public init(code: String, message: String) {
        self.code = code
        self.message = message
    }

    private enum CodingKeys: String, CodingKey { case code, message }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        code = c.lenient(String.self, .code) ?? ""
        message = (c.lenient(String.self, .message) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

/// How a final model came out: the calculator's verdict on it, and what it had to give up on the way.
/// Kept with the dish on the iPhone so that the screens can show it.
public struct FinalOutcome: Codable, Equatable, Hashable, Sendable {
    public var verdict: ScanVerdict?
    public var fallbacks: [Fallback]

    public init(verdict: ScanVerdict?, fallbacks: [Fallback] = []) {
        self.verdict = verdict
        self.fallbacks = fallbacks
    }

    /// Nothing to show: no verdict and no fallback.
    public var isEmpty: Bool { verdict == nil && fallbacks.isEmpty }

    private enum CodingKeys: String, CodingKey { case verdict, fallbacks }

    /// Never fails: an object without these two fields, or something that is not an object, gives an empty outcome.
    public init(from decoder: Decoder) throws {
        guard let c = try? decoder.container(keyedBy: CodingKeys.self) else {
            verdict = nil
            fallbacks = []
            return
        }
        verdict = c.lenient(ScanVerdict.self, .verdict)
        fallbacks = (c.lenient([Fallback].self, .fallbacks) ?? []).filter { !$0.message.isEmpty }
    }

    /// From the bytes of a JSON object that has "verdict" and "fallbacks" at its top. nil when it has neither.
    public static func read(_ data: Data) -> FinalOutcome? {
        guard let outcome = try? JSONDecoder().decode(FinalOutcome.self, from: data), !outcome.isEmpty else { return nil }
        return outcome
    }

    /// The bytes `read` understands, for keeping the outcome in a file.
    public func jsonData() throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return try encoder.encode(self)
    }
}

/// The check of the model's size against the width of the container typed by the person before the scan
/// ("scale_check" in the calculator's report.json). The width changes nothing in the model: it only says
/// whether the model came out at the right size.
public struct ScaleCheck: Equatable, Hashable, Sendable {
    /// The width typed by the person, in metres.
    public var referenceWidthM: Double
    /// The width of the dish in the model, in metres; nil when the calculator could not measure it.
    public var measuredWidthM: Double?

    public init(referenceWidthM: Double, measuredWidthM: Double?) {
        self.referenceWidthM = referenceWidthM
        self.measuredWidthM = measuredWidthM
    }

    private struct Report: Decodable {
        struct Check: Decodable {
            var reference: Double?
            var measured: Double?

            private enum CodingKeys: String, CodingKey {
                case reference = "reference_width_m"
                case measured = "measured_width_m"
            }

            init(from decoder: Decoder) throws {
                let c = try decoder.container(keyedBy: CodingKeys.self)
                reference = c.lenient(Double.self, .reference)
                measured = c.lenient(Double.self, .measured)
            }
        }

        var check: Check?

        private enum CodingKeys: String, CodingKey { case check = "scale_check" }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            check = c.lenient(Check.self, .check)
        }
    }

    /// From the bytes of the calculator's report. nil when no width was typed for this dish, and when the
    /// report cannot be read.
    public static func read(_ report: Data) -> ScaleCheck? {
        guard let check = (try? JSONDecoder().decode(Report.self, from: report))?.check,
              let reference = check.reference, reference.isFinite, reference > 0 else { return nil }
        let measured = check.measured.flatMap { $0.isFinite && $0 > 0 ? $0 : nil }
        return ScaleCheck(referenceWidthM: reference, measuredWidthM: measured)
    }

    /// "24,3 cm pour 24 cm saisis", written the French way. Without a measure: "non mesurée (24 cm saisis)".
    public var text: String {
        let typed = ScaleCheck.centimetres(referenceWidthM)
        guard let measuredWidthM else { return "non mesurée (\(typed) saisis)" }
        return "\(ScaleCheck.centimetres(measuredWidthM)) pour \(typed) saisis"
    }

    /// Whether the model is within 5 % of the width typed; nil without a measure.
    public var matches: Bool? {
        guard let measuredWidthM else { return nil }
        return abs(measuredWidthM - referenceWidthM) <= 0.05 * referenceWidthM
    }

    /// "24,3 cm": at most one decimal, with a comma.
    static func centimetres(_ metres: Double) -> String {
        let tenths = (metres * 1000).rounded()
        let whole = Int(tenths / 10)
        let decimal = Int(tenths) - whole * 10
        return decimal == 0 ? "\(whole) cm" : "\(whole),\(decimal) cm"
    }
}

/// What the calculator says about one scan (`GET /sessions/{id}`).
public struct SessionStatus: Decodable, Equatable, Sendable {
    /// capturing, paused, finishing, done, failed.
    public var state: String
    /// A live process is working on this scan right now.
    public var active: Bool
    /// The final model exists on the calculator.
    public var ready: Bool
    /// The calculator is finishing another scan.
    public var busyWithOther: Bool
    /// Where the final calculation stands, when it can be counted.
    public var step: String?
    public var done: Int?
    public var total: Int?
    /// The final calculation of this scan waits its turn. nil with a calculator that has no queue.
    public var queued: Bool?
    /// 1 = next.
    public var queuePosition: Int?
    /// The views are kept, and the live preview starts when the calculator is free.
    public var waiting: Bool
    /// The final calculation failed; it can be asked again.
    public var failed: Bool
    /// One short French sentence from the calculator about that failure.
    public var error: String?
    /// The verdict on the final model and what the calculation gave up, when the calculator says so.
    public var outcome: FinalOutcome?

    public init(state: String = "", active: Bool = false, ready: Bool = false, busyWithOther: Bool = false,
                step: String? = nil, done: Int? = nil, total: Int? = nil, queued: Bool? = nil, queuePosition: Int? = nil,
                waiting: Bool = false, failed: Bool = false, error: String? = nil, outcome: FinalOutcome? = nil) {
        self.state = state
        self.active = active
        self.ready = ready
        self.busyWithOther = busyWithOther
        self.step = step
        self.done = done
        self.total = total
        self.queued = queued
        self.queuePosition = queuePosition
        self.waiting = waiting
        self.failed = failed
        self.error = error
        self.outcome = outcome
    }

    private enum CodingKeys: String, CodingKey {
        case state, active, ready, progress, queued, waiting, failed, error
        case busyWithOther = "busy_with_other"
        case queuePosition = "queue_position"
    }

    private enum ProgressKeys: String, CodingKey { case step, done, total }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        state = c.lenient(String.self, .state) ?? ""
        active = c.lenient(Bool.self, .active) ?? false
        ready = c.lenient(Bool.self, .ready) ?? false
        busyWithOther = c.lenient(Bool.self, .busyWithOther) ?? false
        if let p = try? c.nestedContainer(keyedBy: ProgressKeys.self, forKey: .progress) {
            step = p.lenient(String.self, .step)
            done = p.lenientInt(.done)
            total = p.lenientInt(.total)
        } else {
            step = nil
            done = nil
            total = nil
        }
        queued = c.lenient(Bool.self, .queued)
        queuePosition = c.lenientInt(.queuePosition)
        waiting = c.lenient(Bool.self, .waiting) ?? false
        failed = c.lenient(Bool.self, .failed) ?? false
        let sentence = c.lenient(String.self, .error)?.trimmingCharacters(in: .whitespacesAndNewlines)
        error = (sentence?.isEmpty == false) ? sentence : nil
        // "verdict" and "fallbacks" sit at the top of the answer, next to the other fields.
        let read = try? FinalOutcome(from: decoder)
        outcome = (read?.isEmpty == false) ? read : nil
    }

    /// Fails only when the bytes are not a JSON object.
    public static func decode(_ data: Data) throws -> SessionStatus {
        try JSONDecoder().decode(SessionStatus.self, from: data)
    }
}

/// Answer to `POST /sessions`.
public struct SessionCreated: Decodable, Equatable, Sendable {
    public var id: String
    /// The calculator is finishing another dish: the views sent are kept, and the live preview starts by
    /// itself when it is free.
    public var waiting: Bool

    public init(id: String, waiting: Bool = false) {
        self.id = id
        self.waiting = waiting
    }

    private enum CodingKeys: String, CodingKey {
        case id = "session_id"
        case waiting
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        waiting = c.lenient(Bool.self, .waiting) ?? false
    }

    /// nil when the answer names no scan.
    public static func decode(_ data: Data) -> SessionCreated? {
        guard let created = try? JSONDecoder().decode(SessionCreated.self, from: data), !created.id.isEmpty else { return nil }
        return created
    }
}

/// Answer to `POST /sessions/{id}/finish`.
public struct FinishAnswer: Decodable, Equatable, Sendable {
    /// The final calculation waits behind another dish.
    public var queued: Bool
    /// 1 = next.
    public var position: Int?

    public init(queued: Bool = false, position: Int? = nil) {
        self.queued = queued
        self.position = position
    }

    private enum CodingKeys: String, CodingKey { case queued, position }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        queued = c.lenient(Bool.self, .queued) ?? false
        position = c.lenientInt(.position)
    }

    /// An answer that cannot be read is the one of a calculator without a queue: started at once.
    public static func decode(_ data: Data) -> FinishAnswer {
        (try? JSONDecoder().decode(FinishAnswer.self, from: data)) ?? FinishAnswer()
    }
}

/// Answer to `POST /sessions/{id}/resume_worker`.
public struct WorkerAnswer: Decodable, Equatable, Sendable {
    /// Another dish is being finished: this scan is taken up again when the calculator is free.
    public var waiting: Bool

    public init(waiting: Bool = false) { self.waiting = waiting }

    private enum CodingKeys: String, CodingKey { case waiting }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        waiting = c.lenient(Bool.self, .waiting) ?? false
    }

    public static func decode(_ data: Data) -> WorkerAnswer {
        (try? JSONDecoder().decode(WorkerAnswer.self, from: data)) ?? WorkerAnswer()
    }
}

/// Answer to `PUT /sessions/{id}/frames/{n}`.
public struct FrameAnswer: Decodable, Equatable, Sendable {
    /// Whether a live process took the view at once. false: the view is stored, but nothing works on this
    /// scan for now (the calculator was restarted, or it is finishing another dish). nil: not said.
    public var queued: Bool?

    public init(queued: Bool? = nil) { self.queued = queued }

    private enum CodingKeys: String, CodingKey { case queued }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        queued = c.lenient(Bool.self, .queued)
    }

    public static func decode(_ data: Data) -> FrameAnswer {
        (try? JSONDecoder().decode(FrameAnswer.self, from: data)) ?? FrameAnswer()
    }
}
