import ARKit
import Foundation
import ScanCore
import UIKit

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
    }

    var lidarActive: Bool { ar.lidarActive }

    // MARK: actions

    func start() {
        guard box.placed else { return }
        let localID = ISO8601DateFormatter().string(from: Date()).replacingOccurrences(of: ":", with: "-")
        do { store = try SessionStore(localID: localID) } catch { errorText = error.localizedDescription; return }
        box.locked = true
        scheduler.reset()
        scheduler.epoch = ar.epoch
        scheduler.active = true
        phase = .scanning
        store?.writeSessionInfo(["local_id": localID, "box": (try? JSONSerialization.jsonObject(with: JSONEncoder().encode(box.spec(epoch: ar.epoch, revision: 0)))) ?? [:],
                                 "lidar": useLidar, "reference_width_m": referenceWidth as Any])
        startUploadLoop()
    }

    func pause() {
        scheduler.active = false
        phase = .paused
        if let sid = serverSessionID { Task { try? await transport.post("sessions/\(sid)/pause") } }
    }

    func resume() {
        guard phase == .paused else { return }
        scheduler.active = true
        phase = .scanning
        if let sid = serverSessionID { Task { try? await transport.post("sessions/\(sid)/resume") } }
    }

    /// Explicit box revision (only while paused): the calculator rebuilds the volume from stored frames.
    func reviseBox() { box.locked = false }

    func applyBoxRevision() {
        box.locked = true
        boxRevision += 1
        let spec = box.spec(epoch: ar.epoch, revision: boxRevision)
        if let sid = serverSessionID { Task { try? await transport.postBox(sessionID: sid, box: spec) } }
        if phase == .needsNewBox {
            scheduler.reset()
            scheduler.epoch = ar.epoch
            phase = .paused
        }
    }

    func finish() {
        scheduler.active = false
        phase = .uploadingRest
        Task {
            while (store?.pendingCount ?? 0) > 0 || serverSessionID == nil {
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
        if ar.worldWasReset && phase == .scanning {
            // New tracking epoch: the old box pose is meaningless in the new world. Never fuse silently.
            scheduler.active = false
            ar.acknowledgeReset()
            box.reset()
            phase = .needsNewBox
        }
        guard let store, phase == .scanning else {
            updateTrackingPoints(frame)
            return
        }
        scheduler.consider(frame, box: box, store: store, lidar: ar.lidarActive, formatText: ar.videoFormatText)
        if status != scheduler.status { status = scheduler.status }
        updateTrackingPoints(frame)
    }

    /// ARKit feature points inside the box, shown as "suivi" (unstable, never accumulated).
    private func updateTrackingPoints(_ frame: ARFrame) {
        guard box.placed, frame.timestamp - lastTrackingUpdate > 0.2 else { return }
        lastTrackingUpdate = frame.timestamp
        guard let raw = frame.rawFeaturePoints?.points else { return }
        let inv = box.worldFromObject.rigidInverse
        let w = Double(box.width) / 2, d = Double(box.depth) / 2, h = Double(box.height)
        var pts: [SIMD3<Float>] = []
        for p in raw {
            let o = inv.apply([Double(p.x), Double(p.y), Double(p.z)])
            if abs(o[0]) <= w, abs(o[2]) <= d, o[1] >= -0.005, o[1] <= h { pts.append(SIMD3(Float(o[0]), Float(o[1]), Float(o[2]))) }
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
            let body = SessionCreate(clientSessionID: store.localID, box: box.spec(epoch: scheduler.epoch, revision: boxRevision),
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
