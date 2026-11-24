import XCTest
@testable import ScanCore

/// What the app understands of the calculator's answers, and what it decides from them. No network here: the
/// answers are written as the calculator sends them (engine p1-0.10.0, without the queue, and p1-0.11.0, with it).
final class EngineVersionTests: XCTestCase {
    func testReadsAndCompares() throws {
        let old = try XCTUnwrap(EngineVersion("p1-0.10.0"))
        let new = try XCTUnwrap(EngineVersion("p1-0.11.0"))
        XCTAssertEqual(old.phase, 1)
        XCTAssertEqual(old.numbers, [0, 10, 0])
        XCTAssertTrue(old < new)
        XCTAssertTrue(try XCTUnwrap(EngineVersion("p1-0.9.4")) < old, "9 comes before 10: numbers, not letters")
        XCTAssertTrue(new < (try XCTUnwrap(EngineVersion("p1-0.11.1"))))
        XCTAssertTrue(new < (try XCTUnwrap(EngineVersion("p1-1.0.0"))))
        XCTAssertTrue(new < (try XCTUnwrap(EngineVersion("p2-0.1.0"))), "a later phase is newer")
        XCTAssertEqual(try XCTUnwrap(EngineVersion("p1-0.11")), new, "a missing number counts as zero")
        XCTAssertEqual(try XCTUnwrap(EngineVersion(" p1-0.11.0-beta\n")), new, "letters after a number are ignored")
        XCTAssertEqual(try XCTUnwrap(EngineVersion("0.11.0")).phase, 0)
    }

    func testRefusesWhatIsNotAVersion() {
        XCTAssertNil(EngineVersion(""))
        XCTAssertNil(EngineVersion("moteur"))
        XCTAssertNil(EngineVersion("p1-"))
        XCTAssertNil(EngineVersion("px-0.11.0"))
        XCTAssertNil(EngineVersion("p1-0..1"))
    }

    func testWhichCalculatorsKeepAQueue() {
        XCTAssertFalse(EngineVersion.hasQueue("p1-0.10.0"))
        XCTAssertFalse(EngineVersion.hasQueue("p1-0.9.0"))
        XCTAssertTrue(EngineVersion.hasQueue("p1-0.11.0"))
        XCTAssertTrue(EngineVersion.hasQueue("p1-0.12.3"))
        XCTAssertTrue(EngineVersion.hasQueue("p2-0.1.0"))
        XCTAssertFalse(EngineVersion.hasQueue("?"), "a text that cannot be read counts as an older calculator")
    }

    /// An older calculator stops the dish it is finishing when a scan is created: the app must not create one then.
    func testProtectionAgainstAnOlderCalculator() {
        // Nothing to ask when the calculator works on no scan, or when its process is gone.
        XCTAssertFalse(OlderCalculator.mustLookAtActiveSession(engine: "p1-0.10.0", activeSession: nil, workerAlive: false))
        XCTAssertFalse(OlderCalculator.mustLookAtActiveSession(engine: "p1-0.10.0", activeSession: "a", workerAlive: false))
        XCTAssertFalse(OlderCalculator.mustLookAtActiveSession(engine: "p1-0.10.0", activeSession: "a", workerAlive: nil))
        XCTAssertTrue(OlderCalculator.mustLookAtActiveSession(engine: "p1-0.10.0", activeSession: "a", workerAlive: true))
        // A calculator with a queue is never asked: it protects the dish itself.
        XCTAssertFalse(OlderCalculator.mustLookAtActiveSession(engine: "p1-0.11.0", activeSession: "a", workerAlive: true))

        XCTAssertTrue(OlderCalculator.newScanWouldStopACalculation(engine: "p1-0.10.0", activeState: "finishing", activeReady: false))
        XCTAssertFalse(OlderCalculator.newScanWouldStopACalculation(engine: "p1-0.10.0", activeState: "capturing", activeReady: false))
        XCTAssertFalse(OlderCalculator.newScanWouldStopACalculation(engine: "p1-0.10.0", activeState: "done", activeReady: true))
        XCTAssertFalse(OlderCalculator.newScanWouldStopACalculation(engine: "p1-0.11.0", activeState: "finishing", activeReady: false))
    }
}

