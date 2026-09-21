import ARKit
import AVFoundation
import Combine
import CoreImage
import SceneKit
import SwiftUI
import Vision
import simd

private struct FrameAnalysis {
    var box: CGRect?
    var sharpness: Double
    var brightness: Double
    var clipped: Double
    var jpeg: Data?
    var originalJPEG: Data?
    var orientation: UInt32 = 1
    var raster: ScanRaster?
    var projection: ScanProjection?
    var hull: SilhouettePreview?
}

// One retained analysis frame; movie encoding admits at most one additional camera buffer.
@MainActor
final class GuidedScan: NSObject, ObservableObject, @preconcurrency ARSessionDelegate, Identifiable {
    let id = UUID()
    enum Phase { case preparing, detecting, adjusting, scanning, paused, review, failed }
    @Published var phase: Phase = .preparing
    @Published var instruction = "Aim at the dish. Keep the whole plate in view."
    @Published var progress = 0.0
    @Published var coverage = ScanCoverage()
    @Published var previewHasPoints = false
    @Published var depthAvailable = false
    @Published var meshAvailable = false
    @Published var canCenterManually = false
    @Published var estimatedVolume = false
    @Published var previewKind = "Observed points · provisional"
    @Published var previewThumbnail: UIImage?
    @Published var nextSector: Int?
    @Published var guidanceArrow = "arrow.clockwise"
    @Published var error: String?
    @Published var recordingSeconds = 0
    @Published var recordingVideo = false
    @Published var savingVideo = false
    @Published private(set) var captureVolume: ScanVolume?
    @Published private(set) var trackingReady = false
    @Published private(set) var acceptedViewCount = 0
    @Published private(set) var previewPointCount = 0
    // A display-density warning, not a photogrammetry confidence or a fidelity score.
    var previewSparse: Bool { previewPointCount < 80 }
    private var volumeConfirmed = false
    var volumeConfirmedForDisplay: Bool { volumeConfirmed }
    private lazy var gizmo: CaptureVolumeGizmo = {
        let value = CaptureVolumeGizmo(camera: camera)
        value.onChange = { [weak self] volume in self?.setVolume(volume) }
        return value
    }()
    private var movie: ScanMovieRecorder?
    private var movieStarted: Double?
    private var movieFinalization: Task<Void, Never>?
    private var backgroundSave: UIBackgroundTaskIdentifier = .invalid
    let camera = ARSCNView(frame: .zero)
    let preview = SCNScene()
    let record: CaptureRecord
    private let processing = DispatchQueue(label: "app.dishplay.scan.analysis", qos: .userInitiated)
    private let context = CIContext(options: [.cacheIntermediates: false])
    private var analyzing = false
    private var generation = 0
    private var lastAnalysis = -Double.infinity
    private var previousPose: (SIMD3<Float>, TimeInterval)?
    private var lastAcceptedPosition: SIMD3<Float>?
    private var target: SIMD3<Float>?
    private var candidate: SIMD3<Float>?
    private var stableDetections = 0
    private var radius: Float = 0.18
    private var startAngle: Double?
    private var points: [String: (position: SIMD3<Float>, color: SIMD3<Float>)] = [:]
    private var silhouette: SilhouettePreview?
    private var lastRaster: ScanRaster?
    private var lastProjection: ScanProjection?
    private var meshAnchors: [UUID: ARMeshAnchor] = [:]
    private var lastMeshPreview = -Double.infinity
    private var detectingSince = Date()
    private var lastViewAngle: Double?
    private var orbitDirection = 1
    private var shownPreview: SCNNode?
    private let previewRoot = SCNNode()
    private var orbitNodes: [SCNNode] = []
    private let targetNode = SCNNode()
    private var milestone = 0
    private var configured = false
    private var stopped = false
    var onSaved: (() -> Void)?

