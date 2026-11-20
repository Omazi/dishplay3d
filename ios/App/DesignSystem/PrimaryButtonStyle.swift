import SwiftUI

/// How the primary action is drawn: a solid capsule that sinks slightly under the finger.
struct PrimaryButtonStyle: ButtonStyle {
    let tint: Color
    let enabled: Bool

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(enabled ? Theme.onAccent : Theme.textSecondary)
            // Opaque on purpose, also over the camera: the main action must stay readable over anything.
            .background(enabled ? tint : Theme.surfaceSunken, in: Capsule())
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .opacity(configuration.isPressed ? 0.88 : 1)
            .animation(.spring(duration: 0.2), value: configuration.isPressed)
            .animation(.easeInOut(duration: 0.3), value: tint)
    }
}
