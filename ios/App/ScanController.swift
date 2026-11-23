import ARKit
import Foundation
import ScanCore
import UIKit
import simd

/// Scan state machine: place/adjust box -> scanning (live reconstruction on the calculator) ->
/// pause -> finish (explicit finishing only) -> inspection/export.
@MainActor
final class ScanController: ObservableObject {
    enum Phase: Equatable { case placing, scanning, paused, uploadingRest, finishing, done, needsNewBox }

    @Published private(set) var phase: Phase = .placing
    @Published private(set) var serverSessionID: String?
    @Published private(set) var calculatorOnline = false
    @Published private(set) var lastGeometry: GeometryHeader?
    @Published private(set) var lastGeometryReceivedAt: Date?
    @Published private(set) var serverFrames: [String: Int] = [:]
    @Published private(set) var finishText: String?
    @Published private(set) var errorText: String?
    @Published private(set) var savedFrames = 0
    @Published private(set) var sentFrames = 0
    @Published private(set) var resultFiles: [URL] = []
    @Published var status = CaptureScheduler.Status()
    /// 0...1 while the calculator reports a countable finishing step, nil otherwise.
    @Published private(set) var finishFraction: Double?
    /// Every side seen and enough high views: the user may finish.
    @Published private(set) var tourComplete = false
    /// The calculator is finishing another dish. This scan goes on: its views are kept, and the live preview
    /// starts by itself when the calculator is free.
    @Published private(set) var waitingForCalculator = false
    /// The linked calculator is an older one (engine before p1-0.11.0) and it is finishing another dish, which
    /// creating a scan would stop. No scan is created there until that dish is done.
    @Published private(set) var olderCalculatorBusy = false
    /// The final model was asked for and waits behind another dish; it starts by itself.
    @Published private(set) var finishQueued = false
    /// The views being taken cannot be kept on the iPhone (no room left, most often): one sentence for the
    /// person. Shown during the scan too, and not erased by a view that reaches the calculator.
    @Published private(set) var storageProblem: String?
    /// The calculator's verdict on the final model and what its calculation had to give up. nil until the
    /// model is ready, and when the calculator says nothing (engine before p1-0.11.0).
    @Published private(set) var finalOutcome: FinalOutcome?
    private var lastVisitedBins = 0
    private var revisionBackup: BoundingBoxController.Saved?
    /// First progress report of the current finishing step: lets the app estimate the time left.
    private var finishStep: (name: String, since: Date, done: Int)?

    /// " · encore ~4 min", once enough of the step has run for the estimate to mean something.
    private func remainingText(done: Int, total: Int) -> String {
        guard let s = finishStep, done - s.done >= 5, done < total else { return "" }
        let perItem = Date().timeIntervalSince(s.since) / Double(done - s.done)
        let left = perItem * Double(total - done)
        if left < 50 { return " · moins d’une minute" }
        return " · encore ~\(Int((left / 60).rounded(.up))) min"
    }

    let ar = ARSessionController()
    let box = BoundingBoxController()
    let preview = PreviewRenderer()
    let scheduler = CaptureScheduler()
    private(set) var store: SessionStore?
    private let transport: ScanTransport
    private let useLidar: Bool
    private let referenceWidth: Double?
    private var boxRevision = 0
    private var reachabilityTask: Task<Void, Never>?
    private var uploadTask: Task<Void, Never>?
    private var finishTask: Task<Void, Never>?
    private var finishWatch: Task<Void, Never>?
    /// Set by `stop`: the screen was left, nothing of this scan may go on.
    private var stopped = false
    /// A problem shown in `errorText` that must stay until the person acts (a refused box, a failed finish).
    /// The other ones go away as soon as a view reaches the calculator again.
    private var errorIsLasting = false
    /// A changed box the calculator has not confirmed yet: sent before any further view, again and again.
    private var pendingBox: BoxSpec?
    private var storageFailures = 0
    /// Whether the linked calculator keeps a queue of calculations (engine p1-0.11.0 or later).
    private var calculatorHasQueue = false
    private var nextReopen = Date.distantPast
    private var newestRequestedVersion = 0
    private var shownGeometryVersion = 0
    /// Changes each time the previews start counting from 1 again (new scan, or the calculator took the scan
    /// up again after being restarted): a preview still being downloaded from before is then dropped.
    private var geometryRun = 0
    private var lastTrackingUpdate = 0.0
    private var lastPoseUpdate = 0.0
    /// Box pose in the "frozen" world sent to the calculator. Camera poses are expressed relative to the
    /// box ARAnchor, then mapped through this pose, so ARKit map corrections do not shift the model.
    /// Kept in double precision with exact rigid inverses (the calculator rejects non-rigid matrices).
    private var frozenBox: Mat4?
    private var frozenFromLive = Mat4.identity
    /// Where the phone is around the box (object frame), for the coverage ring and the preview camera.
    @Published private(set) var cameraAzimuthDeg = 0.0