    init(record: CaptureRecord) {
        self.record = record
        super.init()
        camera.scene = SCNScene()
        camera.preferredFramesPerSecond = 30
        camera.automaticallyUpdatesLighting = false
        camera.rendersContinuously = false
        camera.session.delegate = self
        camera.session.delegateQueue = .main
        preview.rootNode.addChildNode(previewRoot)
        let eye = SCNNode()
        eye.camera = SCNCamera()
        eye.camera?.zNear = 0.01
        eye.position = SCNVector3(0, 0.45, 0.8)
        eye.look(at: SCNVector3(0, 0.04, 0))
        preview.rootNode.addChildNode(eye)
    }
    func start() {
        guard phase == .preparing, !configured, !stopped else { return }
        guard ARWorldTrackingConfiguration.isSupported else {
            phase = .failed
            error = "Spatial tracking is unavailable on this device. Use Video only under Other capture methods; your PC can still reconstruct the saved views."
            return
        }
        Task {
            let allowed: Bool
            switch AVCaptureDevice.authorizationStatus(for: .video) {
            case .authorized: allowed = true
            case .notDetermined: allowed = await AVCaptureDevice.requestAccess(for: .video)
            default: allowed = false
            }
            guard phase == .preparing, !stopped else { return }
            guard allowed else {
                phase = .failed
                error = "Camera access is off. Enable it in Settings, then try again. Existing captures are preserved."
                return
            }
            runSession(reset: true)
            beginDetection()
        }
    }
    private func recordMovie(_ frame: ARFrame) {
        guard !savingVideo else { return }
        if movie == nil {
            let folder = CaptureFiles.root(record).appendingPathComponent("Movies", isDirectory: true)
            do { try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true) }
            catch { self.error = "The video could not be saved. Your captured views remain available."; pause(); return }
            let angle: CGFloat
            switch camera.window?.windowScene?.interfaceOrientation ?? .portrait {
            case .portrait: angle = .pi / 2
            case .portraitUpsideDown: angle = -.pi / 2
            case .landscapeLeft: angle = .pi
            default: angle = 0
            }
            movie = ScanMovieRecorder(url: folder.appendingPathComponent(UUID().uuidString + ".mov"), transform: CGAffineTransform(rotationAngle: angle)) { [weak self] in
                Task { @MainActor in
                    self?.error = "The video could not be saved. Your captured views remain available."
                    self?.pause()
                }
            }
            movieStarted = frame.timestamp
            recordingSeconds = 0
        }
        let seconds = Int(frame.timestamp - (movieStarted ?? frame.timestamp))
        if recordingSeconds != seconds { recordingSeconds = seconds }
        if recordingSeconds >= 90 {
            pause()
            instruction = "Video segment saved. Resume to capture the missing areas."
            return
        }
        if movie?.append(frame.capturedImage, timestamp: frame.timestamp) == true { recordingVideo = true }
    }
    private func finishMovie() {
        guard let movie else { return }
        self.movie = nil; movieStarted = nil; recordingVideo = false; savingVideo = true
        // Give the small encoder queue time to finish when the app goes into the background.
        backgroundSave = UIApplication.shared.beginBackgroundTask(withName: "Save scan video") { [weak self] in
            Task { @MainActor in self?.endBackgroundSave() }
        }
        movieFinalization = Task {
            defer { savingVideo = false; movieFinalization = nil; endBackgroundSave(); onSaved?() }
            do {
                if let url = try await movie.finish() {
                    var current = CaptureFiles.latest(record)
                    let path = "Movies/" + url.lastPathComponent
                    current.sourceVideoPath = path
                    current.videoPaths = (current.videoPaths ?? []) + [path]
                    try CaptureFiles.save(current)
                }
            } catch { self.error = "The video could not be saved. Your captured views remain available." }
        }
    }
    private func endBackgroundSave() {
        if backgroundSave != .invalid { UIApplication.shared.endBackgroundTask(backgroundSave); backgroundSave = .invalid }
    }
    private func beginDetection() {
        phase = .detecting
        detectingSince = Date()
        canCenterManually = false
        let ticket = generation
        Task { [weak self] in
            try? await Task.sleep(for: .seconds(4))
            guard let self, !self.stopped, self.generation == ticket, self.phase == .detecting else { return }
            self.canCenterManually = true
        }
    }
    private func runSession(reset: Bool) {
        let configuration = ARWorldTrackingConfiguration()
        configuration.planeDetection = [.horizontal]
        configuration.isAutoFocusEnabled = true
        depthAvailable = ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth)
        if depthAvailable { configuration.frameSemantics.insert(.sceneDepth) }
        meshAvailable = ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh)
        if meshAvailable { configuration.sceneReconstruction = .mesh }
        if let format = ARWorldTrackingConfiguration.supportedVideoFormats.first(where: {
            $0.framesPerSecond == 30 && $0.imageResolution.width >= 1920 && $0.imageResolution.width <= 2048
        }) { configuration.videoFormat = format }
        camera.session.run(configuration, options: reset ? [.resetTracking, .removeExistingAnchors] : [])
        configured = true
    }
    func pause() {
        guard phase == .detecting || phase == .adjusting || phase == .scanning else { return }
        generation += 1
        camera.session.pause()
        phase = .paused
        gizmo.enabled = false
        trackingReady = false
        finishMovie()
        instruction = "Scan paused. Return to the same view, then resume."
    }
    func resume() {
        guard configured, !savingVideo, phase == .paused || phase == .review else { return }
        generation += 1
        previousPose = nil
        runSession(reset: false)
        phase = target == nil ? .detecting : volumeConfirmed ? .scanning : .adjusting
        gizmo.display(captureVolume, editable: phase == .adjusting)
        if target == nil { beginDetection() }
    }
    func finish() {
        guard phase == .scanning || phase == .paused else { return }
        generation += 1
        camera.session.pause()
        phase = .review
        finishMovie()
        previewRoot.removeAction(forKey: "scan-rotation")
        instruction = previewSparse ? "The preview is too sparse to assess. Review your views before sending."
            : coverage.complete ? "Views captured. Review the preview before creating the final model."
            : "Some views are missing. You can scan only the missing areas."
        savePreview()
        onSaved?()
    }
    func stop() {
        stopped = true
        generation += 1
        camera.session.pause()
        camera.session.delegate = nil
        gizmo.enabled = false
        finishMovie()
        onSaved?()
    }
    func sessionWasInterrupted(_ session: ARSession) { pause() }
    func sessionShouldAttemptRelocalization(_ session: ARSession) -> Bool { true }
    func session(_ session: ARSession, didFailWithError error: Error) {
        generation += 1
        phase = .failed
        gizmo.enabled = false
        finishMovie()
        self.error = error.localizedDescription
        onSaved?()
    }
    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        let normal: Bool
        if case .normal = frame.camera.trackingState { normal = true } else { normal = false }
        if trackingReady != normal { trackingReady = normal }
        if phase == .scanning { recordMovie(frame) }
        if phase == .adjusting {
            // Keep an explicit start/framing error visible until the box is adjusted.
            if !normal {
                if instruction != "Move gently while the camera finds its position." {
                    instruction = "Move gently while the camera finds its position."
                }
            } else if instruction == "Move gently while the camera finds its position." {
                instruction = "Fit the box around the whole dish, then start recording."
            }
            return
        }
        guard phase == .detecting || phase == .scanning, !analyzing,
              frame.timestamp - lastAnalysis >= 0.35 else { return }
        lastAnalysis = frame.timestamp
        canCenterManually = phase == .detecting && Date().timeIntervalSince(detectingSince) > 4
        guard case .normal = frame.camera.trackingState else {
            instruction = "Move gently while the camera finds its position."
            return
        }
        let position = SIMD3<Float>(frame.camera.transform.columns.3.x, frame.camera.transform.columns.3.y, frame.camera.transform.columns.3.z)
        defer { previousPose = (position, frame.timestamp) }
        if let previousPose {
            let speed = simd_distance(position, previousPose.0) / Float(max(0.001, frame.timestamp - previousPose.1))
            if speed > 0.65 { instruction = "Slow down."; return }
        }
        if let target {
            gatherPoints(frame, center: target)
            let offset = position - target
            let distance = simd_length(offset)
            if distance < radius * 1.5 { instruction = "Move a little farther away."; return }
            if distance > max(0.85, radius * 4.5) { instruction = "Move a little closer."; return }
            if !volumeInFrame() {
                instruction = "Keep the whole dish inside the frame."; return
            }
            let angle = atan2(Double(offset.x), Double(offset.z))
            let relative = angle - (startAngle ?? angle)
            if let lastViewAngle {
                let delta = atan2(sin(relative-lastViewAngle), cos(relative-lastViewAngle))
                if abs(delta) > 0.06 { orbitDirection = delta > 0 ? 1 : -1 }
            }
            lastViewAngle = relative
            nextSector = coverage.nextNeeded(from: relative, direction: orbitDirection)
            guidanceArrow = orbitDirection > 0 ? "arrow.clockwise" : "arrow.counterclockwise"
            updateOrbit()
            let elevation = atan2(Double(offset.y), Double(hypot(offset.x, offset.z)))
            if !coverage.needs(angle: relative, elevation: elevation, time: frame.timestamp) {
                instruction = coverage.covered == ScanCoverage.sectors && coverage.upperViews < 4
                    ? "Raise the phone slightly and follow the remaining arc."
                    : "This area is captured. Continue around the unfilled arc."
                return
            }
            if let lastAcceptedPosition, simd_distance(position, lastAcceptedPosition) < 0.025 { return }
        }
        analyzing = true
        let ticket = generation
        let context = self.context
        let hull = silhouette
        let volume = captureVolume
        let projection = ScanProjection(cameraToWorld: frame.camera.transform, intrinsics: frame.camera.intrinsics,
            resolution: SIMD2(Float(frame.camera.imageResolution.width), Float(frame.camera.imageResolution.height)))
        let orientation: CGImagePropertyOrientation
        switch camera.window?.windowScene?.interfaceOrientation ?? .portrait {
        case .portrait: orientation = .right
        case .portraitUpsideDown: orientation = .left
        case .landscapeLeft: orientation = .down
        default: orientation = .up
        }
        processing.async { [weak self] in
            let result = Self.analyze(frame.capturedImage, context: context, orientation: orientation, projection: projection, hull: hull, volume: volume)
            DispatchQueue.main.async { [weak self] in
                guard let self else { return }
                self.analyzing = false
                guard self.generation == ticket, self.phase == .detecting || self.phase == .scanning else { return }
                self.consume(result, frame: frame, position: position)
            }
        }
    }
    nonisolated private static func analyze(_ buffer: CVPixelBuffer, context: CIContext, orientation: CGImagePropertyOrientation,
                                            projection: ScanProjection, hull: SilhouettePreview?, volume: ScanVolume?) -> FrameAnalysis {
        autoreleasepool {
            let image = CIImage(cvPixelBuffer: buffer)
            let size = 96
            let polygon = volume?.footprint(projection) ?? []
            var pixels = [UInt8](repeating: 0, count: size * size)
            let scaled = image.transformed(by: CGAffineTransform(scaleX: CGFloat(size) / image.extent.width, y: CGFloat(size) / image.extent.height))
            context.render(scaled, toBitmap: &pixels, rowBytes: size, bounds: CGRect(x: 0, y: 0, width: size, height: size), format: .L8, colorSpace: CGColorSpaceCreateDeviceGray())
            var sum = 0.0, lap = 0.0, lapSquared = 0.0, clipped = 0.0, count = 0.0
            for y in 1..<95 { for x in 1..<95 {
                // Core Image's bitmap rows run from the lower edge; projection UVs start at the upper edge.
                if volume != nil {
                    guard ScanVolume.inside(SIMD2((Float(x)+0.5)/96, 1-(Float(y)+0.5)/96), polygon: polygon) else { continue }
                } else if x < 16 || x >= 80 || y < 16 || y >= 80 { continue }
                let p = y * size + x, v = Double(pixels[y * size + x])
                let l = 4 * v - Double(pixels[p-1]) - Double(pixels[p+1]) - Double(pixels[p-size]) - Double(pixels[p+size])
                sum += v; lap += l; lapSquared += l*l; count += 1
                if v < 8 || v > 248 { clipped += 1 }
            }}
            guard count >= 16 else { return FrameAnalysis(sharpness: 0, brightness: 0, clipped: 1) }
            var result = FrameAnalysis(sharpness: lapSquared/count - pow(lap/count, 2), brightness: sum/count, clipped: clipped/count)
            result.orientation = orientation.rawValue
            result.projection = projection
            // Foreground is not a food classifier. Choose a central instance, including plates with a hole at the exact center.
            let request = VNGenerateForegroundInstanceMaskRequest()
            let handler = VNImageRequestHandler(cvPixelBuffer: buffer, orientation: .up)
            do {
                try handler.perform([request])
                if let observation = request.results?.first, let label = centralInstance(observation.instanceMask, polygon: polygon) {
                    // Use Apple's full-image mapping before downsampling; model padding must not corrupt camera projection.
                    let mask = try observation.generateScaledMaskForImage(forInstances: IndexSet(integer: Int(label)), from: handler)
                    let side = 64
                    var foreground = [UInt8](repeating: 0, count: side * side)
                    CVPixelBufferLockBaseAddress(mask, .readOnly)
                    if let base = CVPixelBufferGetBaseAddress(mask) {
                        let w = CVPixelBufferGetWidth(mask), h = CVPixelBufferGetHeight(mask), row = CVPixelBufferGetBytesPerRow(mask)
                        let floating = CVPixelBufferGetPixelFormatType(mask) == kCVPixelFormatType_OneComponent32Float
                        for y in 0..<side { for x in 0..<side {
                            let address = base.advanced(by: (y*h/side)*row + (x*w/side)*(floating ? 4 : 1))
                            let value = floating ? address.load(as: Float.self) : Float(address.load(as: UInt8.self))/255
                            foreground[y*side+x] = value > 0.5 ? 1 : 0
                            if volume != nil, !ScanVolume.inside(SIMD2((Float(x)+0.5)/Float(side), (Float(y)+0.5)/Float(side)), polygon: polygon) {
                                foreground[y*side+x] = 0
                            }
                        }}
                    }
                    CVPixelBufferUnlockBaseAddress(mask, .readOnly)
                    var minX = side, minY = side, maxX = -1, maxY = -1
                    for y in 0..<side { for x in 0..<side where foreground[y*side+x] > 0 {
                        minX = min(minX,x); maxX = max(maxX,x); minY = min(minY,y); maxY = max(maxY,y)
                    }}
                    if maxX > minX && maxY > minY {
                        result.box = CGRect(x: Double(minX)/Double(side), y: Double(minY)/Double(side),
                            width: Double(maxX-minX+1)/Double(side), height: Double(maxY-minY+1)/Double(side))
                    }
                    var colorBuffer: CVPixelBuffer?
                    if CVPixelBufferCreate(nil, side, side, kCVPixelFormatType_32BGRA,
                        [kCVPixelBufferIOSurfacePropertiesKey: [:]] as CFDictionary, &colorBuffer) == kCVReturnSuccess, let colorBuffer {
                        let small = image.transformed(by: CGAffineTransform(scaleX: CGFloat(side)/image.extent.width, y: CGFloat(side)/image.extent.height))
                        context.render(small, to: colorBuffer, bounds: CGRect(x: 0,y: 0,width: side,height: side), colorSpace: CGColorSpaceCreateDeviceRGB())
                        CVPixelBufferLockBaseAddress(colorBuffer, .readOnly)
                        var rgba = [UInt8](repeating: 255, count: side * side * 4)
                        if let base = CVPixelBufferGetBaseAddress(colorBuffer)?.assumingMemoryBound(to: UInt8.self) {
                            let row = CVPixelBufferGetBytesPerRow(colorBuffer)
                            for y in 0..<side { for x in 0..<side {
                                let source = y*row+x*4, destination = (y*side+x)*4
                                rgba[destination] = base[source+2]; rgba[destination+1] = base[source+1]; rgba[destination+2] = base[source]
                            }}
                        }
                        CVPixelBufferUnlockBaseAddress(colorBuffer, .readOnly)
                        result.raster = ScanRaster(width: side, height: side, foreground: foreground, rgba: rgba)
                    }
                }
            } catch { /* Keep geometric guidance and real tracked points when segmentation is unavailable. */ }
            if result.sharpness >= 18 && result.brightness > 18 && result.brightness < 240 && result.clipped < 0.7 {
                func jpeg(_ source: CIImage) -> Data? {
                    let upright = source.oriented(orientation)
                    let scale = min(1, 1920 / max(upright.extent.width, upright.extent.height))
                    let export = upright.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
                    return context.jpegRepresentation(of: export, colorSpace: CGColorSpaceCreateDeviceRGB(),
                        options: [CIImageRepresentationOption(rawValue: kCGImageDestinationLossyCompressionQuality as String): 0.9])
                }
                if volume != nil {
                    // Keep the original separately; only the bounded derivative is uploaded for reconstruction.
                    if let isolated = ScanImageMask.isolate(image, polygon: polygon) {
                        result.originalJPEG = jpeg(image)
                        result.jpeg = jpeg(isolated)
                    }
                } else { result.jpeg = jpeg(image) }
                if var next = hull, let raster = result.raster {
                    next.integrate(raster, projection: projection)
                    result.hull = next
                }
            }
            return result
        }
    }
    nonisolated private static func centralInstance(_ mask: CVPixelBuffer, polygon: [SIMD2<Float>]) -> UInt8? {
        guard CVPixelBufferGetPixelFormatType(mask) == kCVPixelFormatType_OneComponent8 else { return nil }
        CVPixelBufferLockBaseAddress(mask, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(mask, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(mask)?.assumingMemoryBound(to: UInt8.self) else { return nil }
        let w = CVPixelBufferGetWidth(mask), h = CVPixelBufferGetHeight(mask), row = CVPixelBufferGetBytesPerRow(mask)
        var scores = [Int](repeating: 0, count: 256)
        for y in stride(from: 0, to: h, by: 3) { for x in stride(from: 0, to: w, by: 3) {
            if polygon.isEmpty {
                guard x >= w/4, x < w*3/4, y >= h/4, y < h*3/4 else { continue }
            } else if !ScanVolume.inside(SIMD2((Float(x)+0.5)/Float(w), (Float(y)+0.5)/Float(h)), polygon: polygon) { continue }
            let value = Int(base[y*row+x])
            if value > 0 { scores[value] += 1 }
        }}
        guard let label = (1..<256).max(by: { scores[$0] < scores[$1] }), scores[label] >= 8 else { return nil }
        return UInt8(label)
    }
    private func consume(_ result: FrameAnalysis, frame: ARFrame, position: SIMD3<Float>) {
        if result.brightness <= 18 || result.brightness >= 240 || result.clipped >= 0.7 {
            instruction = "Use brighter, diffuse lighting. Avoid reflections."; return
        }
        guard result.sharpness >= 18, let jpeg = result.jpeg else { instruction = "Hold the phone steady for a moment."; return }
        if target == nil, let box = result.box, box.width > 0.94 || box.height > 0.94 {
            instruction = "Move a little farther away."; return
        }
        if target == nil {
            guard let box = result.box, box.width > 0.08, box.height > 0.08 else {
                instruction = canCenterManually ? "Center the plate, then tap Center scan here." : "Aim at the dish. Keep the whole plate in view."
                return
            }
            let orientation = camera.window?.windowScene?.interfaceOrientation ?? .portrait
            let transform = frame.displayTransform(for: orientation, viewportSize: camera.bounds.size)
            let normalized = CGPoint(x: box.midX, y: box.midY).applying(transform)
            let pixel = CGPoint(x: normalized.x * camera.bounds.width, y: normalized.y * camera.bounds.height)
            guard let hit = surfacePoint(at: pixel) else {
                instruction = canCenterManually ? "Center the plate, then tap Center scan here." : "Move gently so the camera can locate the table."
                return
            }
            if let candidate, simd_distance(candidate, hit.position) < 0.07 { stableDetections += 1 } else { stableDetections = 0 }
            candidate = hit.position
            guard stableDetections >= 1 else { instruction = "Dish located. Hold steady."; return }
            let distance = simd_distance(position, hit.position)
            guard distance >= 0.18, distance <= 1.2 else { instruction = "Keep the phone beside and slightly above the plate."; return }
            let extent = min(0.28, max(0.10, Float(max(box.width, box.height)) * distance * 0.6))
            anchor(at: hit.position, radius: extent, position: position, estimated: hit.estimated)
            return
        }
        guard phase == .scanning, let target, let volume = captureVolume, let original = result.originalJPEG else { return }
        let offset = position-target
        let angle = atan2(Double(offset.x), Double(offset.z)) - (startAngle ?? 0)
        let elevation = atan2(Double(offset.y), Double(hypot(offset.x, offset.z)))
        guard elevation > 0.1, elevation < 1.4 else { instruction = "Keep the phone beside and slightly above the plate."; return }
        guard coverage.needs(angle: angle, elevation: elevation, time: frame.timestamp) else { return }
        do {
            let name = UUID().uuidString
            let originals = CaptureFiles.root(record).appendingPathComponent("Originals", isDirectory: true)
            try FileManager.default.createDirectory(at: originals, withIntermediateDirectories: true)
            try original.write(to: originals.appendingPathComponent(name + ".jpg"), options: .atomic)
            try jpeg.write(to: CaptureFiles.images(record).appendingPathComponent(name + ".jpg"), options: .atomic)
            let metadata: [String: Any] = ["schema": 3, "timestamp": frame.timestamp,
                "original": "Originals/" + name + ".jpg", "selectionMaskApplied": true,
                "volumeOrigin": [volume.origin.x, volume.origin.y, volume.origin.z],
                "volumeSize": [volume.size.x, volume.size.y, volume.size.z], "volumeYaw": volume.yaw,
                "transform": (0..<4).flatMap { c in (0..<4).map { r in frame.camera.transform[c][r] } },
                "intrinsics": (0..<3).flatMap { c in (0..<3).map { r in frame.camera.intrinsics[c][r] } },
                "imageResolution": [frame.camera.imageResolution.width, frame.camera.imageResolution.height],
                "photoOrientationApplied": result.orientation, "sharpness": result.sharpness, "angle": angle, "elevation": elevation,
                "segmentationAvailable": result.raster != nil, "estimatedCaptureVolume": estimatedVolume, "metricScaleVerified": false]
            try JSONSerialization.data(withJSONObject: metadata).write(to: CaptureFiles.checkpoints(record).appendingPathComponent(name + ".json"), options: .atomic)
            coverage.accept(angle: angle, elevation: elevation, time: frame.timestamp)
            acceptedViewCount = coverage.accepted
            lastAcceptedPosition = position
            lastRaster = result.raster
            lastProjection = result.projection
            if let hull = result.hull { silhouette = hull }
            if previewThumbnail == nil { previewThumbnail = UIImage(data: jpeg) }
            progress = coverage.progress
            nextSector = coverage.nextNeeded(from: angle, direction: orbitDirection)
            updateOrbit()
            gatherPoints(frame, center: target)
            var current = CaptureFiles.latest(record)
            current.imageCount = CaptureFiles.photos(record).count
            current.state = "scanning"
            try CaptureFiles.save(current)
            let reached = Int(progress * 4)
            if reached > milestone { milestone = reached; UIImpactFeedbackGenerator(style: .light).impactOccurred() }
            if coverage.covered >= ScanCoverage.sectors / 2 && coverage.upperViews < 4 {
                instruction = "Raise the phone slightly as you continue around the plate."
                guidanceArrow = "arrow.up"
            } else if coverage.covered >= ScanCoverage.sectors * 2 / 3, let nextSector {
                instruction = ["Complete the views near your starting position.", "A right-side view is missing. Follow the orange arc.",
                               "A view behind the dish is missing. Follow the orange arc.", "A left-side view is missing. Follow the orange arc."][min(3, nextSector * 4 / ScanCoverage.sectors)]
            } else { instruction = "Continue slowly around the highlighted arc." }
            if coverage.complete { UINotificationFeedbackGenerator().notificationOccurred(previewSparse ? .warning : .success); finish() }
        } catch { self.error = error.localizedDescription; pause() }
    }
    private func surfacePoint(at pixel: CGPoint) -> (position: SIMD3<Float>, estimated: Bool)? {
        for (kind, estimated) in [(ARRaycastQuery.Target.existingPlaneGeometry, false), (.estimatedPlane, true)] {
            if let query = camera.raycastQuery(from: pixel, allowing: kind, alignment: .horizontal),
               let hit = camera.session.raycast(query).first {
                return (SIMD3(hit.worldTransform.columns.3.x, hit.worldTransform.columns.3.y, hit.worldTransform.columns.3.z), estimated)
            }
        }
        return nil
    }
    func centerManually() {
        guard phase == .detecting || phase == .adjusting, let frame = camera.session.currentFrame, case .normal = frame.camera.trackingState else {
            instruction = "Move gently while the camera finds its position."
            return
        }
        let position = SIMD3(frame.camera.transform.columns.3.x, frame.camera.transform.columns.3.y, frame.camera.transform.columns.3.z)
        let pixel = CGPoint(x: camera.bounds.midX, y: camera.bounds.midY)
        if let hit = surfacePoint(at: pixel) { anchor(at: hit.position, radius: 0.18, position: position, estimated: hit.estimated) }
        else {
            // Explicitly chosen provisional volume. This is neither detected food nor measured depth.
            let center = frame.camera.transform * SIMD4<Float>(0, -0.025, -0.45, 1)
            anchor(at: SIMD3(center.x,center.y,center.z), radius: 0.18, position: position, estimated: true)
        }
    }
    private func anchor(at center: SIMD3<Float>, radius: Float, position: SIMD3<Float>, estimated: Bool) {
        phase = .adjusting
        volumeConfirmed = false
        estimatedVolume = estimated
        canCenterManually = false
        // The base is placed on the table. The user can correct every dimension before recording.
        setVolume(ScanVolume(origin: center, size: SIMD3(radius * 2, min(0.30, radius), radius * 2),
            yaw: atan2(position.x-center.x, position.z-center.z)))
        instruction = "Fit the box around the whole dish, then start recording."
    }
    private func setVolume(_ volume: ScanVolume) {
        guard phase == .adjusting else { return }
        captureVolume = volume; target = volume.origin; radius = volume.radius
        instruction = "Fit the box around the whole dish, then start recording."
        gizmo.display(volume, editable: true)
        if let eye = preview.rootNode.childNodes.first(where: { $0.camera != nil }) {
            eye.position = SCNVector3(0, max(radius, volume.size.y) * 1.9 + 0.15, radius * 3 + 0.2)
            eye.look(at: SCNVector3(0, volume.size.y / 2, 0))
        }
    }
    func resizeVolume(axis: Int, value: Float) {
        guard var volume = captureVolume else { return }
        volume.resize(axis: axis, to: value); setVolume(volume)
    }
    private func volumeInFrame() -> Bool {
        guard let volume = captureVolume, !camera.bounds.isEmpty else { return false }
        let bounds = camera.bounds.insetBy(dx: 8, dy: 8)
        return volume.corners.allSatisfy { point in
            let p = camera.projectPoint(SCNVector3(point))
            return p.z > 0 && p.z < 1 && bounds.contains(CGPoint(x: CGFloat(p.x), y: CGFloat(p.y)))
        }
    }
    func startCapture() {
        guard phase == .adjusting, let volume = captureVolume, let frame = camera.session.currentFrame,
              case .normal = frame.camera.trackingState else {
            instruction = "Move gently while the camera finds its position."; return
        }
        guard volumeInFrame() else { instruction = "Keep the whole dish inside the frame."; return }
        generation += 1
        let position = frame.camera.transform.columns.3
        startAngle = atan2(Double(position.x-volume.origin.x), Double(position.z-volume.origin.z))
        silhouette = SilhouettePreview(volume: volume)
        nextSector = 0; previousPose = nil; volumeConfirmed = true
        createOrbit(volume.origin)
        gizmo.display(volume, editable: false)
        previewRoot.eulerAngles = SCNVector3Zero
        previewRoot.runAction(.repeatForever(.rotateBy(x: 0, y: .pi * 2, z: 0, duration: 28)), forKey: "scan-rotation")
        phase = .scanning
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()
        instruction = "Continue slowly around the highlighted arc."
    }
    func restart() {
        guard !savingVideo, phase == .review || phase == .paused else { return }
        generation += 1
        camera.session.pause()
        do {
            let archive = CaptureFiles.root(record).appendingPathComponent("Retakes/" + UUID().uuidString, isDirectory: true)
            try FileManager.default.createDirectory(at: archive, withIntermediateDirectories: true)
            let oldPreview = CaptureFiles.root(record).appendingPathComponent("preview.json")
            if FileManager.default.fileExists(atPath: oldPreview.path) {
                try FileManager.default.moveItem(at: oldPreview, to: archive.appendingPathComponent("preview.json"))
            }
            for source in [CaptureFiles.images(record), CaptureFiles.checkpoints(record)] {
                try FileManager.default.moveItem(at: source, to: archive.appendingPathComponent(source.lastPathComponent))
                try FileManager.default.createDirectory(at: source, withIntermediateDirectories: true)
            }
            let originals = CaptureFiles.root(record).appendingPathComponent("Originals", isDirectory: true)
            if FileManager.default.fileExists(atPath: originals.path) {
                try FileManager.default.moveItem(at: originals, to: archive.appendingPathComponent("Originals"))
            }
            var current = CaptureFiles.latest(record)
            current.sourceVideoPath = nil; current.videoPaths = nil; current.imageCount = 0
            current.state = "ready"
            try CaptureFiles.save(current)
            // Prior movie segments stay in Movies; restart never deletes originals.
            coverage = ScanCoverage(); progress = 0; target = nil; candidate = nil; startAngle = nil
            captureVolume = nil; volumeConfirmed = false; acceptedViewCount = 0; previewPointCount = 0
            gizmo.display(nil, editable: false)
            stableDetections = 0; lastAcceptedPosition = nil; previousPose = nil; lastViewAngle = nil; milestone = 0
            points.removeAll(); silhouette = nil; lastRaster = nil; lastProjection = nil; meshAnchors.removeAll()
            previewThumbnail = nil; previewHasPoints = false; shownPreview = nil; nextSector = nil
            previewRoot.childNodes.forEach { $0.removeFromParentNode() }
            previewRoot.removeAllActions(); previewRoot.eulerAngles = SCNVector3Zero
            targetNode.childNodes.forEach { $0.removeFromParentNode() }; targetNode.removeFromParentNode(); orbitNodes.removeAll()
            error = nil; estimatedVolume = false; canCenterManually = false
            beginDetection()
            instruction = "Aim at the dish. Keep the whole plate in view."
            runSession(reset: true)
            onSaved?()
        } catch { self.error = error.localizedDescription; phase = .failed }
    }
    private func createOrbit(_ center: SIMD3<Float>) {
        targetNode.childNodes.forEach { $0.removeFromParentNode() }; orbitNodes.removeAll()
        targetNode.simdPosition = center
        camera.scene.rootNode.addChildNode(targetNode)
        for index in 0..<ScanCoverage.sectors {
            let middle = (Float(index)+0.5) / Float(ScanCoverage.sectors) * 2 * .pi + Float(startAngle ?? 0)
            let half = Float.pi / Float(ScanCoverage.sectors) * 0.85
            let inner = radius * 1.35, outer = radius * 1.5
            let y: Float = 0.025
            let vertices = [SCNVector3(sin(middle-half)*inner,y,cos(middle-half)*inner),
                            SCNVector3(sin(middle-half)*outer,y,cos(middle-half)*outer),
                            SCNVector3(sin(middle+half)*outer,y,cos(middle+half)*outer),
                            SCNVector3(sin(middle+half)*inner,y,cos(middle+half)*inner)]
            let geometry = SCNGeometry(sources: [SCNGeometrySource(vertices: vertices)],
                elements: [SCNGeometryElement(indices: [UInt16(0),1,2,0,2,3], primitiveType: .triangles)])
            let material = SCNMaterial()
            material.lightingModel = .constant
            material.isDoubleSided = true
            geometry.materials = [material]
            let node = SCNNode(geometry: geometry)
            orbitNodes.append(node); targetNode.addChildNode(node)
        }
        updateOrbit()
    }
    private func updateOrbit() {
        SCNTransaction.begin(); SCNTransaction.animationDuration = 0.18
        for (index, node) in orbitNodes.enumerated() {
            let captured = coverage.elevations[index] != nil
            let next = index == nextSector
            node.geometry?.firstMaterial?.diffuse.contents = next ? UIColor.systemOrange : captured ? UIColor.systemMint : UIColor.white.withAlphaComponent(0.25)
            node.geometry?.firstMaterial?.emission.contents = next ? UIColor.systemOrange.withAlphaComponent(0.25) : UIColor.black
        }
        SCNTransaction.commit()
    }
    private func gatherPoints(_ frame: ARFrame, center: SIMD3<Float>) {
        func insert(_ point: SIMD3<Float>) {
            let local = point-center
            guard captureVolume?.contains(point) == true else { return }
            let key = "\(Int(local.x*250)),\(Int(local.y*250)),\(Int(local.z*250))"
            let color = lastProjection?.project(point).flatMap { lastRaster?.sample($0) }.flatMap { $0.inside ? $0.color : nil }
                ?? SIMD3<Float>(0.3,0.9,0.75)
            if points.count < 4000 || points[key] != nil { points[key] = (local,color) }
        }
        frame.rawFeaturePoints?.points.forEach(insert)
        if let depth = frame.sceneDepth {
            let map = depth.depthMap, confidence = depth.confidenceMap
            CVPixelBufferLockBaseAddress(map, .readOnly)
            if let confidence { CVPixelBufferLockBaseAddress(confidence, .readOnly) }
            defer {
                CVPixelBufferUnlockBaseAddress(map, .readOnly)
                if let confidence { CVPixelBufferUnlockBaseAddress(confidence, .readOnly) }
            }
            if let base = CVPixelBufferGetBaseAddress(map)?.assumingMemoryBound(to: Float.self) {
                let w = CVPixelBufferGetWidth(map), h = CVPixelBufferGetHeight(map), row = CVPixelBufferGetBytesPerRow(map)/4
                let sx = Float(frame.camera.imageResolution.width)/Float(w), sy = Float(frame.camera.imageResolution.height)/Float(h)
                let k = frame.camera.intrinsics
                let confidenceBase = confidence.flatMap { CVPixelBufferGetBaseAddress($0)?.assumingMemoryBound(to: UInt8.self) }
                let confidenceRow = confidence.map { CVPixelBufferGetBytesPerRow($0) } ?? 0
                for y in stride(from: 0, to: h, by: 4) { for x in stride(from: 0, to: w, by: 4) {
                    if let confidenceBase, confidenceBase[y*confidenceRow+x] < 1 { continue }
                    let z = base[y*row+x]
                    guard z.isFinite, z > 0.1, z < 1.5 else { continue }
                    let local = SIMD4<Float>((Float(x)*sx-k[2][0])*z/k[0][0], -(Float(y)*sy-k[2][1])*z/k[1][1], -z, 1)
                    let world = frame.camera.transform * local
                    insert(SIMD3(world.x,world.y,world.z))
                }}
            }
        }
        if meshAvailable, frame.timestamp - lastMeshPreview >= 1, renderMeasuredMesh(center: center) {
            lastMeshPreview = frame.timestamp
            return
        }
        if previewKind == "Measured surface · provisional", frame.timestamp - lastMeshPreview < 1 { return }
        let hull = silhouette?.surface() ?? ScanPreviewPoints()
        if !depthAvailable, !hull.positions.isEmpty {
            renderPoints(hull, kind: "Silhouette estimate · provisional")
        } else if !points.isEmpty {
            let values = Array(points.values)
            renderPoints(ScanPreviewPoints(positions: values.map(\.position), colors: values.map(\.color)),
                         kind: depthAvailable ? "Measured points · provisional" : "Observed points · provisional")
        } else if !hull.positions.isEmpty { renderPoints(hull, kind: "Silhouette estimate · provisional") }
    }
    private func colorSource(_ colors: [SIMD3<Float>]) -> SCNGeometrySource {
        let values = colors.flatMap { [$0.x,$0.y,$0.z,Float(1)] }
        let data = values.withUnsafeBytes { Data($0) }
        return SCNGeometrySource(data: data, semantic: .color, vectorCount: colors.count, usesFloatComponents: true,
                                 componentsPerVector: 4, bytesPerComponent: 4, dataOffset: 0, dataStride: 16)
    }
    private func renderPoints(_ points: ScanPreviewPoints, kind: String) {
        guard !points.positions.isEmpty else { return }
        previewPointCount = points.positions.count
        let source = SCNGeometrySource(vertices: points.positions.map { SCNVector3($0) })
        let element = SCNGeometryElement(indices: Array(0..<UInt32(points.positions.count)), primitiveType: .point)
        element.pointSize = kind == "Silhouette estimate · provisional" ? 5 : 3
        element.minimumPointScreenSpaceRadius = 1; element.maximumPointScreenSpaceRadius = 5
        let geometry = SCNGeometry(sources: [source,colorSource(points.colors)], elements: [element])
        show(geometry, kind: kind)
    }
    private func show(_ geometry: SCNGeometry, kind: String) {
        let material = SCNMaterial()
        material.diffuse.contents = UIColor.white
        material.lightingModel = .constant
        material.isDoubleSided = true
        geometry.materials = [material]
        let node = SCNNode(geometry: geometry)
        node.opacity = 0
        previewRoot.addChildNode(node)
        node.runAction(.fadeIn(duration: 0.18))
        shownPreview?.runAction(.sequence([.fadeOut(duration: 0.18), .removeFromParentNode()]))
        shownPreview = node
        previewHasPoints = true
        previewKind = kind
    }
    func session(_ session: ARSession, didAdd anchors: [ARAnchor]) { updateMeshes(anchors) }
    func session(_ session: ARSession, didUpdate anchors: [ARAnchor]) { updateMeshes(anchors) }
    func session(_ session: ARSession, didRemove anchors: [ARAnchor]) {
        anchors.forEach { meshAnchors.removeValue(forKey: $0.identifier) }
    }
    private func updateMeshes(_ anchors: [ARAnchor]) {
        for anchor in anchors {
            if let mesh = anchor as? ARMeshAnchor { meshAnchors[mesh.identifier] = mesh }
        }
        // Keep only nearby anchors; a room scan must not become an unbounded dish preview.
        if meshAnchors.count > 12 {
            let target = self.target ?? .zero
            let nearest = meshAnchors.values.sorted {
                simd_distance(SIMD3($0.transform.columns.3.x,$0.transform.columns.3.y,$0.transform.columns.3.z),target)
                    < simd_distance(SIMD3($1.transform.columns.3.x,$1.transform.columns.3.y,$1.transform.columns.3.z),target)
            }.prefix(12)
            meshAnchors = Dictionary(uniqueKeysWithValues: nearest.map { ($0.identifier,$0) })
        }
    }
    private func renderMeasuredMesh(center: SIMD3<Float>) -> Bool {
        var vertices: [SCNVector3] = [], colors: [SIMD3<Float>] = []
        var examined = 0
        for anchor in meshAnchors.values {
            let mesh = anchor.geometry
            guard mesh.vertices.format == .float3, mesh.faces.indexCountPerPrimitive == 3,
                  mesh.faces.bytesPerIndex == 2 || mesh.faces.bytesPerIndex == 4 else { continue }
            let faces = mesh.faces.buffer.contents(), source = mesh.vertices.buffer.contents()
            for face in 0..<mesh.faces.count {
                examined += 1
                if vertices.count >= 12_000 || examined > 60_000 { break }
                var triangle: [SIMD3<Float>] = []
                for corner in 0..<3 {
                    let p = faces.advanced(by: (face*3+corner)*mesh.faces.bytesPerIndex)
                    let index = mesh.faces.bytesPerIndex == 4 ? Int(p.load(as: UInt32.self)) : Int(p.load(as: UInt16.self))
                    guard index < mesh.vertices.count else { continue }
                    let address = source.advanced(by: mesh.vertices.offset+index*mesh.vertices.stride).assumingMemoryBound(to: Float.self)
                    let world = anchor.transform * SIMD4<Float>(address[0],address[1],address[2],1)
                    let local = SIMD3(world.x,world.y,world.z)-center
                    if captureVolume?.contains(SIMD3(world.x,world.y,world.z)) == true { triangle.append(local) }
                }
                guard triangle.count == 3 else { continue }
                for point in triangle {
                    vertices.append(SCNVector3(point))
                    let color = lastProjection?.project(point+center).flatMap { lastRaster?.sample($0) }.flatMap { $0.inside ? $0.color : nil }
                    colors.append(color ?? SIMD3<Float>(0.6,0.75,0.7))
                }
            }
        }
        guard vertices.count >= 18 else { return false }
        previewPointCount = vertices.count
        let geometry = SCNGeometry(sources: [SCNGeometrySource(vertices: vertices),colorSource(colors)],
            elements: [SCNGeometryElement(indices: Array(0..<UInt32(vertices.count)), primitiveType: .triangles)])
        show(geometry, kind: "Measured surface · provisional")
        return true
    }
    private func savePreview() {
        let hull = silhouette?.surface() ?? ScanPreviewPoints()
        let values = hull.positions.isEmpty ? points.values.map { [$0.position.x,$0.position.y,$0.position.z] } : hull.positions.map { [$0.x,$0.y,$0.z] }
        do {
            let data = try JSONSerialization.data(withJSONObject: ["schema": 2,
                "kind": hull.positions.isEmpty ? "observed-points" : "silhouette-estimate",
                "points": values, "coverage": progress, "finalModel": false, "metricScaleVerified": false])
            try data.write(to: CaptureFiles.root(record).appendingPathComponent("preview.json"), options: .atomic)
        } catch { self.error = error.localizedDescription }
    }

}

struct ScanCameraView: UIViewRepresentable {
    let scan: GuidedScan
    func makeUIView(context: Context) -> ARSCNView { scan.camera }
    func updateUIView(_ view: ARSCNView, context: Context) {}
}

struct GuidedScanScreen: View {
    @StateObject var scan: GuidedScan
    let linked: Bool
    let onContinue: () -> Void
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @State private var help = false
    @State private var confirmRestart = false
    @State private var selectedAxis = 0

    var body: some View {
        GeometryReader { proxy in
            if proxy.size.width > proxy.size.height {
                HStack(spacing: 0) {
                    cameraPanel.frame(width: proxy.size.width * 0.57)
                    previewPanel
                }
            } else {
                VStack(spacing: 0) {
                    cameraPanel.frame(height: proxy.size.height * 0.59)
                    previewPanel
                }
            }
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            controls.padding(.horizontal, 18).padding(.vertical, 12)
                .frame(maxWidth: .infinity).background(Color(.systemBackground))
        }
        .background(Color(.systemBackground))
        .onAppear { scan.start() }
        .onDisappear { scan.stop() }
        .onChange(of: scenePhase) { _, value in if value != .active { scan.pause() } }
        .alert("One gentle orbit", isPresented: $help) {
            Button("OK", role: .cancel) {}
        } message: {
            Text("Fit the box around the dish and plate. Drag its white handles or use the size controls; pinch to scale, drag to move, and rotate with two fingers. Start recording, then walk slowly around the stationary dish. Follow the orange arc and raise the phone for the top. The lower preview comes from your observations. Your PC creates the final model after upload. Remove transparent lids and avoid reflections.")
        }
        .confirmationDialog("Start this scan again?", isPresented: $confirmRestart) {
            Button("Restart scan") { scan.restart() }
        } message: { Text("Your previous views remain saved on this iPhone.") }
    }
    private var cameraPanel: some View {
        ZStack {
            ScanCameraView(scan: scan)
            if scan.phase == .detecting {
                RoundedRectangle(cornerRadius: 44)
                    .stroke(.white.opacity(0.65), style: StrokeStyle(lineWidth: 1.5, dash: [8,8]))
                    .frame(maxWidth: 250, maxHeight: 180).padding(.vertical, 55)
                    .accessibilityHidden(true)
            }
            VStack(spacing: 10) {
                HStack {
                    Button { dismiss() } label: {
                        Image(systemName: "xmark").frame(width: 44, height: 44)
                    }.accessibilityLabel("Close").disabled(scan.savingVideo)
                    Spacer()
                    VStack(spacing: 2) {
                        Text("Film and scan my dish").font(.headline)
                        if scan.phase == .adjusting { Text("1 · Adjust the box").font(.caption) }
                        if scan.recordingVideo {
                            HStack(spacing: 5) {
                                Circle().fill(.red).frame(width: 7, height: 7)
                                Text("Recording"); Text(scan.recordingSeconds, format: .number).monospacedDigit(); Text("s")
                            }.font(.caption)
                        }
                        if scan.phase == .scanning || scan.phase == .review || scan.phase == .paused {
                            Text(scan.progress, format: .percent.precision(.fractionLength(0)))
                                .font(.title3.monospacedDigit().bold())
                            Text("Views covered").font(.caption2)
                        }
                    }
                    Spacer()
                    Button { help = true } label: {
                        Image(systemName: "questionmark").frame(width: 44, height: 44)
                    }.accessibilityLabel("Scan help")
                }.background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 24))
                Spacer(minLength: 0)
                HStack(spacing: 10) {
                    Image(systemName: scan.phase == .adjusting ? "cube.transparent" : scan.phase == .review ? "eye" : scan.guidanceArrow)
                        .font(.title2).foregroundStyle(Color.orange)
                    Text(LocalizedStringKey(scan.instruction)).font(.callout.weight(.semibold))
                        .fixedSize(horizontal: false, vertical: true)
                }.padding(12).frame(maxWidth: .infinity)
                    .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 18))
            }.padding(14)
        }.clipped()
    }
    private var previewPanel: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Live 3D preview").font(.headline)
                Spacer()
                if scan.phase == .review { Image(systemName: "hand.draw").foregroundStyle(.secondary) }
            }
            if scan.phase == .adjusting {
                Text("Include the whole plate. Leave neighbouring objects outside.").font(.caption).foregroundStyle(.secondary)
            } else { Text(LocalizedStringKey(scan.previewKind)).font(.caption).foregroundStyle(.secondary) }
            ZStack {
                SceneView(scene: scan.preview, options: scan.phase == .review ? [.allowsCameraControl] : [], preferredFramesPerSecond: 30)
                if !scan.previewHasPoints {
                    if scan.phase == .adjusting {
                        VStack(spacing: 8) {
                            Image(systemName: "cube.transparent").font(.system(size: 38, weight: .ultraLight))
                            Text("Your preview starts when you record and move around the dish.")
                                .font(.caption).multilineTextAlignment(.center)
                        }.foregroundStyle(.secondary).padding()
                    } else if let image = scan.previewThumbnail {
                        VStack(spacing: 6) {
                            Image(uiImage: image).resizable().scaledToFit().clipShape(RoundedRectangle(cornerRadius: 10))
                            Text("First view saved. Building the provisional preview…").font(.caption).multilineTextAlignment(.center)
                        }.padding(12)
                    } else {
                        Text("The first observations will appear here.").font(.caption)
                            .foregroundStyle(.secondary).multilineTextAlignment(.center).padding()
                    }
                }
            }.frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color.secondary.opacity(0.06)).clipShape(RoundedRectangle(cornerRadius: 18))
            if scan.estimatedVolume {
                Text("Capture volume estimated. Final shape and scale still need review.")
                    .font(.caption2).foregroundStyle(.secondary)
            }
            if let error = scan.error { Text(LocalizedStringKey(error)).font(.caption).foregroundStyle(.red) }
            if scan.volumeConfirmedForDisplay {
                HStack {
                    Label("Useful views: \(scan.acceptedViewCount)", systemImage: "photo.on.rectangle")
                    Spacer()
                    if scan.phase == .scanning {
                        Image(systemName: scan.trackingReady ? "location.fill" : "location.slash.fill")
                            .foregroundStyle(scan.trackingReady ? Color.mint : Color.orange)
                            .accessibilityLabel(scan.trackingReady ? "Position tracked" : "Finding camera position")
                    }
                }.font(.caption2)
                if scan.acceptedViewCount >= 4 && scan.previewSparse {
                    Text("Few usable points. Check the box, lighting and reflections before continuing.")
                        .font(.caption).foregroundStyle(.orange)
                }
            }
            if scan.phase == .scanning {
                HStack(spacing: 12) {
                    Label("Captured", systemImage: "circle.fill").foregroundStyle(.mint)
                    Label("Next area", systemImage: "circle.fill").foregroundStyle(.orange)
                }.font(.caption2)
            }
        }.padding(14)
    }
    @ViewBuilder private var controls: some View {
        switch scan.phase {
        case .preparing: ProgressView("Preparing camera…")
        case .detecting:
            if scan.canCenterManually {
                Button("Center scan here", systemImage: "scope") { scan.centerManually() }
                    .buttonStyle(.borderedProminent)
                Text("Use this if the table or plate cannot be detected. Keep the dish in the center.")
                    .font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.center)
            } else { ProgressView("Locating the dish and table…") }
        case .adjusting:
            VStack(spacing: 10) {
                Picker("Box dimension", selection: $selectedAxis) {
                    Text("Width").tag(0); Text("Height").tag(1); Text("Depth").tag(2)
                }.pickerStyle(.segmented)
                HStack(spacing: 12) {
                    Slider(value: Binding(get: { Double(scan.captureVolume?.size[selectedAxis] ?? 0.2) },
                        set: { scan.resizeVolume(axis: selectedAxis, value: Float($0)) }), in: 0.04...0.8)
                        .accessibilityLabel("Selected box dimension")
                    Text("~\(Int((scan.captureVolume?.size[selectedAxis] ?? 0.2) * 100)) cm")
                        .font(.caption.monospacedDigit()).frame(minWidth: 58)
                }
                HStack {
                    Button("Recenter", systemImage: "scope") { scan.centerManually() }.buttonStyle(.bordered)
                    Spacer()
                    Button("Start recording", systemImage: "record.circle") { scan.startCapture() }
                        .buttonStyle(.borderedProminent).disabled(!scan.trackingReady)
                }
            }
        case .scanning:
            VStack(spacing: 8) {
                Text("Video and useful views are saved together").font(.caption).foregroundStyle(.secondary)
                HStack {
                    Button("Pause", systemImage: "pause") { scan.pause() }.buttonStyle(.bordered)
                    Spacer()
                    Button("Review scan") { scan.finish() }.buttonStyle(.bordered).disabled(scan.coverage.accepted < 8)
                }
            }
        case .paused:
            HStack {
                Button("Resume scan") { scan.resume() }.buttonStyle(.borderedProminent).disabled(scan.savingVideo)
                Button("Review scan") { scan.finish() }.buttonStyle(.bordered).disabled(scan.coverage.accepted < 8)
            }
        case .review:
            VStack(spacing: 10) {
                if scan.savingVideo { ProgressView("Saving your video…") }
                Button(linked ? "Send and create my 3D dish" : "Save and link my dish", systemImage: "arrow.up.circle.fill") { onContinue(); dismiss() }
                    .buttonStyle(.borderedProminent).disabled(scan.coverage.accepted < 8 || scan.savingVideo)
                HStack {
                    if !scan.coverage.complete { Button("Scan a missing area") { scan.resume() } }
                    Button("Restart scan") { confirmRestart = true }
                }.buttonStyle(.bordered).font(.callout).disabled(scan.savingVideo)
            }
        case .failed:
            if AVCaptureDevice.authorizationStatus(for: .video) == .denied {
                Button("Open camera permission settings") {
                    if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
                }.buttonStyle(.borderedProminent)
            }
            Button("Back to my dish") { dismiss() }.buttonStyle(.bordered)
        }
    }
}
