import ScanCore
import simd

extension Mat4 {
    /// simd matrices are column-major; Mat4 is row-major. Converting through columns keeps it explicit.
    init(_ m: simd_float4x4) {
        let c = m.columns
        self.init(columns: [Double(c.0.x), Double(c.0.y), Double(c.0.z), Double(c.0.w)],
                  [Double(c.1.x), Double(c.1.y), Double(c.1.z), Double(c.1.w)],
                  [Double(c.2.x), Double(c.2.y), Double(c.2.z), Double(c.2.w)],
                  [Double(c.3.x), Double(c.3.y), Double(c.3.z), Double(c.3.w)])
    }
}