    init(transport: ScanTransport, useLidar: Bool, referenceWidthCm: Double?) {
        self.transport = transport
        self.useLidar = useLidar
        referenceWidth = referenceWidthCm.map { $0 / 100 }
        box.attach(to: ar.arView)
        ar.onFrame = { [weak self] frame in self?.onFrame(frame) }
        scheduler.onSaved = { [weak self] _ in self?.viewSaved() }
        scheduler.onError = { [weak self] failure in self?.viewNotSaved(failure) }
        // The app keeps one connection for the calculator's events. Left on the previous dish, it would bring
        // that dish's events to this screen: it is cut here, and opened again once this scan exists there.
        transport.disconnectEvents()
        transport.onEvent = { [weak self] ev in Task { @MainActor in self?.handle(ev) } }
        transport.onSocketState = { [weak self] up in Task { @MainActor in self?.socketChanged(up) } }
        ar.start(useLidar: useLidar)
        #if DEBUG
        if let moment = UITestMode.scanMoment { stage(moment) }
        #endif
        startReachabilityLoop()
    }

    #if DEBUG
    /// Screen check in the iPhone simulator, which has neither camera nor calculator: put the screen at a given
    /// moment of a scan, with the model files of the newest sample dish. Debug builds only.
    private func stage(_ moment: String) {
        serverSessionID = "screen-check"   // also keeps the reachability loop from saying the calculator is away
        calculatorOnline = true
        ar.stage(cameraDenied: moment == "denied")
        if moment == "denied" { return }   // nothing was placed: the camera never started
        box.stage(locked: moment != "box")
        let results = DishLibrary.all().first { $0.geometry != nil }?.root.appending(path: "results")
        func show(_ file: String) {
            guard let url = results?.appending(path: file), let data = try? Data(contentsOf: url),
                  let geometry = try? PreviewGeometry.decode(data) else { return }
            preview.show(geometry)
            lastGeometry = geometry.header
            lastGeometryReceivedAt = .now
        }
        switch moment {
        case "scanning", "paused":
            // Seven of the twelve sides seen so far, from a low angle.
            for side in 0..<7 {
                let angle = (Double(side) + 0.5) * .pi / 6
                scheduler.ring.add(cameraInObject: [cos(angle), 0.2, sin(angle)], boxHeight: Double(box.height))
            }
            cameraAzimuthDeg = 180
            savedFrames = 34
            show("live_preview.dpg")
            phase = moment == "paused" ? .paused : .scanning
        case "finishing":
            savedFrames = 60
            show("live_preview.dpg")
            preview.followPhone = false
            finishText = "Calcul fin des profondeurs : 12/40 · encore ~2 min"
            finishFraction = 0.3
            phase = .finishing
        case "done":
            savedFrames = 60
            show("final_preview.dpg")
            preview.followPhone = false
            phase = .done
        default:
            break   // "box": the box has just been placed, the scan has not started
        }
    }
    #endif

    /// Before a scan exists on the calculator there is no event connection: the calculator is asked regularly,
    /// so that the status chip is truthful and the scan only starts when it may (`olderCalculatorIsFinishing`).
    private func startReachabilityLoop() {
        reachabilityTask?.cancel()
        reachabilityTask = Task { [weak self] in
            // The loop holds the controller only while one step runs, never while it waits: with `[weak self]`
            // alone and a `guard let self` around the wait, this loop and the upload loop kept the controller
            // (and its camera) alive for ever, each holding it while the other one let go.
            while !Task.isCancelled, self != nil {
                await self?.reachabilityStep()
                try? await Task.sleep(nanoseconds: 3_000_000_000)
            }
        }
    }

    private func reachabilityStep() async {
        guard !stopped, serverSessionID == nil else { return }
        let busy = try? await olderCalculatorIsFinishing()
        guard !stopped, serverSessionID == nil else { return }
        calculatorOnline = busy != nil
        if let busy { olderCalculatorBusy = busy }
    }

    /// Asks the calculator. True: it is an older one, without a queue, and it is finishing another dish. Such a
    /// calculator stops that calculation as soon as a scan is created, so the app must not create one now.
    /// Throws when the calculator does not answer.
    private func olderCalculatorIsFinishing() async throws -> Bool {
        let (health, _) = try await transport.health()
        calculatorHasQueue = EngineVersion.hasQueue(health.engine)
        guard OlderCalculator.mustLookAtActiveSession(engine: health.engine, activeSession: health.active_session,
                                                      workerAlive: health.worker_alive),
              let active = health.active_session else { return false }
        let info = try await transport.sessionInfo(sessionID: active)
        return OlderCalculator.newScanWouldStopACalculation(engine: health.engine, activeState: info.state, activeReady: info.ready)
    }

