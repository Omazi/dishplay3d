import SwiftUI

/// Top view of the tour around the dish. The phone is always at the bottom ("you are here"):
/// empty sectors on the right mean "walk to your right". Outer ring: side views; inner ring: high views.
struct CoverageRingView: View {
    let counts: [[Int]]        // 3 elevation rows x 12 azimuth sectors (ScanCore.CoverageRing)
    let azimuthDeg: Double     // where the phone is now, object frame

    var body: some View {
        Canvas { ctx, size in
            draw(&ctx, size)
        }
        .accessibilityLabel("Couverture du tour autour du plat")
    }

    private func draw(_ ctx: inout GraphicsContext, _ size: CGSize) {
        let cx: Double = Double(size.width) / 2
        let cy: Double = Double(size.height) / 2
        let R: Double = Double(min(size.width, size.height)) / 2 - 5
        let emptyOuter = Theme.textPrimary.opacity(0.22)
        let emptyInner = Theme.textPrimary.opacity(0.14)
        for k in 0..<12 {
            let side: Bool = counts.count == 3 && (counts[0][k] + counts[1][k]) > 0
            let high: Bool = counts.count == 3 && counts[2][k] > 0
            // Screen angle (y down). Top view with x right / z down is a true, non-mirrored view from above.
            let start: Double = Double(k) * 30 - azimuthDeg + 90
            let a0: Double = (start + 2.5) * Double.pi / 180
            let a1: Double = (start + 27.5) * Double.pi / 180
            let outer: Path = Self.sector(cx, cy, R * 0.74, R, a0, a1)
            let inner: Path = Self.sector(cx, cy, R * 0.46, R * 0.68, a0, a1)
            ctx.fill(outer, with: .color(side ? Theme.accent : emptyOuter))
            ctx.fill(inner, with: .color(high ? Theme.good : emptyInner))
        }
        let dish = CGRect(x: cx - R * 0.2, y: cy - R * 0.2, width: R * 0.4, height: R * 0.4)
        ctx.fill(Path(ellipseIn: dish), with: .color(Theme.textPrimary.opacity(0.35)))
        var me = Path()
        me.move(to: CGPoint(x: cx, y: cy + R - 3))
        me.addLine(to: CGPoint(x: cx - 5, y: cy + R + 5))
        me.addLine(to: CGPoint(x: cx + 5, y: cy + R + 5))
        me.closeSubpath()
        ctx.fill(me, with: .color(Theme.textPrimary))
    }

    private static func point(_ cx: Double, _ cy: Double, _ r: Double, _ a: Double) -> CGPoint {
        CGPoint(x: cx + r * cos(a), y: cy + r * sin(a))
    }

    private static func sector(_ cx: Double, _ cy: Double, _ r0: Double, _ r1: Double, _ a0: Double, _ a1: Double) -> Path {
        var p = Path()
        let n = 8
        let step: Double = (a1 - a0) / Double(n)
        p.move(to: point(cx, cy, r1, a0))
        for i in 1...n { p.addLine(to: point(cx, cy, r1, a0 + step * Double(i))) }
        for i in 0...n { p.addLine(to: point(cx, cy, r0, a1 - step * Double(i))) }
        p.closeSubpath()
        return p
    }
}
