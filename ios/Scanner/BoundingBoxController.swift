import ARKit
import Combine
import RealityKit
import ScanCore
import UIKit

/// The resizable capture box: tap the table to place it, drag the base disc to move it,
/// drag side handles for width/depth, the top handle for height, two-finger rotate for yaw.
/// Its base always stays on the chosen plane.
@MainActor
final class BoundingBoxController: NSObject, ObservableObject, UIGestureRecognizerDelegate {
    @Published private(set) var placed = false
    @Published var locked = false { didSet { rebuild() } }
    @Published var width: Float = 0.30 { didSet { clampAndRebuild() } }
    @Published var depth: Float = 0.30 { didSet { clampAndRebuild() } }
    @Published var height: Float = 0.10 { didSet { clampAndRebuild() } }
    @Published private(set) var yaw: Float = 0
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
        let rot = UIRotationGestureRecognizer(target: self, action: #selector(onRotate(_:)))
        let pinch = UIPinchGestureRecognizer(target: self, action: #selector(onPinch(_:)))
        for g in [tap, pan, rot, pinch] as [UIGestureRecognizer] { g.delegate = self; view.addGestureRecognizer(g) }
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
            // face the box towards the user
            let fwd = SIMD3<Float>(-cam.columns.2.x, 0, -cam.columns.2.z)
            yaw = atan2(fwd.x, fwd.z)
        }
        placed = true
        rebuild()
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

    @objc private func onRotate(_ g: UIRotationGestureRecognizer) {
        guard placed, !locked else { return }
        yaw -= Float(g.rotation)
        g.rotation = 0
        rebuild()
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
            case "h_+x": width = s.w + lx; shiftCentre(s.centre, along: SIMD3(c, 0, -sn), by: lx / 2)
            case "h_-x": width = s.w - lx; shiftCentre(s.centre, along: SIMD3(c, 0, -sn), by: lx / 2)
            case "h_+z": depth = s.d + lz; shiftCentre(s.centre, along: SIMD3(sn, 0, c), by: lz / 2)
            case "h_-z": depth = s.d - lz; shiftCentre(s.centre, along: SIMD3(sn, 0, c), by: lz / 2)
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

    private func shiftCentre(_ start: SIMD3<Float>, along axis: SIMD3<Float>, by d: Float) {
        // keep the opposite face fixed while resizing (only if the size is inside its limits)
        centre = start + axis * d
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
        let edge: UIColor = locked ? UIColor.systemGreen : UIColor.white
        let mat = UnlitMaterial(color: edge)
        let t: Float = 0.003
        let w = width, d = depth, h = height
        func bar(_ size: SIMD3<Float>, _ pos: SIMD3<Float>) {
            let e = ModelEntity(mesh: .generateBox(size: size), materials: [mat])
            e.position = pos
            root.addChild(e)
        }
        for y in [Float(0), h] {
            for z in [-d / 2, d / 2] { bar([w, t, t], [0, y, z]) }
            for x in [-w / 2, w / 2] { bar([t, t, d], [x, y, 0]) }
        }
        for x in [-w / 2, w / 2] { for z in [-d / 2, d / 2] { bar([t, h, t], [x, h / 2, z]) } }
        // Translucent footprint: shows exactly which part of the table is inside the box.
        var floorMat = UnlitMaterial(color: locked ? UIColor.systemGreen : UIColor.white)
        floorMat.blending = .transparent(opacity: 0.16)
        let floor = ModelEntity(mesh: .generatePlane(width: w, depth: d), materials: [floorMat])
        floor.position = [0, 0.001, 0]
        root.addChild(floor)
        guard !locked else { return }
        func handle(_ name: String, _ pos: SIMD3<Float>, _ color: UIColor) {
            let e = ModelEntity(mesh: .generateSphere(radius: 0.014), materials: [UnlitMaterial(color: color)])
            e.name = name
            e.position = pos
            e.collision = CollisionComponent(shapes: [.generateSphere(radius: 0.04)])
            root.addChild(e)
        }
        handle("h_+x", [w / 2, h / 2, 0], .systemOrange)
        handle("h_-x", [-w / 2, h / 2, 0], .systemOrange)
        handle("h_+z", [0, h / 2, d / 2], .systemTeal)
        handle("h_-z", [0, h / 2, -d / 2], .systemTeal)
        handle("h_top", [0, h, 0], .systemYellow)
        let disc = ModelEntity(mesh: .generatePlane(width: 0.05, depth: 0.05, cornerRadius: 0.025),
                               materials: [UnlitMaterial(color: UIColor.white.withAlphaComponent(0.8))])
        disc.name = "h_move"
        disc.position = [0, 0.002, 0]
        disc.collision = CollisionComponent(shapes: [.generateBox(size: [0.07, 0.02, 0.07])])
        root.addChild(disc)
    }
}