    private func socketChanged(_ up: Bool) {
        guard !stopped else { return }
        calculatorOnline = up
    }

    var lidarActive: Bool { ar.lidarActive }

    // MARK: problems shown to the person

    /// Show a problem. `lasting`: it stays until the person acts; otherwise it goes away as soon as a view
    /// reaches the calculator again.
    private func say(_ text: String, lasting: Bool = false) {
        errorText = text
        errorIsLasting = lasting
    }

    private func clearError() {
        if errorText != nil { errorText = nil }
        errorIsLasting = false
    }

    private func viewSaved() {
        savedFrames += 1
        storageFailures = 0
        // Capture goes on and views are kept again. In pause the sentence stays: it says why the scan paused.
        if storageProblem != nil, phase == .scanning { storageProblem = nil }
    }

    /// A view could not be kept on the iPhone. It is not counted in the coverage ring (`CaptureScheduler`), and
    /// it is said at once, during the scan too. After three in a row the capture pauses by itself, so that
    /// nobody walks around the dish for nothing.
    private func viewNotSaved(_ failure: CaptureScheduler.Failure) {
        guard !stopped else { return }
        storageFailures += 1
        switch failure {
        case .noSpace:
            storageProblem = "L’iPhone n’a plus de place : les nouvelles vues ne sont pas gardées. Libérez de la place, puis reprenez le scan."
        case .storage, .encoding:
            storageProblem = "Les nouvelles vues ne peuvent pas être gardées sur l’iPhone. Reprenez le scan ; si cela continue, fermez l’app et rouvrez-la."
        }
        if storageFailures >= 3, phase == .scanning {
            Haptics.warning()
            pause()
        }
    }

    // MARK: actions

    func start() {
        guard box.placed, !stopped, !olderCalculatorBusy else { return }
        let localID = ISO8601DateFormatter().string(from: Date()).replacingOccurrences(of: ":", with: "-")
        do { store = try SessionStore(localID: localID) } catch { say(error.localizedDescription); return }
        // Nothing left from before may be taken for this scan: previews count from 1 again.
        restartGeometryCount()
        lastGeometry = nil
        lastGeometryReceivedAt = nil
        serverFrames = [:]
        resultFiles = []
        finalOutcome = nil
        finishText = nil
        finishFraction = nil
        finishStep = nil
        finishQueued = false
        pendingBox = nil
        waitingForCalculator = false
        storageProblem = nil
        storageFailures = 0
        clearError()
        frozenFromLive = .identity
        lockBox()
        scheduler.reset()
        scheduler.epoch = ar.epoch
        scheduler.active = true
        ar.setScanExposure(locked: true)
        phase = .scanning
        lastVisitedBins = 0
        tourComplete = false
        Haptics.tap(.heavy)
        store?.writeSessionInfo(["local_id": localID, "box": (try? JSONSerialization.jsonObject(with: JSONEncoder().encode(boxSpec()))) ?? [:],
                                 "lidar": useLidar, "reference_width_m": referenceWidth as Any])
        startUploadLoop()
    }

    /// Freeze the box: its pose becomes the reference frame of the reconstruction and an ARAnchor is dropped on it.
    private func lockBox() {
        let live = box.worldTransform
        frozenBox = frozenFromLive * Mat4(live)
        ar.setBoxAnchor(live)
        box.locked = true
        scheduler.lockedWorldFromObject = frozenBox
    }

    private func boxSpec() -> BoxSpec {
        // Sizes travel as Double. The smallest height the box allows, 1 cm, is a hair under 0.01 once converted
        // from Float, and the calculator refuses a height under 0.01: the scan was then never created. The sizes
        // sent are kept inside what the contract accepts (contracts/capture-session.schema.json, box.size_m).
        let size = BoxSpec.Size(width: min(1.5, max(0.03, Double(box.width))),
                                height: min(1.0, max(0.01, Double(box.height))),
                                depth: min(1.5, max(0.03, Double(box.depth))))
        return BoxSpec(worldFromObject: frozenBox ?? box.worldFromObject, size: size,
                       epoch: ar.epoch, revision: boxRevision, plane: box.planeSource)
    }

