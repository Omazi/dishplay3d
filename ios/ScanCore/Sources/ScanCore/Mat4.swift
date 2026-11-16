import Foundation

/// 4x4 rigid transform in double precision, stored ROW-MAJOR (the wire order).
/// `T_A_from_B` maps coordinates expressed in frame B into frame A.
public struct Mat4: Equatable, Codable, Sendable {
    public var m: [Double]  // 16 values, row-major: m[r * 4 + c]

    public init(rowMajor: [Double]) {
        precondition(rowMajor.count == 16, "Mat4 needs 16 values")
        m = rowMajor
    }

    /// Build from 4 columns (e.g. simd_float4x4.columns), avoiding any implicit layout confusion.
    public init(columns c0: [Double], _ c1: [Double], _ c2: [Double], _ c3: [Double]) {
        let cols = [c0, c1, c2, c3]
        var v = [Double](repeating: 0, count: 16)
        for r in 0..<4 { for c in 0..<4 { v[r * 4 + c] = cols[c][r] } }
        m = v
    }

    public static let identity = Mat4(rowMajor: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
    /// C = diag(1, -1, -1, 1): cameraCV = cameraAR * C.
    public static let arFromCV = Mat4(rowMajor: [1, 0, 0, 0, 0, -1, 0, 0, 0, 0, -1, 0, 0, 0, 0, 1])

    public subscript(r: Int, c: Int) -> Double {
        get { m[r * 4 + c] }
        set { m[r * 4 + c] = newValue }
    }

    public var rowMajor: [Double] { m }
    public var translation: [Double] { [m[3], m[7], m[11]] }

    public static func * (a: Mat4, b: Mat4) -> Mat4 {
        var out = [Double](repeating: 0, count: 16)
        for r in 0..<4 {
            for c in 0..<4 {
                var s = 0.0
                for k in 0..<4 { s += a.m[r * 4 + k] * b.m[k * 4 + c] }
                out[r * 4 + c] = s
            }
        }
        return Mat4(rowMajor: out)
    }

    /// Inverse of a rigid transform [R t; 0 1] -> [R^T, -R^T t].
    public var rigidInverse: Mat4 {
        var out = Mat4.identity
        for r in 0..<3 { for c in 0..<3 { out[r, c] = self[c, r] } }
        for r in 0..<3 {
            out[r, 3] = -(out[r, 0] * self[0, 3] + out[r, 1] * self[1, 3] + out[r, 2] * self[2, 3])
        }
        return out
    }

    public func apply(_ p: [Double]) -> [Double] {
        (0..<3).map { r in self[r, 0] * p[0] + self[r, 1] * p[1] + self[r, 2] * p[2] + self[r, 3] }
    }

    public func isRigid(tolerance: Double = 1e-3) -> Bool {
        for i in 0..<3 {
            for j in 0..<3 {
                var dot = 0.0
                for k in 0..<3 { dot += self[k, i] * self[k, j] }
                if abs(dot - (i == j ? 1 : 0)) > tolerance { return false }
            }
        }
        let det = self[0, 0] * (self[1, 1] * self[2, 2] - self[1, 2] * self[2, 1])
            - self[0, 1] * (self[1, 0] * self[2, 2] - self[1, 2] * self[2, 0])
            + self[0, 2] * (self[1, 0] * self[2, 1] - self[1, 1] * self[2, 0])
        return abs(det - 1) < tolerance && abs(self[3, 0]) + abs(self[3, 1]) + abs(self[3, 2]) + abs(self[3, 3] - 1) < tolerance
    }

    /// Rotation about +y (yaw, radians) followed by a translation: the capture box pose on the table.
    public static func yawTranslation(yaw: Double, x: Double, y: Double, z: Double) -> Mat4 {
        let c = cos(yaw), s = sin(yaw)
        return Mat4(rowMajor: [c, 0, s, x, 0, 1, 0, y, -s, 0, c, z, 0, 0, 0, 1])
    }
}
