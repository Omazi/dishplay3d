import SwiftUI

/// The one obvious action of a step: a solid capsule in the action colour. Only this button is coloured;
/// everything around it stays neutral.
struct PrimaryButton: View {
    let title: String
    let icon: String
    var enabled = true
    var tint: Color = Theme.accent
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label(title, systemImage: icon)
                .font(.headline)
                .frame(maxWidth: .infinity)
                .frame(minHeight: 56)
        }
        .buttonStyle(PrimaryButtonStyle(tint: tint, enabled: enabled))
        .disabled(!enabled)
    }
}
