import Foundation
import simd

@main struct ScanVolumeTests {
    static func check(_ value: Bool, _ message: String) { precondition(value, message) }
    static func main() {
        var box = ScanVolume(origin: SIMD3(0.2, 0, -0.8), size: SIMD3(0.4, 0.2, 0.1), yaw: .pi / 4)
        let local = SIMD3<Float>(0.15, 0.1, 0.02)
        check(simd_distance(box.local(box.world(local)), local) < 0.0001, "Rotated box transforms round-trip")
        check(box.contains(box.world(local)), "Observed points within the selected box are retained")
        check(!box.contains(box.world(SIMD3(0.21, 0.1, 0))), "Background outside width is excluded")
        check(!box.contains(box.world(SIMD3(0, -0.02, 0))), "Table underside is excluded")
        check(!box.contains(box.world(SIMD3(0, 0.3, 0))), "Objects above the selected height are excluded")
        let ratio = box.size.x / box.size.z
        box.scale(by: 100)
        check(box.size.x <= 0.8 && abs(box.size.x / box.size.z - ratio) < 0.0001, "Pinching preserves proportions at limits")
        box.scale(by: 0.001)
        check(box.size.z >= 0.0399, "Pinching cannot create a zero-sized volume")
        box.resize(axis: 1, to: .nan)
        check(box.size.y.isFinite, "Invalid gestures cannot poison geometry")
        let pose = matrix_identity_float4x4
        let intrinsics = simd_float3x3(columns: (SIMD3(100,0,0),SIMD3(0,100,0),SIMD3(100,100,1)))
        let projection = ScanProjection(cameraToWorld: pose, intrinsics: intrinsics, resolution: SIMD2(200,200))
        let subject = ScanVolume(origin: SIMD3(0,-0.1,-0.8), size: SIMD3(0.3,0.2,0.2))
        let polygon = subject.footprint(projection)
        check(polygon.count >= 4, "Selected box produces a camera-space outline")
        check(ScanVolume.inside(SIMD2(0.5,0.5), polygon: polygon), "Target center remains in the image mask")
        check(!ScanVolume.inside(SIMD2(0.01,0.01), polygon: polygon), "Outside pixels are excluded")
        check(ScanVolume(origin: SIMD3(0,0,1)).footprint(projection).isEmpty, "Box behind the camera cannot produce a valid mask")
        check(!ScanVolume.inside(SIMD2(0.5,0.5), polygon: []), "Missing tracking cannot create a full-frame mask")
        print("PASS: editable capture volume, rotation, containment, resize limits, camera footprint and masks")
    }
}
