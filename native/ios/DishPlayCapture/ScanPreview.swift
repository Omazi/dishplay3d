import Foundation
import simd

/// Small, top-left-origin rasters in the camera sensor's native orientation.
struct ScanRaster: Sendable {
    let width: Int
    let height: Int
    let foreground: [UInt8]
    let rgba: [UInt8]

    func sample(_ uv: SIMD2<Float>) -> (inside: Bool, color: SIMD3<Float>)? {
        guard width > 0, height > 0, uv.x.isFinite, uv.y.isFinite, uv.x >= 0, uv.y >= 0, uv.x < 1, uv.y < 1,
              foreground.count == width * height, rgba.count == width * height * 4 else { return nil }
        let index = min(height-1, Int(uv.y * Float(height))) * width + min(width-1, Int(uv.x * Float(width)))
        return (foreground[index] > 0, SIMD3(Float(rgba[index*4]), Float(rgba[index*4+1]), Float(rgba[index*4+2])) / 255)
    }
}

struct ScanProjection: Sendable {
    let cameraToWorld: simd_float4x4
    let intrinsics: simd_float3x3
    let resolution: SIMD2<Float>

    func project(_ world: SIMD3<Float>) -> SIMD2<Float>? {
        projectCamera(simd_inverse(cameraToWorld) * SIMD4(world, 1))
    }
    func projectCamera(_ point: SIMD4<Float>) -> SIMD2<Float>? {
        guard point.z < -0.02, resolution.x > 0, resolution.y > 0 else { return nil }
        return SIMD2(intrinsics[0][0] * point.x / -point.z + intrinsics[2][0],
                     intrinsics[2][1] - intrinsics[1][1] * point.y / -point.z) / resolution
    }
}

struct ScanPreviewPoints: Sendable {
    var positions: [SIMD3<Float>] = []
    var colors: [SIMD3<Float>] = []
}

/// A soft visual hull from real foreground masks and AR camera poses.
/// This is a bounded silhouette estimate, not measured depth, final geometry or metric calibration.
struct SilhouettePreview: Sendable {
    static let side = 32
    let center: SIMD3<Float>
    let radius: Float
    let minimumY: Float
    let maximumY: Float
    private let volume: ScanVolume?
    private var support = [UInt8](repeating: 0, count: side * side * side)
    private var rejected = [UInt8](repeating: 0, count: side * side * side)
    private var colorSums = [SIMD3<Float>](repeating: .zero, count: side * side * side)
    private var acceptedPoses: [SIMD3<Float>] = []
    private(set) var observations = 0

    init(center: SIMD3<Float>, radius: Float, minimumY: Float = -0.025, maximumY: Float = 0.24) {
        self.center = center
        self.radius = max(0.06, min(0.35, radius))
        self.minimumY = minimumY
        self.maximumY = maximumY
        self.volume = nil
    }
    init(volume: ScanVolume) {
        self.center = volume.origin
        self.radius = volume.radius
        self.minimumY = -0.005
        self.maximumY = volume.size.y
        self.volume = volume
    }
    private func local(_ x: Int, _ y: Int, _ z: Int) -> SIMD3<Float> {
        if let volume {
            let p = SIMD3((Float(x)+0.5)/Float(Self.side) * volume.size.x-volume.size.x/2,
                          minimumY + (Float(y)+0.5)/Float(Self.side) * (maximumY-minimumY),
                          (Float(z)+0.5)/Float(Self.side) * volume.size.z-volume.size.z/2)
            return volume.world(p) - center
        }
        return SIMD3((Float(x)+0.5)/Float(Self.side) * 2 * radius-radius,
              minimumY + (Float(y)+0.5)/Float(Self.side) * (maximumY-minimumY),
              (Float(z)+0.5)/Float(Self.side) * 2 * radius-radius)
    }
    private func index(_ x: Int, _ y: Int, _ z: Int) -> Int { (y * Self.side + z) * Self.side + x }

    mutating func integrate(_ raster: ScanRaster, projection: ScanProjection) {
        guard raster.width > 0, raster.height > 0, raster.foreground.count == raster.width * raster.height,
              raster.rgba.count == raster.width * raster.height * 4 else { return }
        let visible = raster.foreground.filter { $0 > 0 }.count
        guard visible > raster.foreground.count / 100, visible < raster.foreground.count * 9 / 10 else { return }
        guard let centerUV = projection.project(volume?.center ?? (center + SIMD3(0, 0.04, 0))),
              raster.sample(centerUV)?.inside == true else { return }
        let origin = projection.cameraToWorld.columns.3
        let cameraPosition = SIMD3(origin.x, origin.y, origin.z)
        // Replaying one view must not strengthen the estimate or turn an initial mask into a model.
        guard acceptedPoses.allSatisfy({ simd_distance($0, cameraPosition) >= 0.025 }), observations < 24 else { return }
        let inverse = simd_inverse(projection.cameraToWorld)
        var observed = 0
        for y in 0..<Self.side { for z in 0..<Self.side { for x in 0..<Self.side {
            let point = local(x, y, z)
            guard (volume != nil || point.x * point.x + point.z * point.z <= radius * radius),
                  let uv = projection.projectCamera(inverse * SIMD4(center + point, 1)),
                  let sample = raster.sample(uv) else { continue }
            let i = index(x, y, z)
            if sample.inside {
                support[i] = min(24, support[i] + 1)
                colorSums[i] += sample.color
                observed += 1
            } else {
                rejected[i] = min(24, rejected[i] + 1)
            }
        }}}
        if observed > 0 { observations += 1; acceptedPoses.append(cameraPosition) }
    }
    func surface(maximumPoints: Int = 4000) -> ScanPreviewPoints {
        guard observations >= 3, maximumPoints > 0 else { return ScanPreviewPoints() }
        func occupied(_ x: Int, _ y: Int, _ z: Int) -> Bool {
            guard x >= 0, y >= 0, z >= 0, x < Self.side, y < Self.side, z < Self.side else { return false }
            let i = index(x,y,z)
            return support[i] >= 2 && rejected[i] <= 1
        }
        var boundary: [Int] = []
        for y in 0..<Self.side { for z in 0..<Self.side { for x in 0..<Self.side {
            guard occupied(x,y,z) else { continue }
            if !occupied(x-1,y,z) || !occupied(x+1,y,z) || !occupied(x,y-1,z) || !occupied(x,y+1,z) || !occupied(x,y,z-1) || !occupied(x,y,z+1) {
                boundary.append(index(x,y,z))
            }
        }}}
        var result = ScanPreviewPoints()
        let step = max(1, Int(ceil(Double(boundary.count) / Double(maximumPoints))))
        for offset in stride(from: 0, to: boundary.count, by: step) {
            let i = boundary[offset]
            let x = i % Self.side, z = (i / Self.side) % Self.side, y = i / (Self.side * Self.side)
            result.positions.append(local(x,y,z))
            result.colors.append(colorSums[i] / Float(max(1, support[i])))
        }
        return result
    }
}