final class CalculatorAnswerTests: XCTestCase {
    private func status(_ json: String) throws -> SessionStatus {
        try SessionStatus.decode(Data(json.utf8))
    }

    /// The answer of engine p1-0.10.0: none of the newer fields.
    func testSessionStatusOfAnOlderCalculator() throws {
        let s = try status(#"""
        {"id":"20261120-201500-a1b2c3","created_at":1.5,"state":"finishing","box":{"revision":0},"device":{},"settings":{},
         "reference_width_m":null,"frames":{"integrated":40},"active":true,"last_geometry":null,"ready":false,
         "progress":{"step":"depth","done":12,"total":40},"busy_with_other":false}
        """#)
        XCTAssertEqual(s.state, "finishing")
        XCTAssertTrue(s.active)
        XCTAssertFalse(s.ready)
        XCTAssertFalse(s.busyWithOther)
        XCTAssertEqual(s.step, "depth")
        XCTAssertEqual(s.done, 12)
        XCTAssertEqual(s.total, 40)
        XCTAssertNil(s.queued, "an older calculator says nothing about a queue")
        XCTAssertNil(s.queuePosition)
        XCTAssertFalse(s.waiting)
        XCTAssertFalse(s.failed)
        XCTAssertNil(s.error)
        XCTAssertNil(s.outcome)
    }

    func testSessionStatusWithTheQueueFields() throws {
        let queued = try status(#"{"state":"capturing","active":false,"ready":false,"busy_with_other":true,"progress":null,"queued":true,"queue_position":2,"waiting":false,"failed":false,"error":null,"verdict":null,"fallbacks":[]}"#)
        XCTAssertEqual(queued.queued, true)
        XCTAssertEqual(queued.queuePosition, 2)
        XCTAssertNil(queued.step)
        XCTAssertNil(queued.outcome)

        let waiting = try status(#"{"state":"capturing","active":false,"ready":false,"queued":false,"queue_position":null,"waiting":true}"#)
        XCTAssertEqual(waiting.queued, false)
        XCTAssertNil(waiting.queuePosition)
        XCTAssertTrue(waiting.waiting)

        let failed = try status(#"{"state":"failed","active":false,"ready":false,"queued":false,"failed":true,"error":" Le modèle n’a pas pu être construit. "}"#)
        XCTAssertTrue(failed.failed)
        XCTAssertEqual(failed.error, "Le modèle n’a pas pu être construit.")

        let ready = try status(#"""
        {"state":"done","active":false,"ready":true,"queued":false,"failed":false,
         "verdict":{"level":"fair","score":71,"issues":["holes","few_views"],"top_coverage":0.8},
         "fallbacks":[{"code":"texture_failed","message":"Les photos n’ont pas pu être appliquées : le modèle garde des couleurs simples."}]}
        """#)
        XCTAssertTrue(ready.ready)
        XCTAssertEqual(ready.outcome?.verdict, ScanVerdict(level: "fair", score: 71, issues: ["holes", "few_views"]))
        XCTAssertEqual(ready.outcome?.fallbacks.count, 1)
        XCTAssertEqual(ready.outcome?.fallbacks.first?.code, "texture_failed")
    }

    /// One field of an unexpected kind must not hide the rest of the answer.
    func testSessionStatusSurvivesOddValues() throws {
        let s = try status(#"{"state":7,"active":"yes","ready":true,"progress":{"step":"depth","done":12.0,"total":"40"},"queued":1,"queue_position":3.0,"error":"","verdict":"good","fallbacks":{"a":1}}"#)
        XCTAssertEqual(s.state, "")
        XCTAssertFalse(s.active)
        XCTAssertTrue(s.ready)
        XCTAssertEqual(s.done, 12)
        XCTAssertNil(s.total)
        XCTAssertNil(s.queued)
        XCTAssertEqual(s.queuePosition, 3)
        XCTAssertNil(s.error, "an empty sentence is no sentence")
        XCTAssertNil(s.outcome)
        XCTAssertThrowsError(try status("[1, 2]"), "only something that is not an object is refused")
    }

    func testAnswersToRequests() throws {
        // POST /sessions
        XCTAssertEqual(SessionCreated.decode(Data(#"{"session_id":"s1","events":"/sessions/s1/events","lidar_used":false}"#.utf8)),
                       SessionCreated(id: "s1", waiting: false))
        XCTAssertEqual(SessionCreated.decode(Data(#"{"session_id":"s2","waiting":true}"#.utf8)), SessionCreated(id: "s2", waiting: true))
        XCTAssertNil(SessionCreated.decode(Data(#"{"detail":"refused"}"#.utf8)))
        XCTAssertNil(SessionCreated.decode(Data(#"{"session_id":""}"#.utf8)))
        // POST /sessions/{id}/finish
        XCTAssertEqual(FinishAnswer.decode(Data(#"{"ok":true,"note":"finishing runs in the worker; follow events"}"#.utf8)), FinishAnswer(queued: false, position: nil))
        XCTAssertEqual(FinishAnswer.decode(Data(#"{"ok":true,"queued":true,"position":2}"#.utf8)), FinishAnswer(queued: true, position: 2))
        XCTAssertEqual(FinishAnswer.decode(Data("pas du JSON".utf8)), FinishAnswer())
        // POST /sessions/{id}/resume_worker
        XCTAssertFalse(WorkerAnswer.decode(Data(#"{"ok":true,"note":"already active"}"#.utf8)).waiting)
        XCTAssertTrue(WorkerAnswer.decode(Data(#"{"ok":true,"waiting":true}"#.utf8)).waiting)
        // PUT a view
        XCTAssertEqual(FrameAnswer.decode(Data(#"{"frame_id":3,"duplicate":false,"status":"received","queued":false}"#.utf8)).queued, false)
        XCTAssertEqual(FrameAnswer.decode(Data(#"{"frame_id":3,"duplicate":false,"status":"received","queued":true}"#.utf8)).queued, true)
        XCTAssertNil(FrameAnswer.decode(Data(#"{"frame_id":3,"duplicate":true,"status":"integrated"}"#.utf8)).queued)
    }

    func testFinalOutcomeIsKeptAndReadBack() throws {
        let outcome = FinalOutcome(verdict: ScanVerdict(level: "good", score: 88, issues: []),
                                   fallbacks: [Fallback(code: "table_kept", message: "La table n’a pas pu être retirée autour du plat.")])
        XCTAssertEqual(FinalOutcome.read(try outcome.jsonData()), outcome)
        // The calculator's own report has many other fields around these two.
        let report = Data(#"{"mesh":{"triangles":9000},"texture":{"status":"ok"},"verdict":{"level":"poor","score":31.0,"issues":["sides_missing"]},"fallbacks":[]}"#.utf8)
        XCTAssertEqual(FinalOutcome.read(report), FinalOutcome(verdict: ScanVerdict(level: "poor", score: 31, issues: ["sides_missing"])))
        XCTAssertNil(FinalOutcome.read(Data(#"{"mesh":{"triangles":9000}}"#.utf8)), "a report without verdict nor fallback gives nothing to show")
        XCTAssertNil(FinalOutcome.read(Data("[]".utf8)))
        // A fallback without a sentence has nothing to say to the person.
        XCTAssertNil(FinalOutcome.read(Data(#"{"fallbacks":[{"code":"x","message":"  "}]}"#.utf8)))
    }
}

final class ServerEventTests: XCTestCase {
    func testEventsOfAnotherScanAreNotOurs() throws {
        let mine = try XCTUnwrap(ServerEvent.decode(#"{"type":"artifacts","session_id":"plat-2","files":["model.glb"]}"#))
        let other = try XCTUnwrap(ServerEvent.decode(#"{"type":"artifacts","session_id":"plat-1","files":["model.glb"]}"#))
        let unnamed = try XCTUnwrap(ServerEvent.decode(#"{"type":"pong","server_time":12.5}"#))
        XCTAssertTrue(mine.isAbout("plat-2"))
        XCTAssertFalse(other.isAbout("plat-2"), "the previous dish finishing must not end the current scan")
        XCTAssertFalse(mine.isAbout(nil), "before the scan exists on the calculator, no event can be about it")
        XCTAssertFalse(mine.isAbout(""))
        XCTAssertTrue(unnamed.isAbout("plat-2"), "an event that names no scan came through this scan's own connection")
        XCTAssertFalse(unnamed.isAbout(nil))
    }

    func testFailureAndFinalReport() throws {
        let failed = try XCTUnwrap(ServerEvent.decode(#"{"type":"status","session_id":"s","state":"failed","error":"Le modèle n’a pas pu être construit."}"#))
        XCTAssertEqual(failed.state, "failed")
        XCTAssertEqual(failed.error, "Le modèle n’a pas pu être construit.")

        let done = try XCTUnwrap(ServerEvent.decode(#"""
        {"type":"artifacts","session_id":"s","files":["model.glb","report.json"],
         "report":{"mesh":{"triangles":9000},"timings_s":{"total":61.2},"verdict":{"level":"fair","score":70,"issues":["holes"]},
                   "fallbacks":[{"code":"texture_failed","message":"Les photos n’ont pas pu être appliquées."}]}}
        """#))
        XCTAssertEqual(done.files, ["model.glb", "report.json"])
        XCTAssertEqual(done.report?.verdict?.level, "fair")
        XCTAssertEqual(done.report?.fallbacks.first?.message, "Les photos n’ont pas pu être appliquées.")

        // The report of engine p1-0.10.0 has neither: nothing to show, and the event is still read.
        let older = try XCTUnwrap(ServerEvent.decode(#"{"type":"artifacts","session_id":"s","files":["model.glb"],"report":{"mesh":{},"texture":{},"scale_check":null}}"#))
        XCTAssertNil(older.report)
        XCTAssertEqual(older.files, ["model.glb"])
    }

    /// The end of a calculation must not be missed because one side field changed its kind.
    func testAnOddFieldDoesNotHideAnEvent() throws {
        let e = try XCTUnwrap(ServerEvent.decode(#"{"type":"artifacts","session_id":"s","files":["model.glb"],"queue":{"length":2},"report":"none","done":"3"}"#))
        XCTAssertEqual(e.files, ["model.glb"])
        XCTAssertNil(e.queue)
        XCTAssertNil(e.done)
        XCTAssertNil(e.report)
        XCTAssertNil(ServerEvent.decode(#"{"session_id":"s"}"#), "an event without a type is no event")
    }
}

final class DishStandingTests: XCTestCase {
    private func standing(_ status: SessionStatus, pending: Int = 0) -> DishStanding {
        DishStanding(status, pendingViews: pending)
    }

    func testWithACalculatorThatKeepsAQueue() {
        let second = standing(SessionStatus(state: "capturing", busyWithOther: true, queued: true, queuePosition: 2))
        XCTAssertEqual(second, .queued(position: 2))
        XCTAssertEqual(second.text, "En attente, 2e dans la file")
        XCTAssertNil(second.action, "a queued dish starts by itself: no button")
        XCTAssertEqual(standing(SessionStatus(queued: true, queuePosition: 1)).text, "En attente, 1er dans la file")
        XCTAssertEqual(standing(SessionStatus(queued: true)).text, "En attente : un autre plat est en cours de calcul")

        let failed = standing(SessionStatus(state: "failed", queued: false, failed: true, error: "Le modèle n’a pas pu être construit."))
        XCTAssertEqual(failed, .failed(message: "Le modèle n’a pas pu être construit."))
        XCTAssertEqual(failed.text, "Le modèle n’a pas pu être construit.", "the calculator's own sentence")
        XCTAssertEqual(failed.action, .restart)
        XCTAssertEqual(standing(SessionStatus(state: "failed", queued: false)).text, "Le calcul du modèle n’a pas abouti.")

        // Asked again after a failure: what is happening now is what counts.
        XCTAssertEqual(standing(SessionStatus(state: "failed", queued: true, queuePosition: 1, failed: true)), .queued(position: 1))
        XCTAssertEqual(standing(SessionStatus(state: "finishing", active: true, queued: false, failed: true)), .computingUncounted)

        // Another dish is being finished, this one was never asked: it can be, the request will wait its turn.
        let notAsked = standing(SessionStatus(state: "capturing", busyWithOther: true, queued: false, waiting: true), pending: 3)
        XCTAssertEqual(notAsked, .viewsToSend(3))
        XCTAssertEqual(notAsked.action, .finish)
    }

    func testWithAnOlderCalculator() {
        let counted = standing(SessionStatus(state: "finishing", active: true, step: "depth", done: 12, total: 40))
        XCTAssertEqual(counted, .computing(step: "depth", done: 12, total: 40))
        XCTAssertEqual(counted.text, "Étape 1 sur 4 : mesure des reliefs", "the count is the progress bar, not figures")
        XCTAssertEqual(counted.fraction ?? 0, 0.3, accuracy: 1e-9)
        XCTAssertNil(counted.action)
        XCTAssertEqual(standing(SessionStatus(state: "finishing", active: true, step: "poses", done: 3, total: 9)).text,
                       "Étape 2 sur 4 : alignement des vues")

        let uncounted = standing(SessionStatus(state: "finishing", active: true))
        XCTAssertEqual(uncounted, .computingUncounted)
        XCTAssertNil(uncounted.fraction)

        // No queue there: the dish is not started by itself, and asking now would be refused.
        let behind = standing(SessionStatus(state: "paused", busyWithOther: true), pending: 2)
        XCTAssertEqual(behind, .waitingForOther)
        XCTAssertNil(behind.action)

        let toSend = standing(SessionStatus(state: "paused"), pending: 5)
        XCTAssertEqual(toSend.text, "5 vues à envoyer")
        XCTAssertEqual(toSend.action, .finish)
        XCTAssertEqual(standing(SessionStatus(state: "paused"), pending: 1).text, "1 vue à envoyer")

        // The calculation died (the calculator was restarted): the state still says "finishing", nothing runs.
        let stopped = standing(SessionStatus(state: "finishing", active: false))
        XCTAssertEqual(stopped, .stopped)
        XCTAssertEqual(stopped.action, .finish)

        XCTAssertEqual(standing(SessionStatus(state: "done", ready: true)), .ready)
    }
}

/// The words the app uses for the final calculation and for the check of the model's size.
final class WordingTests: XCTestCase {
    /// The calculator names its steps after its methods; the app says what happens to the dish.
    func testStepsOfTheFinalCalculation() {
        XCTAssertEqual(FinishWording.step("depth"), "Étape 1 sur 4 : mesure des reliefs")
        XCTAssertEqual(FinishWording.step("poses"), "Étape 2 sur 4 : alignement des vues")
        XCTAssertEqual(FinishWording.step("mesh"), "Étape 3 sur 4 : construction de la surface")
        XCTAssertEqual(FinishWording.step("texture"), "Étape 4 sur 4 : pose des couleurs")
        XCTAssertEqual(FinishWording.step("neural"), "Étape supplémentaire : rendu fin")
        XCTAssertEqual(FinishWording.step("a_new_step"), "Calcul du modèle", "a step the app does not know")
        XCTAssertEqual(FinishWording.step(nil), "Calcul du modèle")
    }

    func testTimeLeft() {
        XCTAssertEqual(FinishWording.remaining(seconds: 10), "moins d’une minute")
        XCTAssertEqual(FinishWording.remaining(seconds: 49), "moins d’une minute")
        XCTAssertEqual(FinishWording.remaining(seconds: 61), "encore 2 min environ")
        XCTAssertEqual(FinishWording.remaining(seconds: 240), "encore 4 min environ")
        XCTAssertEqual(FinishWording.remaining(seconds: .infinity), "moins d’une minute", "no estimate is no promise")
    }

    /// The width typed in Réglages is only a check: the report says what the model measures.
    func testTheCheckOfTheRealWidth() throws {
        let report = Data(#"{"mesh":{"triangles":9000},"scale_check":{"reference_width_m":0.24,"measured_width_m":0.2431,"error_pct":1.29}}"#.utf8)
        let check = try XCTUnwrap(ScaleCheck.read(report))
        XCTAssertEqual(check.referenceWidthM, 0.24, accuracy: 1e-9)
        XCTAssertEqual(check.text, "24,3 cm pour 24 cm saisis")
        XCTAssertEqual(check.matches, true)

        let far = try XCTUnwrap(ScaleCheck.read(Data(#"{"scale_check":{"reference_width_m":0.3,"measured_width_m":0.255}}"#.utf8)))
        XCTAssertEqual(far.text, "25,5 cm pour 30 cm saisis")
        XCTAssertEqual(far.matches, false)

        let unmeasured = try XCTUnwrap(ScaleCheck.read(Data(#"{"scale_check":{"reference_width_m":0.185,"measured_width_m":null,"error_pct":null}}"#.utf8)))
        XCTAssertEqual(unmeasured.text, "non mesurée (18,5 cm saisis)")
        XCTAssertNil(unmeasured.matches)

        // No width typed for this dish (the usual case), an older report, or something that is not a report.
        XCTAssertNil(ScaleCheck.read(Data(#"{"mesh":{},"scale_check":null}"#.utf8)))
        XCTAssertNil(ScaleCheck.read(Data(#"{"mesh":{}}"#.utf8)))
        XCTAssertNil(ScaleCheck.read(Data(#"{"scale_check":{"reference_width_m":"0.24"}}"#.utf8)))
        XCTAssertNil(ScaleCheck.read(Data(#"{"scale_check":{"reference_width_m":0}}"#.utf8)))
        XCTAssertNil(ScaleCheck.read(Data("pas du JSON".utf8)))
    }
}

/// The scan screen runs loops (send the views, ask the calculator if it is there) for as long as it lives.
/// Written as below, a loop holds its owner only while one step runs, never while it waits: the owner can go
/// away. This is the shape used by `ScanController`; the test keeps that property true for the shape.
final class LoopLifetimeTests: XCTestCase {
    @MainActor
    final class Owner {
        private(set) var steps = 0
        private var tasks: [Task<Void, Never>] = []

        func startLoops() {
            let periods: [UInt64] = [20_000_000, 30_000_000]
            for period in periods {
                tasks.append(Task { [weak self] in
                    while !Task.isCancelled, self != nil {
                        await self?.step()
                        try? await Task.sleep(nanoseconds: period)
                    }
                })
            }
        }

        private func step() async {
            steps += 1
            await Task.yield()
        }
    }

    @MainActor
    func testLoopsLetTheirOwnerGo() async throws {
        var owner: Owner? = Owner()
        weak var watched = owner
        owner?.startLoops()
        try await Task.sleep(nanoseconds: 150_000_000)
        XCTAssertGreaterThan(owner?.steps ?? 0, 1, "both loops ran")
        owner = nil
        // Up to two seconds for the loops to notice; they need a few hundredths.
        for _ in 0..<80 where watched != nil {
            try await Task.sleep(nanoseconds: 25_000_000)
        }
        XCTAssertNil(watched, "two running loops must not keep their owner alive")
    }
}