    /// Camera pose in the frozen world: (frozen box) * inverse(box anchor now) * (camera now).
    private func cameraPose(_ frame: ARFrame) -> Mat4 {
        if let frozenBox, let a = ar.boxAnchorTransform(in: frame) {
            return frozenBox * Mat4(a).rigidInverse * Mat4(frame.camera.transform)
        }
        return Mat4(frame.camera.transform)
    }

    /// Transform from live world coordinates to the box frame (anchor when locked, editable box otherwise).
    private func objectFromLiveWorld(_ frame: ARFrame) -> simd_float4x4 {
        if box.locked, let a = ar.boxAnchorTransform(in: frame) { return a.inverse }
        return box.worldTransform.inverse
    }

    func pause() {
        scheduler.active = false
        ar.setScanExposure(locked: false)
        phase = .paused
        if let sid = serverSessionID { Task { try? await transport.post("sessions/\(sid)/pause") } }
    }

    func resume() {
        guard phase == .paused else { return }
        storageProblem = nil
        storageFailures = 0
        scheduler.active = true
        ar.setScanExposure(locked: true)
        phase = .scanning
        if let sid = serverSessionID { Task { try? await transport.post("sessions/\(sid)/resume") } }
    }

    /// Explicit box revision (only while paused): the calculator rebuilds the volume from stored frames.
    func reviseBox() {
        if let frame = ar.arView.session.currentFrame, let a = ar.boxAnchorTransform(in: frame), let frozenBox {
            frozenFromLive = frozenBox * Mat4(a).rigidInverse   // keeps already captured views consistent with the edited box
            box.adopt(anchorTransform: a)
        }
        ar.setBoxAnchor(nil)
        revisionBackup = box.save()
        box.locked = false
    }

    /// Leave the box edit without changing anything: same box, no recalculation.
    func cancelBoxRevision() {
        guard phase == .paused, !box.locked, let saved = revisionBackup else { return }
        box.restore(saved)
        lockBox()   // frozenFromLive was set by reviseBox, so the frozen box is exactly the previous one
        revisionBackup = nil
    }

    func applyBoxRevision() {
        guard box.placed else { return }
        if phase == .needsNewBox { frozenFromLive = .identity }  // new tracking world: nothing to keep aligned
        boxRevision += 1
        revisionBackup = nil
        lockBox()
        // The upload loop sends the box before any further view, and again until the calculator has it. Sent once
        // with its failure ignored, a lost box left the calculator with the previous one: after a restart of the
        // tracking it then set aside every new view, without a word.
        pendingBox = boxSpec()
        if errorIsLasting { clearError() }
        if phase == .needsNewBox {
            scheduler.reset()
            scheduler.epoch = ar.epoch
            phase = .paused
        }
    }

    /// Leave "sending the last views" (e.g. the computer is unreachable) and go back to pause.
    func cancelFinish() {
        if phase == .uploadingRest { backToPause() }
    }

    private func backToPause() {
        phase = .paused
        preview.followPhone = true
    }

    /// Views still being prepared, or not yet received by the calculator (which may not know this scan yet),
    /// or a changed box it has not confirmed.
    private var hasViewsToSend: Bool {
        scheduler.status.inFlight > 0 || (store?.pendingCount ?? 0) > 0 || serverSessionID == nil || pendingBox != nil
    }

    func finish() {
        guard phase == .scanning || phase == .paused, !stopped else { return }
        scheduler.active = false
        ar.setScanExposure(locked: false)
        preview.followPhone = false
        if errorIsLasting { clearError() }
        phase = .uploadingRest
        finishTask?.cancel()
        finishTask = Task { [weak self] in
            // Wait for views still being encoded, then for every stored view to reach the calculator.
            while self?.hasViewsToSend == true {
                try? await Task.sleep(nanoseconds: 500_000_000)
                guard !Task.isCancelled, let phase = self?.phase, phase == .uploadingRest else { return }
            }
            await self?.requestFinish()
        }
    }

