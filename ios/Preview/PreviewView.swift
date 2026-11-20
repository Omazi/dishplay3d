import MetalKit
import ScanCore
import SwiftUI
import simd

struct PreviewUniforms {
    var viewProj: simd_float4x4
    var lightDir: SIMD3<Float>
    var pointSize: Float
    var showMesh: UInt32
    var showProvenance: UInt32
}

enum PreviewMode: String, CaseIterable, Identifiable {
    case both = "Les deux", points = "Points", surface = "Surface"
    var id: String { rawValue }
}

/// Bottom panel: its own virtual camera orbiting the box centre on a neutral background.
@MainActor
final class PreviewRenderer: NSObject, MTKViewDelegate, ObservableObject {
    let device: MTLDevice
    private let queue: MTLCommandQueue
    private var points: PointCloudRenderer?
    private var mesh: MeshRenderer?
    private var depthState: MTLDepthStencilState?
    var mode: PreviewMode = .both
    var showTracking = true
    var boxSize = SIMD3<Float>(0.3, 0.1, 0.3)
    private var contentCentre: SIMD3<Float>?
    private var contentRadius: Float = 0
    private var viewCentre = SIMD3<Float>(0, 0.03, 0)
    private var viewRadius: Float = 0   // 0 until the first frame is drawn
    // orbit camera
    var yaw: Float = 0.6
    var pitch: Float = 0.6
    var distanceScale: Float = 1.0
    var lastInteraction = Date.distantPast
    /// During capture the virtual camera looks at the model from the phone's side, so the preview
    /// matches what the real camera sees. After the scan it turns slowly on its own.
    var followPhone = true
    private var targetYaw: Float?
    private var targetPitch: Float = 0.6
    private var lastDraw = CACurrentMediaTime()

    override init() {
        device = MTLCreateSystemDefaultDevice()!
        queue = device.makeCommandQueue()!
        super.init()
        let lib = device.makeDefaultLibrary()!
        points = try? PointCloudRenderer(device: device, library: lib, pixelFormat: .bgra8Unorm, depthFormat: .depth32Float)
        mesh = try? MeshRenderer(device: device, library: lib, pixelFormat: .bgra8Unorm, depthFormat: .depth32Float)
        let ds = MTLDepthStencilDescriptor()
        ds.depthCompareFunction = .less
        ds.isDepthWriteEnabled = true
        depthState = device.makeDepthStencilState(descriptor: ds)
    }

    func show(_ g: PreviewGeometry) {
        points?.update(g)
        mesh?.update(g)
        if let s = g.header.box_size_m, s.count == 3 { boxSize = SIMD3(Float(s[0]), Float(s[1]), Float(s[2])) }
        if let b = Self.bounds(of: g.vertexPositions, count: g.vertexCount) ?? Self.bounds(of: g.pointPositions, count: g.pointCount) {
            contentCentre = b.centre
            contentRadius = b.radius
        }
    }

    /// Centre and half-diagonal of the reconstructed content (2nd to 98th percentile on each axis, so a few stray
    /// points do not count). The scan box is often much larger than the dish: framed on the box, the finished
    /// dish looked tiny.
    private static func bounds(of data: Data, count: Int) -> (centre: SIMD3<Float>, radius: Float)? {
        guard count >= 10, data.count >= count * 12 else { return nil }
        let step = max(1, count / 3000)
        var xs: [Float] = [], ys: [Float] = [], zs: [Float] = []
        data.withUnsafeBytes { raw in
            var i = 0
            while i < count {
                let o = i * 12
                xs.append(raw.loadUnaligned(fromByteOffset: o, as: Float.self))
                ys.append(raw.loadUnaligned(fromByteOffset: o + 4, as: Float.self))
                zs.append(raw.loadUnaligned(fromByteOffset: o + 8, as: Float.self))
                i += step
            }
        }
        guard xs.count >= 4 else { return nil }
        xs.sort()
        ys.sort()
        zs.sort()
        let lo = Int(Float(xs.count - 1) * 0.02), hi = Int(Float(xs.count - 1) * 0.98)
        let low = SIMD3<Float>(xs[lo], ys[lo], zs[lo]), high = SIMD3<Float>(xs[hi], ys[hi], zs[hi])
        return ((low + high) / 2, simd_length(high - low) / 2)
    }

    func showTracking(_ pts: [SIMD3<Float>]) { points?.updateTracking(pts) }

    /// Unit vector from the box centre towards the phone, in the object frame.
    func follow(direction d: SIMD3<Float>) {
        targetYaw = atan2(d.x, d.z)
        targetPitch = min(1.45, max(0.15, asin(max(-1, min(1, d.y)))))
    }

    func mtkView(_ view: MTKView, drawableSizeWillChange size: CGSize) {}

