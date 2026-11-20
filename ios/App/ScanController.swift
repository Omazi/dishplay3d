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
    private var uploadTask: Task<Void, Never>?
    private var finishWatch: Task<Void, Never>?
    private var newestRequestedVersion = 0
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
        scheduler.onSaved = { [weak self] _ in self?.savedFrames += 1 }
        scheduler.onError = { [weak self] e in self?.errorText = e }
        transport.onEvent = { [weak self] ev in Task { @MainActor in self?.handle(ev) } }
        transport.onSocketState = { [weak self] up in Task { @MainActor in self?.calculatorOnline = up } }
        ar.start(useLidar: useLidar)
        startReachabilityLoop()
    }

    /// Before a session exists there is no event socket: ping the calculator so the status chip is truthful.
    private func startReachabilityLoop() {
        Task { [weak self] in
            while let self, !Task.isCancelled {
                if self.serverSessionID == nil {
                    let ok = (try? await self.transport.health()) != nil
                    if self.serverSessionID == nil { self.calculatorOnline = ok }
                }
                try? await Task.sleep(nanoseconds: 3_000_000_000)
            }
        }
    }

    var lidarActive: Bool { ar.lidarActive }

    // MARK: actions

    func start() {
        guard box.placed else { return }
        let localID = ISO8601DateFormatter().string(from: Date()).replacingOccurrences(of: ":", with: "-")
        do { store = try SessionStore(localID: localID) } catch { errorText = error.localizedDescription; return }
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
        BoxSpec(worldFromObject: frozenBox ?? box.worldFromObject,
                size: .init(width: Double(box.width), height: Double(box.height), depth: Double(box.depth)),
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
        let spec = boxSpec()
        if let sid = serverSessionID { Task { try? await transport.postBox(sessionID: sid, box: spec) } }
        if phase == .needsNewBox {
            scheduler.reset()
            scheduler.epoch = ar.epoch
            phase = .paused
        }
    }

    /// Leave "sending the last views" (e.g. the computer is unreachable) and go back to pause.
    func cancelFinish() {
        if phase == .uploadingRest { phase = .paused; preview.followPhone = true }
    }

    func finish() {
        scheduler.active = false
        ar.setScanExposure(locked: false)
        preview.followPhone = false
        phase = .uploadingRest
        Task {
            // Wait for views still being encoded, then for every stored view to reach the calculator.
            while scheduler.status.inFlight > 0 || (store?.pendingCount ?? 0) > 0 || serverSessionID == nil {
                try? await Task.sleep(nanoseconds: 500_000_000)
                if phase != .uploadingRest { return }
            }
            guard let sid = serverSessionID else { return }
            do {
                var body: [String: Any] = [:]
                if let referenceWidth { body["reference_width_m"] = referenceWidth }
                try await transport.post("sessions/\(sid)/finish", json: body)
                store?.markFinishRequested()
                phase = .finishing
                finishText = "Finition lancée sur le calculateur…"
                watchFinishing(sessionID: sid)
            } catch {
                errorText = AppModel.explain(error)
                phase = .paused
            }
        }
    }

    /// The user leaves the scanner on purpose before finishing: do not offer to resume this session.
    func abandonIfUnfinished() {
        if phase != .finishing && phase != .done { store?.markAbandoned() }
    }

    func exportZip() -> URL? {
        do { return try store?.exportZip() } catch { errorText = error.localizedDescription; return nil }
    }

    // MARK: frames

    private func onFrame(_ frame: ARFrame) {
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
            while !Task.isCancelled {
                guard let self else { return }
                await self.uploadStep()
                try? await Task.sleep(nanoseconds: 150_000_000)
            }
        }
    }

    private func uploadStep() async {
        guard let store else { return }
        if serverSessionID == nil {
            let device = DeviceInfo(model: UIDevice.current.model, os: UIDevice.current.systemVersion,
                                    appVersion: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "?",
                                    lidarAvailable: ARSessionController.lidarSupported, lidarEnabled: ar.lidarActive)
            let body = SessionCreate(clientSessionID: store.localID, box: boxSpec(),
                                     device: device, referenceWidth: referenceWidth)
            do {
                let sid = try await transport.createSession(body)
                serverSessionID = sid
                store.setServerSession(sid)
                transport.connectEvents(sessionID: sid)
                calculatorOnline = true
            } catch {
                calculatorOnline = false
                errorText = AppModel.explain(error)
                try? await Task.sleep(nanoseconds: 2_000_000_000)
            }
            return
        }
        guard let sid = serverSessionID, let fid = store.nextPending() else { return }
        do {
            let env = try store.envelope(frameID: fid, serverSessionID: sid)
            try await transport.putFrame(sessionID: sid, frameID: fid, envelope: env)
            store.markSent(fid)
            sentFrames = store.sentCount
            calculatorOnline = true
            if errorText != nil { errorText = nil }
        } catch {
            calculatorOnline = false  // originals stay on disk; retried
            errorText = AppModel.explain(error)
            try? await Task.sleep(nanoseconds: 1_500_000_000)
        }
    }

    private func handle(_ ev: ServerEvent) {
        switch ev.type {
        case "geometry":
            guard let url = ev.url, let h = ev.header else { return }
            if h.version <= newestRequestedVersion { return }  // stale: newer already requested
            newestRequestedVersion = h.version
            Task {
                do {
                    let data = try await transport.download(url)
                    let g = try PreviewGeometry.decode(data)
                    if g.header.version < (lastGeometry?.version ?? 0) { return }
                    preview.show(g)
                    lastGeometry = g.header
                    lastGeometryReceivedAt = Date()
                    if errorText?.hasPrefix("Aperçu") == true { errorText = nil }
                    if g.header.kind == "final", let store, let u = try? store.saveArtifact(name: "final_preview.dpg", data: data) {
                        if !resultFiles.contains(u) { resultFiles.append(u) }
                    }
                } catch { errorText = "Aperçu non reçu : \(error.localizedDescription)" }
            }
        case "frame":
            if let s = ev.status { serverFrames[s, default: 0] += 1 }
        case "finish_progress":
            guard phase != .done else { break }   // late progress of an optional step must not replace "ready"
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
            finished(files: ev.files ?? [])
        case "error":
            let detail = String((ev.message ?? ev.code ?? "erreur").prefix(140))
            errorText = phase == .finishing
                ? "Le calcul a rencontré un problème sur le calculateur. Vous pourrez le relancer depuis Mes plats. (Détail : \(detail))"
                : "Le calculateur signale un problème. (Détail : \(detail))"
        default: break
        }
    }

    /// The model is ready: show it and fetch its files. Called once, by the event or by the watch below.
    private func finished(files: [String]) {
        guard phase != .done else { return }
        finishWatch?.cancel()
        phase = .done
        finishFraction = nil
        Haptics.success()
        preview.followPhone = false
        finishText = "Modèle final prêt."
        Task { await downloadResults(files) }
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
                guard let self, self.phase == .finishing else { return }
                guard let info = try? await self.transport.sessionInfo(sessionID: sid) else { continue }
                if info.ready {
                    let files = (try? await self.transport.artifacts(sessionID: sid)) ?? []
                    if self.phase == .finishing { self.finished(files: files) }
                    return
                }
                idle = (info.active || info.busyWithOther) ? 0 : idle + 1
                if idle >= 3 {
                    self.errorText = "Le calcul s’est arrêté sur le calculateur. Vous pourrez le relancer depuis Mes plats."
                    return
                }
            }
        }
    }

    private func downloadResults(_ files: [String]) async {
        guard let sid = serverSessionID, let store else { return }
        for name in files where ["final_preview.dpg", "model.glb", "plat_seul.glb", "apercu.png", "report.json", "points.ply", "mesh.ply", "manifest.json"].contains(name) {
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
