import ARKit
import AVFoundation
import Combine
import RealityKit
import ScanCore

/// Owns the ONLY camera session (ARKit). No concurrent AVFoundation session is opened.
@MainActor
final class ARSessionController: NSObject, ObservableObject, ARSessionDelegate {
    enum TrackingQuality: Equatable { case notAvailable, limited(String), normal }

    let arView: ARView
    @Published private(set) var tracking: TrackingQuality = .notAvailable
    @Published private(set) var epoch = 0
    @Published private(set) var worldWasReset = false
    @Published private(set) var lidarActive = false
    @Published private(set) var videoFormatText = ""
    @Published private(set) var errorText: String?
    /// Why the camera or the tracking could not start, in the user's words; nil while they work.
    @Published private(set) var failure: String?
    /// The camera is refused to the app in the iPhone's settings: nothing can be scanned until it is allowed.
    @Published private(set) var cameraDenied = false

    /// Called for every ARFrame on the main thread. Must return quickly and must not retain the frame.
    var onFrame: (@MainActor (ARFrame) -> Void)?
    private var running = false
    private var useLidar = false

    static var worldTrackingSupported: Bool { ARWorldTrackingConfiguration.isSupported }
    static var lidarSupported: Bool { ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth) }

    override init() {
        arView = ARView(frame: .zero, cameraMode: .ar, automaticallyConfigureSession: false)
        super.init()
        arView.renderOptions.insert(.disableMotionBlur)
        arView.renderOptions.insert(.disableDepthOfField)
        arView.session.delegate = self
    }

    func start(useLidar: Bool) {
        self.useLidar = useLidar
        run(reset: true)
    }

    private func run(reset: Bool) {
        guard ARWorldTrackingConfiguration.isSupported else {
            errorText = "Cet appareil ne prend pas en charge le suivi ARKit."
            failure = "Cet iPhone ne peut pas suivre ses déplacements : le scan n’est pas possible ici."
            return
        }
        failure = nil
        cameraDenied = false
        let cfg = ARWorldTrackingConfiguration()
        cfg.planeDetection = [.horizontal]
        cfg.environmentTexturing = .none
        cfg.isAutoFocusEnabled = true
        // Prefer the 4:3 1920x1440 wide-angle format at 30 fps (stable intrinsics, enough detail).
        let formats = ARWorldTrackingConfiguration.supportedVideoFormats
        if let f = formats.first(where: { $0.imageResolution == CGSize(width: 1920, height: 1440) && $0.framesPerSecond == 30 }) {
            cfg.videoFormat = f
        }
        videoFormatText = "\(Int(cfg.videoFormat.imageResolution.width))x\(Int(cfg.videoFormat.imageResolution.height)) @\(cfg.videoFormat.framesPerSecond) fps"
        lidarActive = useLidar && ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth)
        if lidarActive { cfg.frameSemantics.insert(.sceneDepth) }
        arView.session.run(cfg, options: reset ? [.resetTracking, .removeExistingAnchors] : [])
        running = true
    }

    func pauseCamera() {
        arView.session.pause()
        running = false
    }

    func acknowledgeReset() { worldWasReset = false }

    #if DEBUG
    /// Screen check in the simulator, which has no camera: show the scanner as it is while tracking works,
    /// or as it is when the camera is refused to the app.
    func stage(cameraDenied denied: Bool) {
        tracking = denied ? .notAvailable : .normal
        cameraDenied = denied
        failure = denied ? "DishPlay Scan n’a pas accès à la caméra. Autorisez-la dans les réglages de l’iPhone." : nil
    }
    #endif

    // MARK: box anchor (ARKit keeps refining its map; an ARAnchor follows those corrections)

    private(set) var boxAnchorID: UUID?

    func setBoxAnchor(_ transform: simd_float4x4?) {
        if let id = boxAnchorID, let old = arView.session.currentFrame?.anchors.first(where: { $0.identifier == id }) {
            arView.session.remove(anchor: old)
        }
        boxAnchorID = nil
        guard let transform else { return }
        let a = ARAnchor(name: "dishplay.box", transform: transform)
        arView.session.add(anchor: a)
        boxAnchorID = a.identifier
    }

    func boxAnchorTransform(in frame: ARFrame) -> simd_float4x4? {
        guard let id = boxAnchorID else { return nil }
        return frame.anchors.first(where: { $0.identifier == id })?.transform
    }

    // MARK: exposure

    /// During a scan: fixed exposure and white balance (consistent colours between views) and a
    /// shutter no slower than 1/100 s (less motion blur; ISO compensates). Focus stays automatic.
    func setScanExposure(locked: Bool) {
        guard let dev = ARWorldTrackingConfiguration.configurableCaptureDeviceForPrimaryCamera else { return }
        do {
            try dev.lockForConfiguration()
            defer { dev.unlockForConfiguration() }
            if locked {
                let current = CMTimeGetSeconds(dev.exposureDuration)
                let fmt = dev.activeFormat
                let target = max(min(current, 1.0 / 100.0), CMTimeGetSeconds(fmt.minExposureDuration))
                if dev.isExposureModeSupported(.custom), current.isFinite, current > 0 {
                    let iso = min(fmt.maxISO, max(fmt.minISO, dev.iso * Float(current / target)))
                    dev.setExposureModeCustom(duration: CMTime(seconds: target, preferredTimescale: 1_000_000), iso: iso, completionHandler: nil)
                } else if dev.isExposureModeSupported(.locked) {
                    dev.exposureMode = .locked
                }
                if dev.isWhiteBalanceModeSupported(.locked) { dev.whiteBalanceMode = .locked }
            } else {
                if dev.isExposureModeSupported(.continuousAutoExposure) { dev.exposureMode = .continuousAutoExposure }
                if dev.isWhiteBalanceModeSupported(.continuousAutoWhiteBalance) { dev.whiteBalanceMode = .continuousAutoWhiteBalance }
            }
        } catch {
            errorText = "Réglage de l’exposition impossible : \(error.localizedDescription)"
        }
    }

    // MARK: ARSessionDelegate (main queue)

    nonisolated func session(_ session: ARSession, didUpdate frame: ARFrame) {
        MainActor.assumeIsolated {
            onFrame?(frame)
        }
    }

    nonisolated func session(_ session: ARSession, cameraDidChangeTrackingState camera: ARCamera) {
        let q: TrackingQuality
        switch camera.trackingState {
        case .normal: q = .normal
        case .notAvailable: q = .notAvailable
        case .limited(let r):
            switch r {
            case .initializing: q = .limited("initialisation")
            case .excessiveMotion: q = .limited("mouvement trop rapide")
            case .insufficientFeatures: q = .limited("pas assez de détails visibles")
            case .relocalizing: q = .limited("relocalisation")
            @unknown default: q = .limited("limité")
            }
        }
        MainActor.assumeIsolated { tracking = q }
    }

    /// Never relocalise silently into a possibly different world: a reset creates a new epoch.
    nonisolated func sessionShouldAttemptRelocalization(_ session: ARSession) -> Bool { false }

    nonisolated func sessionInterruptionEnded(_ session: ARSession) {
        MainActor.assumeIsolated {
            epoch += 1
            worldWasReset = true
            boxAnchorID = nil
            run(reset: true)
        }
    }

    nonisolated func session(_ session: ARSession, didFailWithError error: Error) {
        let denied = (error as? ARError)?.code == .cameraUnauthorized
        let text = error.localizedDescription
        MainActor.assumeIsolated {
            errorText = text
            cameraDenied = denied
            failure = denied ? "DishPlay Scan n’a pas accès à la caméra. Autorisez-la dans les réglages de l’iPhone."
                             : "La caméra ne démarre pas. Fermez le scan et rouvrez-le. (Détail : \(text))"
        }
    }
}