    func draw(in view: MTKView) {
        let now = CACurrentMediaTime()
        let dt = Float(now - lastDraw)
        lastDraw = now
        if Date().timeIntervalSince(lastInteraction) > 3 {
            if followPhone, let ty = targetYaw {
                var dy = (ty - yaw).truncatingRemainder(dividingBy: 2 * .pi)
                if dy > .pi { dy -= 2 * .pi } else if dy < -.pi { dy += 2 * .pi }
                let k = min(1, dt * 4)
                yaw += dy * k
                pitch += (targetPitch - pitch) * k
            } else {
                yaw += dt * 0.25  // slow automatic turn when idle
            }
        }
        guard let pass = view.currentRenderPassDescriptor, let drawable = view.currentDrawable,
              let cmd = queue.makeCommandBuffer(), let enc = cmd.makeRenderCommandEncoder(descriptor: pass) else { return }
        let aspect = Float(view.drawableSize.width / max(view.drawableSize.height, 1))
        // During capture the view shows the whole scan box, as the camera does. Afterwards it frames what was
        // reconstructed, so the dish fills the view whatever the size of the box.
        let boxRadius = max(boxSize.x, boxSize.z) * 1.15 + boxSize.y
        var goalCentre = SIMD3<Float>(0, boxSize.y * 0.3, 0)
        var goalRadius = boxRadius
        if !followPhone, let c = contentCentre {
            goalCentre = c
            goalRadius = min(boxRadius, max(0.06, contentRadius * 2.4))
        }
        if viewRadius <= 0 {
            viewCentre = goalCentre
            viewRadius = goalRadius
        } else {
            let ease = min(1, dt * 3)
            viewCentre += (goalCentre - viewCentre) * ease
            viewRadius += (goalRadius - viewRadius) * ease
        }
        let radius = viewRadius * distanceScale
        let target = viewCentre
        let eye = target + radius * SIMD3(cos(pitch) * sin(yaw), sin(pitch), cos(pitch) * cos(yaw))
        let vp = perspective(fovy: 0.75, aspect: aspect, near: 0.01, far: 10) * lookAt(eye: eye, target: target, up: [0, 1, 0])
        var u = PreviewUniforms(viewProj: vp, lightDir: simd_normalize(SIMD3(0.3, 1.0, 0.4)),
                                pointSize: Float(view.contentScaleFactor) * 2.2, showMesh: mode == .points ? 0 : 1,
                                showProvenance: UserDefaults.standard.bool(forKey: "preview.showProvenance") ? 1 : 0)
        enc.setDepthStencilState(depthState)
        if mode != .points { mesh?.draw(enc, uniforms: &u) }
        if mode != .surface || (mesh?.indexCount ?? 0) == 0 { points?.draw(enc, uniforms: &u, showTracking: showTracking) }
        enc.endEncoding()
        cmd.present(drawable)
        cmd.commit()
    }

    private func perspective(fovy: Float, aspect: Float, near: Float, far: Float) -> simd_float4x4 {
        let y = 1 / tan(fovy * 0.5), x = y / aspect, z = far / (near - far)
        return simd_float4x4(columns: (SIMD4(x, 0, 0, 0), SIMD4(0, y, 0, 0), SIMD4(0, 0, z, -1), SIMD4(0, 0, z * near, 0)))
    }

    private func lookAt(eye: SIMD3<Float>, target: SIMD3<Float>, up: SIMD3<Float>) -> simd_float4x4 {
        let f = simd_normalize(target - eye)
        let s = simd_normalize(simd_cross(f, up))
        let v = simd_cross(s, f)
        return simd_float4x4(columns: (SIMD4(s.x, v.x, -f.x, 0), SIMD4(s.y, v.y, -f.y, 0), SIMD4(s.z, v.z, -f.z, 0),
                                       SIMD4(-simd_dot(s, eye), -simd_dot(v, eye), simd_dot(f, eye), 1)))
    }
}

struct PreviewView: UIViewRepresentable {
    let renderer: PreviewRenderer

    func makeUIView(context: Context) -> MTKView {
        let v = MTKView(frame: .zero, device: renderer.device)
        v.colorPixelFormat = .bgra8Unorm
        v.depthStencilPixelFormat = .depth32Float
        v.clearColor = MTLClearColor(red: 0.082, green: 0.086, blue: 0.075, alpha: 1)   // Theme.stage
        v.preferredFramesPerSecond = 30
        v.delegate = renderer
        v.addGestureRecognizer(UIPanGestureRecognizer(target: context.coordinator, action: #selector(Coordinator.pan(_:))))
        v.addGestureRecognizer(UIPinchGestureRecognizer(target: context.coordinator, action: #selector(Coordinator.pinch(_:))))
        return v
    }

    func updateUIView(_ uiView: MTKView, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator(renderer: renderer) }

    @MainActor
    final class Coordinator: NSObject {
        let renderer: PreviewRenderer
        init(renderer: PreviewRenderer) { self.renderer = renderer }

        @objc func pan(_ g: UIPanGestureRecognizer) {
            let t = g.translation(in: g.view)
            renderer.yaw -= Float(t.x) * 0.01
            renderer.pitch = min(1.45, max(-0.2, renderer.pitch + Float(t.y) * 0.01))
            renderer.lastInteraction = Date()
            g.setTranslation(.zero, in: g.view)
        }

        @objc func pinch(_ g: UIPinchGestureRecognizer) {
            renderer.distanceScale = min(3, max(0.3, renderer.distanceScale / Float(g.scale)))
            renderer.lastInteraction = Date()
            g.scale = 1
        }
    }
}
