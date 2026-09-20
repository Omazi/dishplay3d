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
}

// Only one retained ARFrame and one serial image analysis at a time. No video recording.
@MainActor
final class GuidedScan: NSObject, ObservableObject, ARSessionDelegate, Identifiable {
    let id = UUID()
    enum Phase { case preparing, detecting, scanning, paused, review, failed }
    @Published var phase: Phase = .preparing
    @Published var instruction = "Aim at the dish. Keep the whole plate in view."
    @Published var progress = 0.0
    @Published var coverage = ScanCoverage()
    @Published var previewHasPoints = false
    @Published var depthAvailable = false
    @Published var error: String?
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
    private var points: [String: SIMD3<Float>] = [:]
    private var orbitNodes: [SCNNode] = []
    private let pointNode = SCNNode()
    private let targetNode = SCNNode()
    private var milestone = 0
    private var configured = false
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
        preview.rootNode.addChildNode(pointNode)
        let eye = SCNNode()
        eye.camera = SCNCamera()
        eye.camera?.zNear = 0.01
        eye.position = SCNVector3(0, 0.45, 0.8)
        eye.look(at: SCNVector3(0, 0.04, 0))
        preview.rootNode.addChildNode(eye)
    }
    func start() {
        guard ARWorldTrackingConfiguration.isSupported else {
            phase = .failed
            error = "Spatial tracking is unavailable on this device. You can import existing photos instead."
            return
        }
        Task {
            let allowed: Bool
            switch AVCaptureDevice.authorizationStatus(for: .video) {
            case .authorized: allowed = true
            case .notDetermined: allowed = await AVCaptureDevice.requestAccess(for: .video)
            default: allowed = false
            }
            guard phase == .preparing else { return }
            guard allowed else {
                phase = .failed
                error = "Camera access is off. Enable it in Settings, then try again. Existing captures are preserved."
                return
            }
            runSession(reset: true)
            phase = .detecting
        }
    }
    private func runSession(reset: Bool) {
        let configuration = ARWorldTrackingConfiguration()
        configuration.planeDetection = [.horizontal]
        configuration.isAutoFocusEnabled = true
        depthAvailable = ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth)
        if depthAvailable { configuration.frameSemantics.insert(.sceneDepth) }
        if let format = ARWorldTrackingConfiguration.supportedVideoFormats.first(where: {
            $0.framesPerSecond == 30 && $0.imageResolution.width >= 1920 && $0.imageResolution.width <= 2048
        }) { configuration.videoFormat = format }
        camera.session.run(configuration, options: reset ? [.resetTracking, .removeExistingAnchors] : [])
        configured = true
    }
    func pause() {
        guard phase == .detecting || phase == .scanning else { return }
        generation += 1
        camera.session.pause()
        phase = .paused
        instruction = "Scan paused. Return to the same view, then resume."
    }
    func resume() {
        guard configured, phase == .paused || phase == .review else { return }
        generation += 1
        previousPose = nil
        runSession(reset: false)
        phase = target == nil ? .detecting : .scanning
    }
    func finish() {
        guard phase == .scanning || phase == .paused else { return }
        generation += 1
        camera.session.pause()
        phase = .review
        instruction = coverage.complete ? "Your dish has been scanned." : "Some views are missing. You can scan only the missing areas."
        savePreview()
        onSaved?()
    }
    func stop() {
        generation += 1
        camera.session.pause()
        camera.session.delegate = nil
        onSaved?()
    }
    func sessionWasInterrupted(_ session: ARSession) { pause() }
    func session(_ session: ARSession, didFailWithError error: Error) {
        generation += 1
        phase = .failed
        self.error = error.localizedDescription
        onSaved?()
    }
    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        guard phase == .detecting || phase == .scanning, !analyzing,
              frame.timestamp - lastAnalysis >= 0.35 else { return }
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
            let screen = camera.projectPoint(SCNVector3(target))
            if screen.z < 0 || screen.z > 1 || !camera.bounds.insetBy(dx: camera.bounds.width * 0.15, dy: camera.bounds.height * 0.15).contains(CGPoint(x: CGFloat(screen.x), y: CGFloat(screen.y))) {
                instruction = "Keep the whole dish inside the frame."; return
            }
            let angle = atan2(Double(offset.x), Double(offset.z))
            let relative = angle - (startAngle ?? angle)
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
        lastAnalysis = frame.timestamp
        let ticket = generation
        let context = self.context
        processing.async { [weak self] in
            let result = Self.analyze(frame.capturedImage, context: context)
            DispatchQueue.main.async { [weak self] in
                guard let self else { return }
                self.analyzing = false
                guard self.generation == ticket, self.phase == .detecting || self.phase == .scanning else { return }
                self.consume(result, frame: frame, position: position)
            }
        }
    }
    nonisolated private static func analyze(_ buffer: CVPixelBuffer, context: CIContext) -> FrameAnalysis {
        autoreleasepool {
            let image = CIImage(cvPixelBuffer: buffer)
            let size = 96
            var pixels = [UInt8](repeating: 0, count: size * size)
            let scaled = image.transformed(by: CGAffineTransform(scaleX: CGFloat(size) / image.extent.width, y: CGFloat(size) / image.extent.height))
            context.render(scaled, toBitmap: &pixels, rowBytes: size, bounds: CGRect(x: 0, y: 0, width: size, height: size), format: .L8, colorSpace: CGColorSpaceCreateDeviceGray())
            var sum = 0.0, lap = 0.0, lapSquared = 0.0, clipped = 0.0, count = 0.0
            for y in 20..<76 { for x in 20..<76 {
                let p = y * size + x
                let v = Double(pixels[p])
                let l = 4 * v - Double(pixels[p-1]) - Double(pixels[p+1]) - Double(pixels[p-size]) - Double(pixels[p+size])
                sum += v; lap += l; lapSquared += l*l; count += 1
                if v < 8 || v > 248 { clipped += 1 }
            }}
            var result = FrameAnalysis(sharpness: lapSquared/count - pow(lap/count, 2), brightness: sum/count, clipped: clipped/count)
            // Segmentation locates foreground; it is not a food classifier or a depth estimate.
            let request = VNGenerateForegroundInstanceMaskRequest()
            let handler = VNImageRequestHandler(cvPixelBuffer: buffer, orientation: .up)
            do {
                try handler.perform([request])
                if let observation = request.results?.first {
                    let mask = observation.instanceMask
                    CVPixelBufferLockBaseAddress(mask, .readOnly)
                    defer { CVPixelBufferUnlockBaseAddress(mask, .readOnly) }
                    if let base = CVPixelBufferGetBaseAddress(mask)?.assumingMemoryBound(to: UInt8.self) {
                        let w = CVPixelBufferGetWidth(mask), h = CVPixelBufferGetHeight(mask), stride = CVPixelBufferGetBytesPerRow(mask)
                        let label = base[(h/2) * stride + w/2]
                        if label != 0 {
                            var minX = w, minY = h, maxX = 0, maxY = 0
                            for y in Swift.stride(from: 0, to: h, by: 2) { for x in Swift.stride(from: 0, to: w, by: 2) {
                                if base[y*stride+x] == label { minX = min(minX,x); maxX = max(maxX,x); minY = min(minY,y); maxY = max(maxY,y) }
                            }}
                            if maxX > minX && maxY > minY {
                                result.box = CGRect(x: Double(minX)/Double(w), y: Double(minY)/Double(h), width: Double(maxX-minX)/Double(w), height: Double(maxY-minY)/Double(h))
                            }
                        }
                    }
                }
            } catch { /* Detecting continues; never invent a target if segmentation failed. */ }
            if result.sharpness >= 35 && result.brightness > 25 && result.brightness < 230 && result.clipped < 0.45 && result.box != nil {
                // Camera pixels and intrinsics share the same native orientation. Retain full frame overlap.
                let scale = min(1, 1920 / image.extent.width)
                let export = image.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
                result.jpeg = context.jpegRepresentation(of: export, colorSpace: CGColorSpaceCreateDeviceRGB(), options: [CIImageRepresentationOption(rawValue: kCGImageDestinationLossyCompressionQuality as String): 0.9])
            }
            return result
        }
    }
    private func consume(_ result: FrameAnalysis, frame: ARFrame, position: SIMD3<Float>) {
        guard let box = result.box, box.width > 0.1, box.height > 0.1,
              box.minX > 0.02, box.minY > 0.02, box.maxX < 0.98, box.maxY < 0.98 else {
            instruction = "Center one dish and leave space around the plate."; return
        }
        if result.brightness <= 25 || result.brightness >= 230 || result.clipped >= 0.45 {
            instruction = "Use brighter, diffuse lighting. Avoid reflections."; return
        }
        guard result.sharpness >= 35, let jpeg = result.jpeg else { instruction = "Hold the phone steady for a moment."; return }
        if target == nil {
            let orientation = camera.window?.windowScene?.interfaceOrientation ?? .portrait
            let transform = frame.displayTransform(for: orientation, viewportSize: camera.bounds.size)
            let normalized = CGPoint(x: box.midX, y: box.midY).applying(transform)
            let pixel = CGPoint(x: normalized.x * camera.bounds.width, y: normalized.y * camera.bounds.height)
            guard let query = camera.raycastQuery(from: pixel, allowing: .estimatedPlane, alignment: .horizontal),
                  let hit = camera.session.raycast(query).first else {
                instruction = "Move gently so the camera can locate the table."; return
            }
            let center = SIMD3<Float>(hit.worldTransform.columns.3.x, hit.worldTransform.columns.3.y, hit.worldTransform.columns.3.z)
            if let candidate, simd_distance(candidate, center) < 0.045 { stableDetections += 1 } else { stableDetections = 0 }
            candidate = center
            guard stableDetections >= 2 else { instruction = "Dish located. Hold steady."; return }
            let distance = simd_distance(position, center)
            radius = min(0.28, max(0.10, Float(max(box.width, box.height)) * distance * 0.45))
            target = center
            startAngle = atan2(Double(position.x-center.x), Double(position.z-center.z))
            createOrbit(center)
            phase = .scanning
        }
        guard let target else { return }
        let offset = position-target
        let angle = atan2(Double(offset.x), Double(offset.z)) - (startAngle ?? 0)
        let elevation = atan2(Double(offset.y), Double(hypot(offset.x, offset.z)))
        guard elevation > 0.15, elevation < 1.35 else { instruction = "Keep the phone beside and slightly above the plate."; return }
        guard coverage.needs(angle: angle, elevation: elevation, time: frame.timestamp) else { return }
        do {
            let name = UUID().uuidString
            try jpeg.write(to: CaptureFiles.images(record).appendingPathComponent(name + ".jpg"), options: .atomic)
            let metadata: [String: Any] = ["schema": 1, "timestamp": frame.timestamp,
                "transform": (0..<4).flatMap { c in (0..<4).map { r in frame.camera.transform[c][r] } },
                "intrinsics": (0..<3).flatMap { c in (0..<3).map { r in frame.camera.intrinsics[c][r] } },
                "imageResolution": [frame.camera.imageResolution.width, frame.camera.imageResolution.height],
                "sharpness": result.sharpness, "angle": angle, "elevation": elevation, "metricScaleVerified": false]
            try JSONSerialization.data(withJSONObject: metadata).write(to: CaptureFiles.checkpoints(record).appendingPathComponent(name + ".json"), options: .atomic)
            coverage.accept(angle: angle, elevation: elevation, time: frame.timestamp)
            lastAcceptedPosition = position
            progress = coverage.progress
            updateOrbit()
            gatherPoints(frame, center: target)
            var current = record
            current.imageCount = CaptureFiles.photos(record).count
            current.state = "scanning"
            try CaptureFiles.save(current)
            let reached = Int(progress * 4)
            if reached > milestone { milestone = reached; UIImpactFeedbackGenerator(style: .light).impactOccurred() }
            instruction = coverage.covered >= 10 && coverage.upperViews < 4
                ? "Raise the phone slightly as you continue around the plate."
                : "Continue slowly around the unfilled arc."
            if coverage.complete { UINotificationFeedbackGenerator().notificationOccurred(.success); finish() }
        } catch { self.error = error.localizedDescription; pause() }
    }
    private func createOrbit(_ center: SIMD3<Float>) {
        targetNode.simdPosition = center
        camera.scene.rootNode.addChildNode(targetNode)
        for index in 0..<ScanCoverage.sectors {
            let angle = Float(index) / Float(ScanCoverage.sectors) * 2 * .pi + Float(startAngle ?? 0)
            let geometry = SCNSphere(radius: 0.009)
            geometry.segmentCount = 8
            geometry.firstMaterial?.lightingModel = .constant
            let node = SCNNode(geometry: geometry)
            node.position = SCNVector3(sin(angle) * radius * 1.5, 0.04 + Float(index) / Float(ScanCoverage.sectors) * 0.10, cos(angle) * radius * 1.5)
            orbitNodes.append(node)
            targetNode.addChildNode(node)
        }
        let volume = SCNCylinder(radius: CGFloat(radius), height: 0.18)
        volume.radialSegmentCount = 24
        volume.heightSegmentCount = 1
        volume.firstMaterial?.diffuse.contents = UIColor.white.withAlphaComponent(0.3)
        volume.firstMaterial?.fillMode = .lines
        volume.firstMaterial?.lightingModel = .constant
        let node = SCNNode(geometry: volume)
        node.position.y = 0.09
        targetNode.addChildNode(node)
        updateOrbit()
    }
    private func updateOrbit() {
        for (index, node) in orbitNodes.enumerated() {
            node.geometry?.firstMaterial?.diffuse.contents = coverage.elevations[index] == nil ? UIColor.white.withAlphaComponent(0.5) : UIColor.systemMint
        }
    }
    private func gatherPoints(_ frame: ARFrame, center: SIMD3<Float>) {
        func insert(_ point: SIMD3<Float>) {
            let local = point-center
            guard hypot(local.x, local.z) < radius, local.y > 0.006, local.y < 0.25 else { return }
            let key = "\(Int(local.x*250)),\(Int(local.y*250)),\(Int(local.z*250))"
            if points.count < 4000 || points[key] != nil { points[key] = local }
        }
        frame.rawFeaturePoints?.points.forEach(insert)
        if let depth = frame.sceneDepth {
            let map = depth.depthMap
            let confidence = depth.confidenceMap
            CVPixelBufferLockBaseAddress(map, .readOnly)
            if let confidence { CVPixelBufferLockBaseAddress(confidence, .readOnly) }
            defer {
                CVPixelBufferUnlockBaseAddress(map, .readOnly)
                if let confidence { CVPixelBufferUnlockBaseAddress(confidence, .readOnly) }
            }
            if let base = CVPixelBufferGetBaseAddress(map)?.assumingMemoryBound(to: Float.self) {
                let w = CVPixelBufferGetWidth(map), h = CVPixelBufferGetHeight(map), stride = CVPixelBufferGetBytesPerRow(map)/MemoryLayout<Float>.stride
                let sx = Float(frame.camera.imageResolution.width)/Float(w), sy = Float(frame.camera.imageResolution.height)/Float(h)
                let k = frame.camera.intrinsics
                let confidenceBase = confidence.flatMap { CVPixelBufferGetBaseAddress($0)?.assumingMemoryBound(to: UInt8.self) }
                let confidenceStride = confidence.map { CVPixelBufferGetBytesPerRow($0) } ?? 0
                for y in Swift.stride(from: 0, to: h, by: 5) { for x in Swift.stride(from: 0, to: w, by: 5) {
                    if let confidenceBase, confidenceBase[y*confidenceStride+x] < 1 { continue }
                    let z = base[y*stride+x]
                    guard z.isFinite, z > 0.1, z < 1.5 else { continue }
                    let local = SIMD4<Float>((Float(x)*sx-k[2][0])*z/k[0][0], -(Float(y)*sy-k[2][1])*z/k[1][1], -z, 1)
                    let world = frame.camera.transform * local
                    insert(SIMD3<Float>(world.x,world.y,world.z))
                }}
            }
        }
        guard !points.isEmpty else { return }
        let positions = points.values.map { SCNVector3($0) }
        let source = SCNGeometrySource(vertices: positions)
        let indices = Array(0..<UInt32(positions.count))
        let element = SCNGeometryElement(indices: indices, primitiveType: .point)
        element.pointSize = 3
        element.minimumPointScreenSpaceRadius = 1
        element.maximumPointScreenSpaceRadius = 4
        let geometry = SCNGeometry(sources: [source], elements: [element])
        geometry.firstMaterial?.diffuse.contents = UIColor.systemMint
        geometry.firstMaterial?.lightingModel = .constant
        pointNode.geometry = geometry
        previewHasPoints = true
    }
    private func savePreview() {
        // Real observed points remain separate from any final textured model.
        let values = points.values.map { [$0.x, $0.y, $0.z] }
        do {
            let data = try JSONSerialization.data(withJSONObject: ["schema": 1, "kind": "observed-points", "points": values, "coverage": progress, "finalModel": false])
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
    let onContinue: () -> Void
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @State private var help = false
    var body: some View {
        GeometryReader { proxy in
            VStack(spacing: 0) {
                ZStack(alignment: .top) {
                    ScanCameraView(scan: scan)
                    VStack {
                        HStack {
                            Button { dismiss() } label: { Image(systemName: "xmark").frame(width: 44, height: 44) }
                            Spacer()
                            Text("Scan your dish").font(.headline)
                            Spacer()
                            Button { help = true } label: { Image(systemName: "questionmark").frame(width: 44, height: 44) }
                        }
                        .background(.ultraThinMaterial, in: Capsule())
                        Spacer()
                        Image(systemName: scan.phase == .review ? "checkmark.circle" : "viewfinder").font(.system(size: 42, weight: .ultraLight))
                        Spacer()
                        Text(LocalizedStringKey(scan.instruction)).font(.title3.weight(.semibold)).multilineTextAlignment(.center)
                            .padding().background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 18))
                        if scan.phase == .scanning || scan.phase == .review {
                            HStack {
                                Text(scan.progress, format: .percent.precision(.fractionLength(0))).font(.title2.monospacedDigit())
                                Text("View coverage").font(.caption)
                            }.padding(8).background(.ultraThinMaterial, in: Capsule())
                        }
                    }.padding(18)
                }.frame(height: max(260, proxy.size.height * 0.61)).clipped()
                VStack(spacing: 8) {
                    HStack {
                        Text("Live 3D preview").font(.headline)
                        Spacer()
                        Text("Observed points · provisional").font(.caption).foregroundStyle(.secondary)
                    }
                    ZStack {
                        SceneView(scene: scan.preview, options: scan.phase == .review ? [.allowsCameraControl] : [])
                            .frame(maxHeight: .infinity)
                        if !scan.previewHasPoints {
                            Text("The first observations will appear here.").font(.caption).foregroundStyle(.secondary)
                        }
                    }.background(Color.black.opacity(0.04)).clipShape(RoundedRectangle(cornerRadius: 14))
                    if let error = scan.error { Text(LocalizedStringKey(error)).font(.caption).foregroundStyle(.red) }
                    controls
                }.padding(16).frame(maxHeight: .infinity)
            }
        }
        .background(Color(.systemBackground))
        .onAppear { scan.start() }
        .onDisappear { scan.stop() }
        .onChange(of: scenePhase) { _, value in if value != .active { scan.pause() } }
        .alert("One gentle orbit", isPresented: $help) {
            Button("OK", role: .cancel) {}
        } message: {
            Text("Keep the dish still and centered. Follow the unfilled arc, raising your phone gradually. Good views are saved automatically. The preview contains observed points; the final textured model is calculated after upload. Scan duration depends on coverage and image quality.")
        }
    }
    @ViewBuilder private var controls: some View {
        switch scan.phase {
        case .preparing: ProgressView("Preparing camera…")
        case .detecting: Text("Place one dish on a clear, well-lit table.").font(.caption)
        case .scanning:
            HStack {
                Button("Pause") { scan.pause() }.buttonStyle(.bordered)
                Button("Review scan") { scan.finish() }.buttonStyle(.bordered)
            }
        case .paused:
            Button("Resume scan") { scan.resume() }.buttonStyle(.borderedProminent)
        case .review:
            HStack {
                Button("Scan a missing area") { scan.resume() }.buttonStyle(.bordered)
                Button("Continue") { onContinue(); dismiss() }.buttonStyle(.borderedProminent)
                    .disabled(scan.coverage.accepted < 3)
            }
        case .failed:
            Button("Back to my dish") { dismiss() }.buttonStyle(.bordered)
        }
    }
}
