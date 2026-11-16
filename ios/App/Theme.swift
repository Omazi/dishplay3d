import SwiftUI
import UIKit

/// Shared look: Liquid Glass on iOS 26+, material fallback before.
extension View {
    @ViewBuilder func glass<S: Shape>(_ shape: S) -> some View {
        if #available(iOS 26.0, *) {
            self.glassEffect(.regular, in: shape)
        } else {
            self.background(.ultraThinMaterial, in: shape)
        }
    }
}

enum Theme {
    static let accent = Color(red: 1.0, green: 0.58, blue: 0.22)
    static let good = Color(red: 0.30, green: 0.85, blue: 0.55)
    static let bad = Color(red: 1.0, green: 0.36, blue: 0.36)
    static let warn = Color(red: 1.0, green: 0.76, blue: 0.28)
    static let panel = Color(red: 0.07, green: 0.07, blue: 0.09)
    static let corner: CGFloat = 26
}

/// Light physical feedback at the moments that matter (placing, starting, a new side covered, done).
@MainActor
enum Haptics {
    static func tap(_ style: UIImpactFeedbackGenerator.FeedbackStyle = .light) {
        UIImpactFeedbackGenerator(style: style).impactOccurred()
    }
    static func success() { UINotificationFeedbackGenerator().notificationOccurred(.success) }
    static func warning() { UINotificationFeedbackGenerator().notificationOccurred(.warning) }
}

/// Buttons sink slightly under the finger.
struct PressableStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.96 : 1)
            .opacity(configuration.isPressed ? 0.85 : 1)
            .animation(.spring(duration: 0.2), value: configuration.isPressed)
    }
}

/// One obvious action per step.
struct PrimaryButton: View {
    let title: String
    let icon: String
    var enabled = true
    var tint: Color = Theme.accent
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                Image(systemName: icon).font(.headline)
                Text(title).font(.headline)
            }
            .frame(maxWidth: .infinity).frame(height: 56)
            .background {
                if enabled {
                    Capsule().fill(LinearGradient(colors: [tint, tint.opacity(0.82)], startPoint: .top, endPoint: .bottom))
                        .shadow(color: tint.opacity(0.45), radius: 14, y: 6)
                } else {
                    Capsule().fill(Color.white.opacity(0.14))
                }
            }
            .foregroundStyle(enabled ? Color.black : Color.white.opacity(0.45))
            .animation(.easeInOut(duration: 0.3), value: tint)
        }
        .buttonStyle(PressableStyle())
        .disabled(!enabled)
    }
}

struct GlassIconButton: View {
    let icon: String
    var label: String?
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                Image(systemName: icon).font(.headline)
                if let label { Text(label).font(.subheadline.weight(.semibold)) }
            }
            .padding(.horizontal, label == nil ? 0 : 16)
            .frame(minWidth: 56).frame(height: 56)
            .foregroundStyle(.white)
            .glass(Capsule())
        }
        .buttonStyle(PressableStyle())
    }
}

struct StatusDot: View {
    let text: String
    let color: Color
    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(color).frame(width: 8, height: 8).shadow(color: color.opacity(0.8), radius: 4)
            Text(text).font(.footnote.weight(.semibold)).lineLimit(1)
        }
    }
}
