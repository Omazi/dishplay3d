import SwiftUI

/// Top view of the tour around the dish. The phone is always at the bottom ("you are here"):
/// empty sectors on the right mean "walk to your right". Outer ring: side views; inner ring: high views.
struct CoverageRingView: View {
    let counts: [[Int]]        // 3 elevation rows x 12 azimuth sectors (ScanCore.CoverageRing)
    let azimuthDeg: Double     // where the phone is now, object frame

    var body: some View {
        Canvas { ctx, size in
            let c = CGPoint(x: size.width / 2, y: size.height / 2)
            let R = min(size.width, size.height) / 2 - 5
            for k in 0..<12 {
                let side = counts.count == 3 && (counts[0][k] + counts[1][k]) > 0
                let high = counts.count == 3 && counts[2][k] > 0
                // Screen angle (y down). Top view with x right / z down is a true, non-mirrored view from above.
                let a0 = (Double(k) * 30 - azimuthDeg + 90 + 2.5) * .pi / 180
                let a1 = (Double(k + 1) * 30 - azimuthDeg + 90 - 2.5) * .pi / 180
                ctx.fill(Self.sector(c, R * 0.74, R, a0, a1), with: .color(side ? Theme.accent : Color.white.opacity(0.20)))
                ctx.fill(Self.sector(c, R * 0.46, R * 0.68, a0, a1), with: .color(high ? Theme.good : Color.white.opacity(0.13)))
            }
            ctx.fill(Path(ellipseIn: CGRect(x: c.x - R * 0.2, y: c.y - R * 0.2, width: R * 0.4, height: R * 0.4)),
                     with: .color(Color.white.opacity(0.35)))
            var me = Path()
            me.move(to: CGPoint(x: c.x, y: c.y + R - 3))
            me.addLine(to: CGPoint(x: c.x - 5, y: c.y + R + 5))
            me.addLine(to: CGPoint(x: c.x + 5, y: c.y + R + 5))
            me.closeSubpath()
            ctx.fill(me, with: .color(.white))
        }
        .accessibilityLabel("Couverture du tour autour du plat")
    }

    private static func sector(_ c: CGPoint, _ r0: Double, _ r1: Double, _ a0: Double, _ a1: Double) -> Path {
        var p = Path()
        let n = 8
        for i in 0...n {
            let a = a0 + (a1 - a0) * Double(i) / Double(n)
            let pt = CGPoint(x: c.x + r1 * cos(a), y: c.y + r1 * sin(a))
            if i == 0 { p.move(to: pt) } else { p.addLine(to: pt) }
        }
        for i in (0...n).reversed() {
            let a = a0 + (a1 - a0) * Double(i) / Double(n)
            p.addLine(to: CGPoint(x: c.x + r0 * cos(a), y: c.y + r0 * sin(a)))
        }
        p.closeSubpath()
        return p
    }
}
