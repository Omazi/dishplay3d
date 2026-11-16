import Foundation

/// Pinhole intrinsics for an image of exactly `width` x `height` pixels (pixel centres at integers).
public struct Intrinsics: Codable, Equatable, Sendable {
    public var fx, fy, cx, cy: Double
    public var width, height: Int

    public init(fx: Double, fy: Double, cx: Double, cy: Double, width: Int, height: Int) {
        self.fx = fx; self.fy = fy; self.cx = cx; self.cy = cy; self.width = width; self.height = height
    }

    /// Intrinsics after resizing the image to (w, h), pixel-centre convention: c' = (c + 0.5) * s - 0.5.
    public func scaled(toWidth w: Int, height h: Int) -> Intrinsics {
        let sx = Double(w) / Double(width), sy = Double(h) / Double(height)
        return Intrinsics(fx: fx * sx, fy: fy * sy, cx: (cx + 0.5) * sx - 0.5, cy: (cy + 0.5) * sy - 0.5, width: w, height: h)
    }
}

public enum Coordinates {
    /// T_object_from_cameraCV = inverse(T_world_from_object) * T_world_from_cameraAR * C
    public static func objectFromCameraCV(worldFromObject: Mat4, worldFromCameraAR: Mat4) -> Mat4 {
        worldFromObject.rigidInverse * worldFromCameraAR * Mat4.arFromCV
    }

    /// Project object-frame points into the CV camera. Returns (u, v, depth) per point.
    public static func project(_ K: Intrinsics, cameraCVFromObject T: Mat4, points: [[Double]]) -> [(u: Double, v: Double, z: Double)] {
        points.map { p in
            let c = T.apply(p)
            return (c[0] / c[2] * K.fx + K.cx, c[1] / c[2] * K.fy + K.cy, c[2])
        }
    }

    /// Box sample points (5x3x5 grid) in object coordinates; size = (width x, height y, depth z).
    public static func boxSamples(width w: Double, height h: Double, depth d: Double) -> [[Double]] {
        var out: [[Double]] = []
        for i in 0..<5 { for j in 0..<3 { for k in 0..<5 {
            out.append([-w / 2 + w * Double(i) / 4, h * Double(j) / 2, -d / 2 + d * Double(k) / 4])
        } } }
        return out
    }

    /// Fraction of the box samples visible in the image (in front of the camera, inside the frame).
    public static func boxVisibility(_ K: Intrinsics, cameraCVFromObject T: Mat4, width: Double, height: Double, depth: Double) -> Double {
        let pts = boxSamples(width: width, height: height, depth: depth)
        let pr = project(K, cameraCVFromObject: T, points: pts)
        let ok = pr.filter { $0.z > 0.05 && $0.u >= 0 && $0.u < Double(K.width) && $0.v >= 0 && $0.v < Double(K.height) }
        return Double(ok.count) / Double(pts.count)
    }
}
