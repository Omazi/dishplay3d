import ARKit
import Combine
import RealityKit
import ScanCore
import UIKit

/// The resizable capture box: tap the table to place it, drag the base disc to move it,
/// drag side handles for width/depth, the top handle for height, pinch to scale; rotation is a slider.
/// Its base always stays on the chosen plane.
@MainActor
final class BoundingBoxController: NSObject, ObservableObject, UIGestureRecognizerDelegate {
    @Published private(set) var placed = false
    @Published var locked = false { didSet { rebuild() } }
    @Published var width: Float = 0.30 { didSet { clampAndRebuild() } }
    @Published var depth: Float = 0.30 { didSet { clampAndRebuild() } }
    @Published var height: Float = 0.10 { didSet { clampAndRebuild() } }
    @Published private(set) var yaw: Float = 0
    private var placedYaw: Float = 0
    @Published private(set) var planeSource = ""
    private(set) var centre = SIMD3<Float>(0, 0, 0)  // centre of the base, world coordinates

    private weak var arView: ARView?
    private let anchor = AnchorEntity(world: .zero)
    private let root = Entity()
    private var dragging: String?
    private var dragStart: (centre: SIMD3<Float>, w: Float, d: Float, h: Float, hit: SIMD3<Float>)?
    private var updating = false

    static let minSide: Float = 0.05, maxSide: Float = 0.8, minHeight: Float = 0.01, maxHeight: Float = 0.4

