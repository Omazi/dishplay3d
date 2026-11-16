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
        box.locked = false
    }

    func applyBoxRevision() {
        guard box.placed else { return }
        if phase == .needsNewBox { frozenFromLive = .identity }  // new tracking world: nothing to keep aligned
        boxRevision += 1
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
                phase = .finishing
                finishText = "Finition lancée sur le calculateur…"
            } catch {
                errorText = AppModel.explain(error)
                phase = .paused
            }
        }
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
            finishText = "Finition : \(ev.step ?? "") \(ev.done ?? 0)/\(ev.total ?? 0)"
        case "artifacts":
            phase = .done
            preview.followPhone = false
            finishText = "Modèle final prêt."
            Task { await downloadResults(ev.files ?? []) }
        case "error":
            errorText = "Calculateur : \(ev.message ?? ev.code ?? "erreur")"
        default: break
        }
    }

    private func downloadResults(_ files: [String]) async {
        guard let sid = serverSessionID, let store else { return }
        for name in files where ["model.glb", "report.json", "points.ply", "mesh.ply", "manifest.json"].contains(name) {
            if let d = try? await transport.download("sessions/\(sid)/artifacts/\(name)"), let u = try? store.saveArtifact(name: name, data: d) {
                resultFiles.append(u)
            }
        }
    }
}