    /// Every view is on the calculator: ask it for the final model.
    private func requestFinish() async {
        guard !stopped, phase == .uploadingRest, let sid = serverSessionID else { return }
        do {
            let answer: FinishAnswer
            do {
                answer = try await transport.finish(sessionID: sid, referenceWidth: referenceWidth)
            } catch let TransportError.http(code, _) where code == 409 {
                // Only a calculator older than the queue answers this: it no longer works on this dish, because
                // it was restarted during the scan. The dish is reopened there, its events are listened to again
                // (that calculator only sends them to a connection opened afterwards), and the model is asked once more.
                _ = try await transport.resumeWorker(sessionID: sid)
                restartGeometryCount()
                transport.connectEvents(sessionID: sid)
                answer = try await transport.finish(sessionID: sid, referenceWidth: referenceWidth)
            }
            store?.markFinishRequested()
            if stopped { return }
            waitingForCalculator = false
            clearError()
            finishFraction = nil
            finishStep = nil
            finishQueued = answer.queued
            finishText = answer.queued ? QueueWording.waiting(answer.position) : "Finition lancée sur le calculateur…"
            phase = .finishing
            watchFinishing(sessionID: sid)
        } catch let TransportError.http(code, _) where code == 409 {
            if Task.isCancelled || stopped { return }
            // An older calculator, finishing another dish (asked from another iPhone, or from Mes plats).
            say("Le calculateur termine un autre plat. Quittez le scan en le gardant : vous le terminerez depuis l’accueil quand le calculateur aura fini.", lasting: true)
            backToPause()
        } catch {
            if Task.isCancelled || stopped { return }
            say(AppModel.explain(error), lasting: true)
            backToPause()
        }
    }

    /// The person gives the scan up before its model was asked for: its views leave the iPhone, as the app says.
    /// A scan whose model is being calculated, or is ready, is kept.
    func abandonIfUnfinished() {
        guard phase != .finishing, phase != .done else { return }
        stop()   // first: nothing may write into the folder any more
        store?.delete()
        store = nil
    }

    /// The scanner screen is left: nothing of this scan goes on behind the other screens. The loops are
    /// cancelled, the camera is paused and the events are disconnected. A calculation already asked for goes on
    /// on the calculator, and the files of a ready model finish arriving. Can be called several times.
    func stop() {
        guard !stopped else { return }
        stopped = true
        reachabilityTask?.cancel()
        uploadTask?.cancel()
        finishTask?.cancel()
        finishWatch?.cancel()
        if scheduler.active {
            scheduler.active = false
            ar.setScanExposure(locked: false)
        }
        ar.onFrame = nil
        ar.pauseCamera()
        transport.onEvent = nil
        transport.onSocketState = nil
        transport.disconnectEvents()
    }

    func exportZip() -> URL? {
        do { return try store?.exportZip() } catch { say(error.localizedDescription, lasting: true); return nil }
    }

    // MARK: frames

    private func onFrame(_ frame: ARFrame) {
        guard !stopped else { return }
        if ar.worldWasReset {
            // New tracking epoch: the old box pose is meaningless in the new world. Never fuse silently.
            ar.acknowledgeReset()
            frozenBox = nil
            scheduler.lockedWorldFromObject = nil
            switch phase {
            case .placing:
                box.reset()
            case .scanning, .paused:
                scheduler.active = false
                ar.setScanExposure(locked: false)
                box.reset()
                phase = .needsNewBox
            default: break
            }
        }
        if box.locked, let a = ar.boxAnchorTransform(in: frame) { box.follow(anchorTransform: a) }
        if let store, phase == .scanning {
            scheduler.consider(frame, worldFromCam: cameraPose(frame), box: box, store: store, lidar: ar.lidarActive,
                               formatText: ar.videoFormatText)
            if status != scheduler.status { status = scheduler.status }
            let bins = scheduler.ring.visitedBins
            if bins != lastVisitedBins {
                lastVisitedBins = bins
                Haptics.tap(.light)   // a new side of the dish is covered
                let done = scheduler.ring.visitedAzimuths == 12 && scheduler.ring.highViews >= 6
                if done && !tourComplete { Haptics.success() }
                tourComplete = done
            }
        }
        guard box.placed else { return }
        let objFromWorld = objectFromLiveWorld(frame)
        updateViewpoint(frame, objFromWorld)
        updateTrackingPoints(frame, objFromWorld)
    }

    /// Phone position around the box: drives the coverage ring and makes the 3D preview show the
    /// model from the same side as the camera.
    private func updateViewpoint(_ frame: ARFrame, _ objFromWorld: simd_float4x4) {
        guard frame.timestamp - lastPoseUpdate > 0.1 else { return }
        lastPoseUpdate = frame.timestamp
        let c = objFromWorld * frame.camera.transform.columns.3
        let d = SIMD3<Float>(c.x, c.y - box.height / 2, c.z)
        guard simd_length(d) > 0.02 else { return }
        preview.follow(direction: simd_normalize(d))
        let az = Double(atan2(d.z, d.x)) * 180 / .pi
        if abs(az - cameraAzimuthDeg) > 2 { cameraAzimuthDeg = az }
    }

