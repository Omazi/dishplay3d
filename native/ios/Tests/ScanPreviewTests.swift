import Foundation
import simd

@main
struct ScanPreviewTests {
    static func require(_ condition: @autoclosure () -> Bool, _ message: String) {
        guard condition() else { fatalError(message) }
    }
    static let subject = SIMD3<Float>(0, 0.08, 0)
    static func projection(angle: Float) -> ScanProjection {
        let position = SIMD3<Float>(sin(angle)*0.5, 0.30, cos(angle)*0.5)
        let back = simd_normalize(position-subject)
        let right = simd_normalize(simd_cross(SIMD3<Float>(0,1,0),back))
        let up = simd_cross(back,right)
        let pose = simd_float4x4(columns: (SIMD4(right,0),SIMD4(up,0),SIMD4(back,0),SIMD4(position,1)))
        let k = simd_float3x3(columns: (SIMD3(80,0,0),SIMD3(0,80,0),SIMD3(32,32,1)))
        return ScanProjection(cameraToWorld: pose, intrinsics: k, resolution: SIMD2(64,64))
    }
    static func sphereMask(_ projection: ScanProjection) -> ScanRaster {
        let origin = projection.cameraToWorld.columns.3
        let center = SIMD3(origin.x,origin.y,origin.z)
        var mask = [UInt8](repeating: 0,count: 4096)
        var colors = [UInt8](repeating: 255,count: 4096*4)
        for y in 0..<64 { for x in 0..<64 {
            let cameraRay = SIMD4<Float>((Float(x)+0.5-32)/80, -(Float(y)+0.5-32)/80, -1, 0)
            let transformed = projection.cameraToWorld * cameraRay
            let ray = simd_normalize(SIMD3(transformed.x,transformed.y,transformed.z))
            let delta = center-subject
            let b = simd_dot(delta,ray)
            let discriminant = b*b - (simd_dot(delta,delta)-0.08*0.08)
            if discriminant >= 0 && -b > 0 { mask[y*64+x] = 1 }
            let i = (y*64+x)*4
            colors[i] = 90; colors[i+1] = 170; colors[i+2] = 60
        }}
        return ScanRaster(width: 64,height: 64,foreground: mask,rgba: colors)
    }
    static func main() {
        let first = projection(angle: 0)
        let center = first.project(subject)!
        require(simd_distance(center,SIMD2<Float>(0.5,0.5)) < 0.0001, "Camera pose and intrinsics must project the subject to the center")
        let upper = first.project(subject+SIMD3(0,0.02,0))!
        require(upper.y < center.y, "AR Y-up must map to top-left raster coordinates")
        require(first.project(SIMD3(0,0.5,2)) == nil, "Points behind the camera must be rejected")

        var hull = SilhouettePreview(center: .zero,radius: 0.15,minimumY: -0.025,maximumY: 0.22)
        require(hull.surface().positions.isEmpty, "An empty capture must not invent a model")
        for _ in 0..<10 { hull.integrate(sphereMask(first),projection: first) }
        require(hull.observations == 1 && hull.surface().positions.isEmpty, "One repeated mask is not a 3D reconstruction")
        for i in 1..<12 {
            let view = projection(angle: Float(i) * 2 * .pi / 12)
            hull.integrate(sphereMask(view),projection: view)
        }
        let surface = hull.surface(maximumPoints: 1200)
        require(hull.observations == 12, "Distinct valid camera poses must contribute")
        require(!surface.positions.isEmpty && surface.positions.count <= 1200, "A real multi-view hull must produce a bounded preview")
        require(surface.colors.count == surface.positions.count, "Every preview point must have observed color")
        require(surface.positions.allSatisfy { simd_length($0-subject) < 0.12 }, "The reconstructed silhouette must remain near the synthetic ground-truth sphere")
        require(surface.colors.allSatisfy { abs($0.y-Float(170)/255) < 0.001 }, "Colors must come from the source raster")

        var blank = SilhouettePreview(center: .zero,radius: 0.15)
        let empty = ScanRaster(width: 64,height: 64,foreground: [UInt8](repeating:0,count:4096),rgba:[UInt8](repeating:0,count:16384))
        let full = ScanRaster(width: 64,height: 64,foreground: [UInt8](repeating:1,count:4096),rgba:[UInt8](repeating:0,count:16384))
        for i in 0..<5 {
            blank.integrate(empty,projection: projection(angle: Float(i)))
            blank.integrate(full,projection: projection(angle: Float(i)))
        }
        require(blank.observations == 0 && blank.surface().positions.isEmpty, "Empty or whole-frame masks must not invent an object")
        print("Scan preview projection, measured pose, silhouette, color and memory-bound checks passed")
    }
}
