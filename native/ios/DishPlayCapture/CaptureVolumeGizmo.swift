import ARKit
import SceneKit
import UIKit
import simd

/// Editable world-anchored selection. These lines are controls, never reconstructed geometry.
@MainActor
final class CaptureVolumeGizmo: NSObject, UIGestureRecognizerDelegate {
    private weak var camera: ARSCNView?
    private let root = SCNNode()
    private var volume: ScanVolume?
    private var dragStart: ScanVolume?
    private var dragAxis: Int?
    private var screenAxis = SIMD2<Float>.zero
    private var dragOrigin: SIMD3<Float>?
    var enabled = false
    var onChange: ((ScanVolume) -> Void)?

    init(camera: ARSCNView) {
        self.camera = camera
        super.init()
        camera.scene.rootNode.addChildNode(root)
        let gestures: [UIGestureRecognizer] = [
            UIPinchGestureRecognizer(target: self, action: #selector(pinch(_:))),
            UIRotationGestureRecognizer(target: self, action: #selector(rotate(_:))),
            UIPanGestureRecognizer(target: self, action: #selector(pan(_:))),
            UITapGestureRecognizer(target: self, action: #selector(tap(_:)))
        ]
        for gesture in gestures { gesture.delegate = self; camera.addGestureRecognizer(gesture) }
    }

    func display(_ volume: ScanVolume?, editable: Bool) {
        self.volume = volume; enabled = editable
        root.childNodes.forEach { $0.removeFromParentNode() }
        guard let volume else { return }
        let corners = volume.corners
        for i in 0..<8 { for bit in [1, 2, 4] where i & bit == 0 {
            let a = corners[i], b = corners[i | bit]
            let line = SCNCylinder(radius: 0.0012, height: CGFloat(simd_distance(a, b)))
            line.radialSegmentCount = 5
            line.firstMaterial?.lightingModel = .constant
            line.firstMaterial?.diffuse.contents = editable ? UIColor.white : UIColor.systemMint.withAlphaComponent(0.65)
            let node = SCNNode(geometry: line)
            node.simdPosition = (a + b) / 2
            node.simdOrientation = simd_quatf(from: SIMD3<Float>(0, 1, 0), to: simd_normalize(b - a))
            root.addChildNode(node)
        }}
        guard editable else { return }
        for axis in 0..<3 {
            for sign in [Float(-1), Float(1)] {
                var p = SIMD3<Float>(0, volume.size.y / 2, 0)
                p[axis] = axis == 1 ? (sign > 0 ? volume.size.y : 0) : sign * volume.size[axis] / 2
                let sphere = SCNSphere(radius: 0.012)
                sphere.segmentCount = 10
                sphere.firstMaterial?.lightingModel = .constant
                sphere.firstMaterial?.diffuse.contents = UIColor.white
                let handle = SCNNode(geometry: sphere)
                handle.simdPosition = volume.world(p)
                handle.name = "resize-\(axis == 1 && sign < 0 ? 3 : axis)"
                root.addChildNode(handle)
            }
        }
    }

    func gestureRecognizerShouldBegin(_ gestureRecognizer: UIGestureRecognizer) -> Bool { enabled }

    @objc private func pinch(_ gesture: UIPinchGestureRecognizer) {
        guard enabled, var next = volume else { return }
        next.scale(by: Float(gesture.scale)); gesture.scale = 1
        onChange?(next)
    }
    @objc private func rotate(_ gesture: UIRotationGestureRecognizer) {
        guard enabled, var next = volume else { return }
        next.yaw -= Float(gesture.rotation); gesture.rotation = 0
        onChange?(next)
    }
    private func pointOnBase(_ pixel: CGPoint, volume: ScanVolume) -> SIMD3<Float>? {
        guard let camera, let frame = camera.session.currentFrame else { return nil }
        let c = frame.camera.transform.columns.3
        let origin = SIMD3(c.x, c.y, c.z)
        let far = camera.unprojectPoint(SCNVector3(Float(pixel.x), Float(pixel.y), 1))
        let ray = SIMD3<Float>(far.x, far.y, far.z) - origin
        guard abs(ray.y) > 0.0001 else { return nil }
        let t = (volume.origin.y - origin.y) / ray.y
        let result = origin + ray * t
        guard t > 0, simd_distance(result, origin) < 2 else { return nil }
        return result
    }
    @objc private func tap(_ gesture: UITapGestureRecognizer) {
        guard enabled, let camera, var next = volume,
              let point = pointOnBase(gesture.location(in: camera), volume: next) else { return }
        next.origin = point
        onChange?(next)
    }
    @objc private func pan(_ gesture: UIPanGestureRecognizer) {
        guard enabled, let camera, let volume else { return }
        if gesture.state == .began {
            dragStart = volume; dragAxis = nil
            dragOrigin = pointOnBase(gesture.location(in: camera), volume: volume)
            // A generous screen-space touch target makes the small 3D handles usable on a phone.
            let location = gesture.location(in: camera)
            let handles = root.childNodes.filter { $0.name?.hasPrefix("resize-") == true }
            if let handle = handles.min(by: {
                let a = camera.projectPoint($0.position), b = camera.projectPoint($1.position)
                return hypot(CGFloat(a.x)-location.x, CGFloat(a.y)-location.y) < hypot(CGFloat(b.x)-location.x, CGFloat(b.y)-location.y)
            }) {
                let a = camera.projectPoint(handle.position)
                if a.z > 0, a.z < 1, hypot(CGFloat(a.x)-location.x, CGFloat(a.y)-location.y) < 36,
                   let axis = Int(handle.name!.dropFirst(7)) {
                    let direction = simd_normalize(handle.simdPosition - volume.center)
                    let b = camera.projectPoint(SCNVector3(handle.simdPosition + direction * 0.03))
                    screenAxis = SIMD2(b.x-a.x, b.y-a.y) / 0.03
                    if simd_length(screenAxis) > 25 { dragAxis = axis }
                }
            }
        }
        guard var next = dragStart else { return }
        if let axis = dragAxis {
            let translation = gesture.translation(in: camera)
            let movement = simd_dot(SIMD2(Float(translation.x), Float(translation.y)), screenAxis) / simd_length_squared(screenAxis)
            if axis == 3 {
                let top = next.origin.y + next.size.y
                next.resize(axis: 1, to: next.size.y + movement)
                next.origin.y = top - next.size.y
            } else {
                next.resize(axis: axis, to: next.size[axis] + movement * (axis == 1 ? 1 : 2))
            }
        } else if let start = dragOrigin, let current = pointOnBase(gesture.location(in: camera), volume: next) {
            next.origin += current - start
        }
        onChange?(next)
        if gesture.state == .ended || gesture.state == .cancelled { dragStart = nil; dragOrigin = nil }
    }
}