    /// ARKit feature points inside the box, shown as "suivi" (unstable, never accumulated).
    private func updateTrackingPoints(_ frame: ARFrame, _ objFromWorld: simd_float4x4) {
        guard frame.timestamp - lastTrackingUpdate > 0.2 else { return }
        lastTrackingUpdate = frame.timestamp
        guard let raw = frame.rawFeaturePoints?.points else { return }
        let w = box.width / 2, d = box.depth / 2, h = box.height
        var pts: [SIMD3<Float>] = []
        for p in raw {
            let o = objFromWorld * SIMD4<Float>(p.x, p.y, p.z, 1)
            if abs(o.x) <= w, abs(o.z) <= d, o.y >= -0.005, o.y <= h { pts.append(SIMD3(o.x, o.y, o.z)) }
        }
        preview.showTracking(pts)
    }

    // MARK: network

    private func startUploadLoop() {
        uploadTask?.cancel()
        uploadTask = Task { [weak self] in
            // Like the reachability loop: the controller is held while a step runs, not while the loop waits.
            while !Task.isCancelled, self != nil {
                await self?.uploadStep()
                try? await Task.sleep(nanoseconds: 150_000_000)
            }
        }
    }

    /// One thing at a time, in this order: create the scan on the calculator, give it a changed box, send a view.
    private func uploadStep() async {
        guard !stopped, let store else { return }
        guard let sid = serverSessionID else {
            await openSession(for: store)
            return
        }
        if let spec = pendingBox {
            await sendBox(spec, sessionID: sid)
            return
        }
        guard let fid = store.nextPending() else { return }
        do {
            let env = try store.envelope(frameID: fid, serverSessionID: sid)
            let answer = try await transport.putFrame(sessionID: sid, frameID: fid, envelope: env)
            store.markSent(fid)
            if stopped { return }
            sentFrames = store.sentCount
            calculatorOnline = true
            if !errorIsLasting { clearError() }
            if answer.queued == true {
                waitingForCalculator = false
            } else if answer.queued == false {
                await takeUpAgain(sessionID: sid)
            }
        } catch {
            if Task.isCancelled || stopped { return }
            calculatorOnline = false  // originals stay on disk; retried
            say(AppModel.explain(error))
            try? await Task.sleep(nanoseconds: 1_500_000_000)
        }
    }

    /// The scan does not exist on the calculator yet: create it there.
    private func openSession(for store: SessionStore) async {
        do {
            // An older calculator stops the dish it is finishing when a scan is created: wait for that dish.
            // The views already taken stay on the iPhone and leave as soon as the scan exists there.
            if try await olderCalculatorIsFinishing() {
                if stopped { return }
                calculatorOnline = true
                olderCalculatorBusy = true
                try? await Task.sleep(nanoseconds: 3_000_000_000)
                return
            }
            olderCalculatorBusy = false
            let device = DeviceInfo(model: UIDevice.current.model, os: UIDevice.current.systemVersion,
                                    appVersion: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "?",
                                    lidarAvailable: ARSessionController.lidarSupported, lidarEnabled: ar.lidarActive)
            let sentBox = boxSpec()
            let body = SessionCreate(clientSessionID: store.localID, box: sentBox,
                                     device: device, referenceWidth: referenceWidth)
            let created = try await transport.createSession(body)
            store.setServerSession(created.id)
            if stopped { return }
            serverSessionID = created.id
            if pendingBox == sentBox { pendingBox = nil }   // the scan was created with this very box
            // `waiting`: the calculator is finishing another dish. It keeps the views sent meanwhile and starts
            // the live preview by itself; the screen says so instead of "unreachable".
            waitingForCalculator = created.waiting
            transport.connectEvents(sessionID: created.id)
            calculatorOnline = true
            if !errorIsLasting { clearError() }
        } catch {
            if Task.isCancelled || stopped { return }
            calculatorOnline = false
            say(AppModel.explain(error))
            try? await Task.sleep(nanoseconds: 2_000_000_000)
        }
    }

    /// Give the calculator a changed box. Tried again at the next step until it is confirmed.
    private func sendBox(_ spec: BoxSpec, sessionID sid: String) async {
        do {
            try await transport.postBox(sessionID: sid, box: spec)
            if stopped { return }
            if pendingBox == spec { pendingBox = nil }   // not when the box was changed again meanwhile
            calculatorOnline = true
            if !errorIsLasting { clearError() }
        } catch let TransportError.http(code, _) where code == 400 || code == 422 {
            if Task.isCancelled || stopped { return }
            // The calculator answers and refuses this very box: sending it again would change nothing, and
            // would hold back every view. Said to the person, who can set the box again.
            if pendingBox == spec { pendingBox = nil }
            say("Le calculateur n’a pas accepté cette boîte. Mettez le scan en pause, touchez « Boîte », ajustez-la et validez de nouveau.", lasting: true)
        } catch {
            if Task.isCancelled || stopped { return }
            calculatorOnline = false
            say(AppModel.explain(error))
            try? await Task.sleep(nanoseconds: 1_500_000_000)
        }
    }

