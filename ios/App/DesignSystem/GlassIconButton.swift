import SwiftUI

/// A floating control over the camera: glass, never coloured.
struct GlassIconButton: View {
    let icon: String
    var label: String?
    /// What VoiceOver says when the button shows an icon only.
    var name: String = ""
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                Image(systemName: icon).font(.headline)
                if let label { Text(label).font(.subheadline.weight(.semibold)) }
            }
            .padding(.horizontal, label == nil ? 0 : Spacing.m)
            .frame(minWidth: 56, minHeight: 56)
            .foregroundStyle(Theme.textPrimary)
            .glass(Capsule(), interactive: true)
        }
        .buttonStyle(PressableStyle())
        .accessibilityLabel(label ?? name)
    }
}
