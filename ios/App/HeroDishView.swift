import SwiftUI

/// The idea of the app in one picture: scattered points fly together into a dish, which then turns slowly.
/// Pure SwiftUI drawing (about 1 500 dots), no asset and no network.
struct HeroDishView: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var start = Date()

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 60.0, paused: reduceMotion)) { timeline in
            Canvas { context, size in
                let t: Double = reduceMotion ? 60 : timeline.date.timeIntervalSince(start)
                HeroDishView.draw(&context, size: size, time: t, turning: !reduceMotion)
            }
        }
        .accessibilityLabel("Un plat qui se forme à partir d’un nuage de points")
        .onAppear { start = Date() }
    }

    private struct Dot {
        var target: SIMD3<Float>
        var scatter: SIMD3<Float>
        var red: Double
        var green: Double
        var blue: Double
        var delay: Float
        var size: Float
    }

    /// Deterministic pseudo-random numbers in 0..<1 (the picture is the same at every launch).
    private struct Lcg {
        var state: UInt64 = 0x2545F4914F6CDD1D
        mutating func next() -> Float {
            state = state &* 6364136223846793005 &+ 1442695040888963407
            return Float((state >> 40) & 0xFFFFFF) / Float(0x1000000)
        }
    }

    private static let dots: [Dot] = makeDots()

    private static func makeDots() -> [Dot] {
        var rng = Lcg()
        var out: [Dot] = []
        out.reserveCapacity(1600)
        func add(_ p: SIMD3<Float>, _ r: Double, _ g: Double, _ b: Double, _ size: Float) {
            let a = rng.next() * 2 * Float.pi
            let radius: Float = 1.6 + rng.next() * 1.6
            let scatter = SIMD3<Float>(cos(a) * radius, (rng.next() - 0.3) * 2.2, sin(a) * radius)
            let jitter = Double(rng.next()) * 0.08
            out.append(Dot(target: p, scatter: scatter, red: r - jitter, green: g - jitter, blue: b - jitter,
                           delay: rng.next() * 0.9, size: size))
        }
        // Plate: shallow well and a raised rim.
        for _ in 0..<760 {
            let rr = sqrt(rng.next())
            let a = rng.next() * 2 * Float.pi
            let y: Float = rr < 0.72 ? 0.05 * rr * rr : 0.026 + (rr - 0.72) * 0.42
            add(SIMD3<Float>(cos(a) * rr, y, sin(a) * rr), 0.93, 0.91, 0.87, 1.0)
        }
        // Food: a dome in the middle.
        for _ in 0..<520 {
            let rr = sqrt(rng.next()) * 0.46
            let a = rng.next() * 2 * Float.pi
            let y: Float = 0.03 + sqrt(max(0, 0.2116 - rr * rr)) * 0.78
            let warm = Double(rng.next())
            add(SIMD3<Float>(cos(a) * rr, y, sin(a) * rr), 0.98, 0.50 + 0.22 * warm, 0.16 + 0.10 * warm, 1.25)
        }
        // Sauce: a ring around the food.
        for _ in 0..<170 {
            let rr: Float = 0.52 + rng.next() * 0.08
            let a = rng.next() * 2 * Float.pi
            add(SIMD3<Float>(cos(a) * rr, 0.03, sin(a) * rr), 0.80, 0.16, 0.14, 1.0)
        }
        // Herbs on top.
        for _ in 0..<70 {
            let rr = rng.next() * 0.22
            let a = rng.next() * 2 * Float.pi
            let y: Float = 0.05 + sqrt(max(0, 0.2116 - rr * rr)) * 0.78
            add(SIMD3<Float>(cos(a) * rr, y, sin(a) * rr), 0.42, 0.78, 0.36, 1.1)
        }
        return out
    }

    private static func draw(_ context: inout GraphicsContext, size: CGSize, time: Double, turning: Bool) {
        let t = Float(time)
        let angle: Float = turning ? t * 0.45 : 0.6
        let ca = cos(angle), sa = sin(angle)
        let pitch: Float = 0.52
        let cp = cos(pitch), sp = sin(pitch)
        let scale = Float(min(size.width, size.height)) * 0.40
        let cx = Float(size.width) * 0.5
        let cy = Float(size.height) * 0.56
        for dot in dots {
            var k = (t - dot.delay) / 1.25
            k = min(1, max(0, k))
            let ease = 1 - (1 - k) * (1 - k) * (1 - k)
            let p = dot.scatter + (dot.target - dot.scatter) * ease
            let x = p.x * ca + p.z * sa
            let z0 = -p.x * sa + p.z * ca
            let y = p.y * cp - z0 * sp
            let z = p.y * sp + z0 * cp
            let persp = 1 / (1 + z * 0.22)
            let sx = cx + x * scale * persp
            let sy = cy - y * scale * persp
            let radius = CGFloat(dot.size * persp * 1.7)
            let depthLight = Double(0.62 + 0.38 * max(0, min(1, (1.2 - z) / 2.4)))
            let alpha = Double(0.15 + 0.85 * ease) * depthLight
            let rect = CGRect(x: CGFloat(sx) - radius, y: CGFloat(sy) - radius, width: radius * 2, height: radius * 2)
            context.fill(Path(ellipseIn: rect), with: .color(.sRGB, red: dot.red, green: dot.green, blue: dot.blue, opacity: alpha))
        }
    }
}