    /// The calculator kept a view but nothing there works on this scan: it was restarted during the scan, or
    /// it is finishing another dish. Looked at every few seconds at most.
    private func takeUpAgain(sessionID sid: String) async {
        guard Date() >= nextReopen else { return }
        nextReopen = Date().addingTimeInterval(5)
        if calculatorHasQueue {
            // This calculator takes the scan up again by itself when it is free; it says whether it is waiting.
            guard let info = try? await transport.sessionInfo(sessionID: sid) else { return }
            if stopped { return }
            waitingForCalculator = info.waiting
            return
        }
        do {
            let answer = try await transport.resumeWorker(sessionID: sid)
            if stopped { return }
            waitingForCalculator = answer.waiting
            if !answer.waiting {
                // A calculation starts again for this scan: its previews count from 1, and an older calculator
                // only sends events to a connection opened after that start. Left alone for a while to start.
                nextReopen = Date().addingTimeInterval(20)
                restartGeometryCount()
                transport.connectEvents(sessionID: sid)
            }
        } catch let TransportError.http(code, _) where code == 409 {
            if stopped { return }
            waitingForCalculator = true   // an older calculator, finishing another dish
        } catch {
            // Not reachable right now: the upload loop says so with its next view.
        }
    }

    private func restartGeometryCount() {
        geometryRun += 1
        newestRequestedVersion = 0
        shownGeometryVersion = 0
    }

    private func handle(_ ev: ServerEvent) {
        // Only the events of this scan. The app scans several dishes one after another with one connection:
        // taken for this one, the end of the previous dish showed "Modèle prêt" before the scan had started.
        guard !stopped, ev.isAbout(serverSessionID) else { return }
        switch ev.type {
        case "geometry":
            guard let url = ev.url, let h = ev.header else { return }
            waitingForCalculator = false
            if h.version == newestRequestedVersion { return }  // sent again after a reconnection
            if h.version < newestRequestedVersion {
                // Within one calculation the versions only go up. A lower one means the calculator started again
                // on this dish (it was restarted during the scan) and counts from 1. Not while the final model is
                // being made or shown: a late live preview must not take its place.
                guard h.kind != "final", phase != .finishing, phase != .done else { return }
                restartGeometryCount()
            }
            newestRequestedVersion = h.version
            let run = geometryRun
            Task {
                do {
                    let data = try await transport.download(url)
                    let g = try PreviewGeometry.decode(data)
                    if stopped || run != geometryRun || g.header.version < shownGeometryVersion { return }
                    shownGeometryVersion = g.header.version
                    preview.show(g)
                    lastGeometry = g.header
                    lastGeometryReceivedAt = Date()
                    if errorText?.hasPrefix("Aperçu") == true { clearError() }
                    if g.header.kind == "final", let store, let u = try? store.saveArtifact(name: "final_preview.dpg", data: data) {
                        if !resultFiles.contains(u) { resultFiles.append(u) }
                    }
                } catch {
                    if stopped || run != geometryRun { return }
                    say("Aperçu non reçu : \(error.localizedDescription)")
                }
            }
        case "frame":
            waitingForCalculator = false
            if let s = ev.status { serverFrames[s, default: 0] += 1 }
        case "status":
            if ev.state == "failed" {
                finishFailed(ev.error)
            } else if ev.state == "capturing" || ev.state == "paused" {
                waitingForCalculator = false
            } else if ev.state == "finishing" {
                waitingForCalculator = false
                if finishQueued {
                    // Its turn has come.
                    finishQueued = false
                    finishText = "Finition lancée sur le calculateur…"
                }
            }
        case "finish_progress":
            guard phase != .done else { break }   // late progress of an optional step must not replace "ready"
            finishQueued = false
            let names = ["poses": "recalage des vues", "depth": "calcul fin des profondeurs", "mesh": "surface", "texture": "texture",
                         "neural": "rendu neuronal"]
            let key = ev.step ?? ""
            let step = names[key] ?? "calcul"
            let label = step.prefix(1).uppercased() + step.dropFirst()
            finishFraction = (ev.total ?? 0) > 1 ? min(1, Double(ev.done ?? 0) / Double(ev.total ?? 1)) : nil
            if let total = ev.total, total > 1 {
                let done = ev.done ?? 0
                if finishStep?.name != key { finishStep = (key, Date(), done) }
                finishText = "\(label) : \(done)/\(total)\(remainingText(done: done, total: total))"
            } else {
                finishStep = nil
                finishText = "\(label)…"
            }
        case "artifacts":
            note(outcome: ev.report)
            finished(files: ev.files ?? [])
        case "error":
            guard phase != .done else { break }   // nor may a late problem of an optional step
            let detail = String((ev.message ?? ev.code ?? "erreur").prefix(140))
            say(phase == .finishing
                ? "Le calcul a rencontré un problème sur le calculateur. Vous pourrez le relancer depuis Mes plats. (Détail : \(detail))"
                : "Le calculateur signale un problème. (Détail : \(detail))")
        default: break
        }
    }

