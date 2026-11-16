import ARKit
import Foundation
import ScanCore

/// Turns the continuous ARKit stream into keyframes, automatically.
/// Runs its checks on the main thread (cheap), copies the selected pixel buffer, and hands
/// encoding/storage to a bounded background queue so rendering never stalls.
@MainActor
final class CaptureScheduler {
    struct Status: Equatable {
        var guidance: Guidance?
        var lastDecision = ""
        var accepted = 0
        var dropped = 0
        var inFlight = 0
    }

    private(set) var status = Status()
    var selector = KeyframeSelector()
    var ring = CoverageRing()
    var active = false
    var epoch = 0
    var nextFrameID = 0
    /// Box pose frozen at lock time; every keyframe pose is expressed relative to it.
    var lockedWorldFromObject: Mat4?
    private var lastEval = 0.0
    private let maxInFlight = 3
    private let encodeQueue = DispatchQueue(label: "app.dishplay.scan.encode", qos: .userInitiated)
    private var inFlight = 0

    var onSaved: (@MainActor (Int) -> Void)?   // frame id saved on disk
    var onError: (@MainActor (String) -> Void)?

    func reset() {
        selector.reset()
        ring = CoverageRing()
        status = Status()
        lastEval = 0
    }

    /// `worldFromCam` is the camera pose expressed in the frozen box world (see ScanController.cameraPose).
    func consider(_ frame: ARFrame, worldFromCam: Mat4, box: BoundingBoxController, store: SessionStore, lidar: Bool, formatText: String) {
        guard active else { return }
        // Evaluate at ~12 Hz: enough for keyframes at <= 4/s, keeps the main thread free.
        if frame.timestamp - lastEval < 0.08 { return }
        lastEval = frame.timestamp
        let cam = frame.camera
        let k = cam.intrinsics  // column-major: fx = k[0][0], fy = k[1][1], cx = k[2][0], cy = k[2][1]
        let K = Intrinsics(fx: Double(k[0][0]), fy: Double(k[1][1]), cx: Double(k[2][0]), cy: Double(k[2][1]),
                           width: Int(cam.imageResolution.width), height: Int(cam.imageResolution.height))
        let objFromCam = Coordinates.objectFromCameraCV(worldFromObject: lockedWorldFromObject ?? box.worldFromObject, worldFromCameraAR: worldFromCam)
        let vis = Coordinates.boxVisibility(K, cameraCVFromObject: objFromCam.rigidInverse, width: Double(box.width),
                                            height: Double(box.height), depth: Double(box.depth))
        var limitedReason: String?
        var normal = false
        switch cam.trackingState {
        case .normal: normal = true
        case .limited: limitedReason = "limited"
        default: break
        }
        let stats = FrameEncoder.lumaStats(frame.capturedImage, roi: boxROI(K, objFromCam.rigidInverse, box))
        let obs = FrameObservation(timestamp: frame.timestamp, worldFromCameraAR: worldFromCam, trackingNormal: normal,
                                   trackingLimitedReason: limitedReason, boxVisibility: vis, sharpness: stats.sharpness, meanLuma: stats.mean)
        let decision = selector.evaluate(obs)
        status.lastDecision = decision.reason
        let camInObj = objFromCam.translation
        if let s = ring.suggestion(currentCameraInObject: camInObj, boxHeight: Double(box.height)) {
            status.guidance = decision.guidance ?? s.0
        } else {
            status.guidance = decision.guidance
        }
        guard decision.accept else { return }
        if inFlight >= maxInFlight || ProcessInfo.processInfo.thermalState == .critical {
            status.dropped += 1
            return
        }
        guard let copy = FrameEncoder.copy(frame.capturedImage) else { status.dropped += 1; return }
        var depth: Data?, conf: Data?, dsize: (Int, Int)?
        if lidar, let sd = frame.sceneDepth {
            depth = FrameEncoder.packed(sd.depthMap, bytesPerPixel: 4)
            if let cm = sd.confidenceMap { conf = FrameEncoder.packed(cm, bytesPerPixel: 1) }
            dsize = (CVPixelBufferGetWidth(sd.depthMap), CVPixelBufferGetHeight(sd.depthMap))
        }
        ring.add(cameraInObject: camInObj, boxHeight: Double(box.height))
        let fid = nextFrameID
        nextFrameID += 1
        let captured = CapturedFrame(frameID: fid, epoch: epoch, timestamp: frame.timestamp, pixelBuffer: copy, intrinsics: K,
                                     worldFromCameraAR: worldFromCam, trackingNormal: normal, exposure: cam.exposureDuration,
                                     formatText: formatText,
                                     quality: .init(sharpness: stats.sharpness, mean_luma: stats.mean, box_in_view: vis,
                                                    translation_since_last_m: decision.translationSinceLast,
                                                    angular_speed_dps: decision.angularSpeedDps),
                                     depth: depth, confidence: conf, depthSize: dsize)
        inFlight += 1
        status.inFlight = inFlight
        status.accepted += 1
        // Slow down when the phone heats up.
        selector.minInterval = ProcessInfo.processInfo.thermalState == .serious ? 0.6 : 0.25
        encodeQueue.async { [weak self] in
            let result = Result { try FrameEncoder.encode(captured, sessionID: store.localID) }
            var errorText: String?
            if case .success(let enc) = result {
                do { try store.save(frameID: fid, jpeg: enc.jpeg, meta: enc.meta, depth: captured.depth, confidence: captured.confidence) }
                catch { errorText = "Stockage impossible : \(error.localizedDescription)" }
            } else if case .failure(let e) = result {
                errorText = "Encodage impossible : \(e.localizedDescription)"
            }
            let failure = errorText
            Task { @MainActor in
                guard let self else { return }
                self.inFlight -= 1
                self.status.inFlight = self.inFlight
                if let failure { self.onError?(failure) } else { self.onSaved?(fid) }
            }
        }
    }

    private func boxROI(_ K: Intrinsics, _ camFromObj: Mat4, _ box: BoundingBoxController) -> CGRect? {
        let pts = Coordinates.boxSamples(width: Double(box.width), height: Double(box.height), depth: Double(box.depth))
        let pr = Coordinates.project(K, cameraCVFromObject: camFromObj, points: pts).filter { $0.z > 0.05 }
        guard pr.count > 4 else { return nil }
        let xs = pr.map(\.u), ys = pr.map(\.v)
        return CGRect(x: xs.min()!, y: ys.min()!, width: xs.max()! - xs.min()!, height: ys.max()! - ys.min()!)
    }
}
