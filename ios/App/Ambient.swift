import SwiftUI

/// Slow warm glows behind the home screens. Drawn in one Canvas; still when Reduce Motion is on.
struct AmbientBackground: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30.0, paused: reduceMotion)) { timeline in
            Canvas { context, size in
                let t = reduceMotion ? 0 : timeline.date.timeIntervalSinceReferenceDate
                AmbientBackground.draw(&context, size: size, time: t)
            }
        }
        .background(Color(red: 0.045, green: 0.04, blue: 0.065))
        .ignoresSafeArea()
        .accessibilityHidden(true)
    }

    private static func draw(_ context: inout GraphicsContext, size: CGSize, time: Double) {
        let w = Double(size.width), h = Double(size.height)
        glow(&context, x: w * (0.22 + 0.10 * sin(time * 0.21)), y: h * (0.16 + 0.05 * cos(time * 0.17)),
             radius: w * 0.95, red: 1.00, green: 0.50, blue: 0.16, opacity: 0.34)
        glow(&context, x: w * (0.86 + 0.08 * cos(time * 0.13)), y: h * (0.42 + 0.07 * sin(time * 0.19)),
             radius: w * 0.80, red: 0.86, green: 0.20, blue: 0.36, opacity: 0.22)
        glow(&context, x: w * (0.30 + 0.12 * cos(time * 0.11)), y: h * (0.88 + 0.04 * sin(time * 0.23)),
             radius: w * 0.90, red: 0.22, green: 0.30, blue: 0.80, opacity: 0.20)
    }

    private static func glow(_ context: inout GraphicsContext, x: Double, y: Double, radius: Double,
                             red: Double, green: Double, blue: Double, opacity: Double) {
        let centre = CGPoint(x: x, y: y)
        let colours = Gradient(colors: [Color(red: red, green: green, blue: blue).opacity(opacity),
                                        Color(red: red, green: green, blue: blue).opacity(0)])
        let rect = CGRect(x: x - radius, y: y - radius, width: radius * 2, height: radius * 2)
        context.fill(Path(ellipseIn: rect), with: .radialGradient(colours, center: centre, startRadius: 0, endRadius: radius))
    }
}
