import Foundation
import simd

/// A user-selected box on the table. Dimensions are AR estimates, not verified scale.
struct ScanVolume: Sendable {
    var origin: SIMD3<Float>
    private(set) var size: SIMD3<Float>
    var yaw: Float

    init(origin: SIMD3<Float>, size: SIMD3<Float> = SIMD3(0.30, 0.20, 0.30), yaw: Float = 0) {
        self.origin = origin
        self.size = SIMD3(Self.bounded(size.x), Self.bounded(size.y), Self.bounded(size.z))
        self.yaw = yaw.isFinite ? yaw : 0
    }
    private static func bounded(_ value: Float) -> Float { value.isFinite ? min(0.8, max(0.04, value)) : 0.2 }
    mutating func resize(axis: Int, to value: Float) {
        guard (0..<3).contains(axis) else { return }
        size[axis] = Self.bounded(value)
    }
    mutating func scale(by factor: Float) {
        guard factor.isFinite, factor > 0 else { return }
        // Preserve proportions when one dimension reaches the limit.
        let minimum = max(0.04 / size.x, 0.04 / size.y, 0.04 / size.z)
        let maximum = min(0.8 / size.x, 0.8 / size.y, 0.8 / size.z)
        size *= min(maximum, max(minimum, factor))
    }
    func world(_ local: SIMD3<Float>) -> SIMD3<Float> {
        origin + SIMD3(cos(yaw) * local.x + sin(yaw) * local.z, local.y,
                       -sin(yaw) * local.x + cos(yaw) * local.z)
    }
    func local(_ world: SIMD3<Float>) -> SIMD3<Float> {
        let p = world - origin
        return SIMD3(cos(yaw) * p.x - sin(yaw) * p.z, p.y, sin(yaw) * p.x + cos(yaw) * p.z)
    }
    func contains(_ point: SIMD3<Float>) -> Bool {
        let p = local(point)
        return p.x.isFinite && p.y.isFinite && p.z.isFinite && abs(p.x) <= size.x / 2 &&
            abs(p.z) <= size.z / 2 && p.y >= -0.005 && p.y <= size.y
    }
    var corners: [SIMD3<Float>] {
        (0..<8).map { i in world(SIMD3(i & 1 == 0 ? -size.x / 2 : size.x / 2,
                                      i & 2 == 0 ? 0 : size.y,
                                      i & 4 == 0 ? -size.z / 2 : size.z / 2)) }
    }
    var center: SIMD3<Float> { world(SIMD3(0, size.y / 2, 0)) }
    var radius: Float { hypot(size.x, size.z) / 2 }

    /// Convex image footprint in the sensor's top-left normalized coordinates.
    /// No valid polygon is produced when a corner is behind the camera.
    func footprint(_ projection: ScanProjection) -> [SIMD2<Float>] {
        let projected = corners.compactMap { projection.project($0) }
        guard projected.count == 8 else { return [] }
        let sorted = projected.sorted { $0.x == $1.x ? $0.y < $1.y : $0.x < $1.x }
        func cross(_ a: SIMD2<Float>, _ b: SIMD2<Float>, _ c: SIMD2<Float>) -> Float {
            let ab = b-a, ac = c-a
            return ab.x * ac.y - ab.y * ac.x
        }
        var lower: [SIMD2<Float>] = [], upper: [SIMD2<Float>] = []
        for p in sorted {
            while lower.count >= 2 && cross(lower[lower.count-2], lower[lower.count-1], p) <= 0 { lower.removeLast() }
            lower.append(p)
        }
        for p in sorted.reversed() {
            while upper.count >= 2 && cross(upper[upper.count-2], upper[upper.count-1], p) <= 0 { upper.removeLast() }
            upper.append(p)
        }
        lower.removeLast(); upper.removeLast()
        return lower + upper
    }
    static func inside(_ pixel: SIMD2<Float>, polygon: [SIMD2<Float>]) -> Bool {
        guard pixel.x.isFinite, pixel.y.isFinite, polygon.count >= 3,
              polygon.allSatisfy({ $0.x.isFinite && $0.y.isFinite }) else { return false }
        for i in polygon.indices {
            let a = polygon[i], b = polygon[(i+1) % polygon.count]
            if (b.x-a.x) * (pixel.y-a.y) - (b.y-a.y) * (pixel.x-a.x) < -0.00001 { return false }
        }
        return true
    }
}