    func attach(to view: ARView) {
        arView = view
        anchor.addChild(root)
        view.scene.addAnchor(anchor)
        let tap = UITapGestureRecognizer(target: self, action: #selector(onTap(_:)))
        let pan = UIPanGestureRecognizer(target: self, action: #selector(onPan(_:)))
        pan.maximumNumberOfTouches = 1
        // No two-finger rotation gesture: it competed with the pinch and turned the box when the user
        // wanted to resize it. Rotation is an explicit control (yawDegrees).
        let pinch = UIPinchGestureRecognizer(target: self, action: #selector(onPinch(_:)))
        for g in [tap, pan, pinch] as [UIGestureRecognizer] { g.delegate = self; view.addGestureRecognizer(g) }
    }

    func gestureRecognizer(_ g: UIGestureRecognizer, shouldRecognizeSimultaneouslyWith other: UIGestureRecognizer) -> Bool { false }

    var worldFromObject: Mat4 {
        Mat4.yawTranslation(yaw: Double(yaw), x: Double(centre.x), y: Double(centre.y), z: Double(centre.z))
    }

    func spec(epoch: Int, revision: Int) -> BoxSpec {
        BoxSpec(worldFromObject: worldFromObject, size: .init(width: Double(width), height: Double(height), depth: Double(depth)),
                epoch: epoch, revision: revision, plane: planeSource)
    }

    func reset() {
        placed = false
        locked = false
        root.children.removeAll()
    }

    // MARK: gestures

    @objc private func onTap(_ g: UITapGestureRecognizer) {
        guard !locked, !placed, let view = arView else { return }
        let p = g.location(in: view)
        let results = view.raycast(from: p, allowing: .existingPlaneGeometry, alignment: .horizontal)
        let hit = results.first ?? view.raycast(from: p, allowing: .estimatedPlane, alignment: .horizontal).first
        guard let hit else { return }
        planeSource = results.first != nil ? "arkit_horizontal_plane" : "arkit_estimated_plane"
        let t = hit.worldTransform.columns.3
        centre = SIMD3(t.x, t.y, t.z)
        if let cam = view.session.currentFrame?.camera.transform {
            // Face the box towards the user. The viewing direction (-z) alone is ill-defined when the phone
            // points straight down; the top of the portrait screen (-x of the ARKit camera) completes it.
            let dir = -cam.columns.2 - cam.columns.0
            let h = SIMD2<Float>(dir.x, dir.z)
            if simd_length(h) > 1e-3 { yaw = atan2(h.x, h.y) }
            placedYaw = yaw
        }
        placed = true
        rebuild()
        Haptics.tap(.medium)
    }

    /// Two-finger pinch: grow or shrink width and depth together.
    @objc private func onPinch(_ g: UIPinchGestureRecognizer) {
        guard placed, !locked else { return }
        let k = Float(g.scale)
        g.scale = 1
        updating = true
        width *= k
        depth *= k
        updating = false
        clampAndRebuild()
    }

    /// Remove the box so the next tap places it again.
    func replace() {
        guard !locked else { return }
        placed = false
        root.children.removeAll()
    }

    /// Rotation of the box on the table, in degrees, relative to how it was placed (facing the user).
    var yawDegrees: Float {
        get { (yaw - placedYaw) * 180 / .pi }
        set {
            guard placed, !locked else { return }
            yaw = placedYaw + newValue * .pi / 180
            rebuild()
        }
    }

    @objc private func onPan(_ g: UIPanGestureRecognizer) {
        guard placed, !locked, let view = arView else { return }
        let p = g.location(in: view)
        switch g.state {
        case .began:
            dragging = view.entity(at: p).flatMap { e -> String? in
                var cur: Entity? = e
                while let c = cur { if c.name.hasPrefix("h_") { return c.name }; cur = c.parent }
                return nil
            }
            if dragging != nil { Haptics.tap(.light) }  // a knob was caught
            if dragging == nil { dragging = "h_move" }  // anywhere else: slide the whole box on the table
            if let name = dragging, let hit = hitPoint(p, handle: name) {
                dragStart = (centre, width, depth, height, hit)
            } else { dragging = nil }
        case .changed:
            guard let name = dragging, let s = dragStart, let hit = hitPoint(p, handle: name) else { return }
            let delta = hit - s.hit
            // express the drag in the box frame (x = width axis, z = depth axis)
            let c = cos(yaw), sn = sin(yaw)
            let lx = c * delta.x - sn * delta.z
            let lz = sn * delta.x + c * delta.z
            updating = true
            switch name {
            case "h_move": centre = SIMD3(s.centre.x + delta.x, s.centre.y, s.centre.z + delta.z)
            // The opposite face stays fixed: the centre moves by half of the size actually applied (after limits).
            case "h_+x": width = Self.side(s.w + lx); centre = s.centre + SIMD3(c, 0, -sn) * ((width - s.w) / 2)
            case "h_-x": width = Self.side(s.w - lx); centre = s.centre - SIMD3(c, 0, -sn) * ((width - s.w) / 2)
            case "h_+z": depth = Self.side(s.d + lz); centre = s.centre + SIMD3(sn, 0, c) * ((depth - s.d) / 2)
            case "h_-z": depth = Self.side(s.d - lz); centre = s.centre - SIMD3(sn, 0, c) * ((depth - s.d) / 2)
            case "h_top": height = s.h + delta.y
            default: break
            }
            updating = false
            clampAndRebuild()
        default:
            dragging = nil
            dragStart = nil
        }
    }

    private static func side(_ v: Float) -> Float { min(max(v, minSide), maxSide) }

    /// World transform of the box frame (origin at the centre of the base, +y up).
    var worldTransform: simd_float4x4 {
        Transform(scale: .one, rotation: simd_quatf(angle: yaw, axis: [0, 1, 0]), translation: centre).matrix
    }

    /// While locked, the drawn box follows the ARKit anchor (map corrections), not a frozen world pose.
    func follow(anchorTransform t: simd_float4x4) {
        guard locked else { return }
        anchor.transform = Transform(matrix: t)
    }

    /// Geometry of the box at one moment, to undo an edit.
    struct Saved { let centre: SIMD3<Float>; let yaw: Float; let placedYaw: Float; let width: Float; let depth: Float; let height: Float }

    func save() -> Saved { Saved(centre: centre, yaw: yaw, placedYaw: placedYaw, width: width, depth: depth, height: height) }

    func restore(_ s: Saved) {
        centre = s.centre
        yaw = s.yaw
        placedYaw = s.placedYaw
        width = s.width
        depth = s.depth
        height = s.height
        rebuild()
    }

    /// When unlocking for a revision, continue from where the anchored box is drawn now.
    func adopt(anchorTransform t: simd_float4x4) {
        centre = SIMD3(t.columns.3.x, t.columns.3.y, t.columns.3.z)
        let keep = yaw - placedYaw
        yaw = atan2(t.columns.2.x, t.columns.2.z)
        placedYaw = yaw - keep
    }

    /// Drag point: on the table plane for moves/width/depth, on a vertical plane facing the camera for height.
    private func hitPoint(_ p: CGPoint, handle: String) -> SIMD3<Float>? {
        guard let view = arView, let ray = view.ray(through: p) else { return nil }
        if handle == "h_top" {
            guard let cam = view.session.currentFrame?.camera.transform else { return nil }
            var n = SIMD3<Float>(cam.columns.2.x, 0, cam.columns.2.z)
            if simd_length(n) < 1e-3 { return nil }
            n = simd_normalize(n)
            let denom = simd_dot(ray.direction, n)
            if abs(denom) < 1e-4 { return nil }
            let t = simd_dot(centre - ray.origin, n) / denom
            return t > 0 ? ray.origin + ray.direction * t : nil
        }
        let denom = ray.direction.y
        if abs(denom) < 1e-4 { return nil }
        let t = (centre.y - ray.origin.y) / denom
        return t > 0 ? ray.origin + ray.direction * t : nil
    }

    private func clampAndRebuild() {
        let w = min(max(width, Self.minSide), Self.maxSide)
        let d = min(max(depth, Self.minSide), Self.maxSide)
        let h = min(max(height, Self.minHeight), Self.maxHeight)
        if w != width { width = w; return }
        if d != depth { depth = d; return }
        if h != height { height = h; return }
        if !updating { rebuild() }
    }

    // MARK: entities

    private func rebuild() {
        root.children.removeAll()
        guard placed else { return }
        anchor.transform = Transform(scale: .one, rotation: simd_quatf(angle: yaw, axis: [0, 1, 0]), translation: centre)
        let tint: UIColor = locked ? UIColor(red: 0.30, green: 0.85, blue: 0.55, alpha: 1) : .white
        let w = width, d = depth, h = height
        func bar(_ size: SIMD3<Float>, _ pos: SIMD3<Float>, _ mat: UnlitMaterial) {
            let e = ModelEntity(mesh: .generateBox(size: size), materials: [mat])
            e.position = pos
            root.addChild(e)
        }
        // Soft full edges: the volume reads as a box without hiding the dish.
        var soft = UnlitMaterial(color: tint)
        soft.blending = .transparent(opacity: 0.38)
        let t: Float = 0.002
        let xs: [Float] = [-w / 2, w / 2]
        let zs: [Float] = [-d / 2, d / 2]
        for y in [Float(0), h] {
            for z in zs { bar(SIMD3<Float>(w, t, t), SIMD3<Float>(0, y, z), soft) }
            for x in xs { bar(SIMD3<Float>(t, t, d), SIMD3<Float>(x, y, 0), soft) }
        }
        for x in xs { for z in zs { bar(SIMD3<Float>(t, h, t), SIMD3<Float>(x, h / 2, z), soft) } }
        // Bright corner brackets carry the shape, like a camera frame.
        let solid = UnlitMaterial(color: tint)
        let k: Float = 0.005
        let lx = min(0.035, w * 0.22), lz = min(0.035, d * 0.22), ly = min(0.03, h * 0.4)
        for sx in [Float(-1), 1] {
            for sz in [Float(-1), 1] {
                for y in [Float(0), h] {
                    let cx: Float = sx * w / 2
                    let cz: Float = sz * d / 2
                    let up: Float = y == 0 ? 1 : -1
                    let px = SIMD3<Float>(cx - sx * lx / 2, y, cz)
                    let pz = SIMD3<Float>(cx, y, cz - sz * lz / 2)
                    let py = SIMD3<Float>(cx, y + up * ly / 2, cz)
                    bar(SIMD3<Float>(lx, k, k), px, solid)
                    bar(SIMD3<Float>(k, k, lz), pz, solid)
                    bar(SIMD3<Float>(k, ly, k), py, solid)
                }
            }
        }
        // Translucent footprint: shows exactly which part of the table is inside the box.
        var floorMat = UnlitMaterial(color: tint)
        floorMat.blending = .transparent(opacity: 0.12)
        let floor = ModelEntity(mesh: .generatePlane(width: w, depth: d), materials: [floorMat])
        floor.position = [0, 0.001, 0]
        root.addChild(floor)
        guard !locked else { return }
        // Centre mark (the whole box moves by dragging anywhere).
        var faint = UnlitMaterial(color: .white)
        faint.blending = .transparent(opacity: 0.7)
        bar(SIMD3<Float>(0.03, 0.001, 0.003), SIMD3<Float>(0, 0.002, 0), faint)
        bar(SIMD3<Float>(0.003, 0.001, 0.03), SIMD3<Float>(0, 0.002, 0), faint)
        // Knobs: one look for all, white with an accent halo. Sides resize, the top one sets the height.
        var halo = UnlitMaterial(color: UIColor(red: 1.0, green: 0.58, blue: 0.22, alpha: 1))
        halo.blending = .transparent(opacity: 0.35)
        func handle(_ name: String, _ pos: SIMD3<Float>) {
            let e = ModelEntity(mesh: .generateSphere(radius: 0.010), materials: [UnlitMaterial(color: .white)])
            e.name = name
            e.position = pos
            e.collision = CollisionComponent(shapes: [.generateSphere(radius: 0.04)])
            e.addChild(ModelEntity(mesh: .generateSphere(radius: 0.017), materials: [halo]))
            root.addChild(e)
        }
        handle("h_+x", [w / 2, h / 2, 0])
        handle("h_-x", [-w / 2, h / 2, 0])
        handle("h_+z", [0, h / 2, d / 2])
        handle("h_-z", [0, h / 2, -d / 2])
        handle("h_top", [0, h, 0])
    }
}