    /// Keep what the calculator says of the final model, on the screen and with the dish.
    private func note(outcome: FinalOutcome?) {
        guard let outcome, !outcome.isEmpty else { return }
        finalOutcome = outcome
        store?.saveOutcome(outcome)
    }

    /// The model is ready: show it and fetch its files. Called once, by the event or by the watch below.
    private func finished(files: [String]) {
        guard phase != .done, !stopped, store != nil else { return }
        finishWatch?.cancel()
        phase = .done
        finishQueued = false
        finishFraction = nil
        clearError()
        Haptics.success()
        preview.followPhone = false
        finishText = "Modèle final prêt."
        Task { await downloadResults(files) }
    }

    /// The calculator could not make the final model. The scan is whole, there and on the iPhone: the screen
    /// goes back to pause, from where "Terminer" asks for the model again.
    private func finishFailed(_ sentence: String?) {
        guard phase == .finishing, !stopped else { return }
        finishWatch?.cancel()
        finishQueued = false
        finishFraction = nil
        finishStep = nil
        finishText = nil
        let said = sentence?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        say((said.isEmpty ? "Le calcul du modèle n’a pas abouti." : said) + " Vous pouvez le relancer avec « Terminer ».", lasting: true)
        Haptics.warning()
        backToPause()
    }

    /// The end of the calculation normally arrives as an event. If the iPhone was locked or the app left at
    /// that moment the event is lost and the screen would say "Finition du modèle" for ever: so the
    /// calculator is also asked directly, every few seconds, where the session stands.
    private func watchFinishing(sessionID sid: String) {
        finishWatch?.cancel()
        finishWatch = Task { [weak self] in
            var idle = 0
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 4_000_000_000)
                guard let self, !self.stopped, self.phase == .finishing else { return }
                guard let info = try? await self.transport.sessionInfo(sessionID: sid) else { continue }
                guard !self.stopped, self.phase == .finishing else { return }
                if info.ready {
                    self.note(outcome: info.outcome)
                    let files = (try? await self.transport.artifacts(sessionID: sid)) ?? []
                    if self.phase == .finishing { self.finished(files: files) }
                    return
                }
                switch DishStanding(info, pendingViews: 0) {
                case .queued(let position):
                    // Behind another dish: it starts by itself, this is not a calculation that stopped.
                    self.finishQueued = true
                    self.finishFraction = nil
                    self.finishText = QueueWording.waiting(position)
                    idle = 0
                case .failed(let message):
                    self.finishFailed(message)
                    return
                default:
                    if self.finishQueued {
                        self.finishQueued = false
                        self.finishText = "Finition lancée sur le calculateur…"
                    }
                    idle = (info.active || info.busyWithOther) ? 0 : idle + 1
                }
                if idle >= 3 {
                    self.say("Le calcul s’est arrêté sur le calculateur. Vous pourrez le relancer depuis Mes plats.", lasting: true)
                    return
                }
            }
        }
    }

    private func downloadResults(_ files: [String]) async {
        guard let sid = serverSessionID, let store else { return }
        // The verdict normally comes with the event that ends the calculation; otherwise the calculator is asked.
        if finalOutcome == nil, let info = try? await transport.sessionInfo(sessionID: sid) { note(outcome: info.outcome) }
        for name in files where ["final_preview.dpg", "model.glb", "model.usdz", "plat_seul.glb", "apercu.png", "report.json", "points.ply", "mesh.ply", "manifest.json"].contains(name) {
            if name == "final_preview.dpg" && lastGeometry?.kind == "final" { continue }   // already received as an event
            guard let d = try? await transport.download("sessions/\(sid)/artifacts/\(name)"), let u = try? store.saveArtifact(name: name, data: d) else { continue }
            if !resultFiles.contains(u) { resultFiles.append(u) }
            // The final model normally arrives as an event; when that event was missed, show it now.
            if name == "final_preview.dpg", let g = try? PreviewGeometry.decode(d) {
                preview.show(g)
                lastGeometry = g.header
                lastGeometryReceivedAt = Date()
            }
        }
    }
}
