import SwiftUI

/// A secondary action as wide as its container: neutral fill, same height as the primary one.
struct QuietButtonLabel: View {
    let title: String
    let icon: String

    var body: some View {
        Label(title, systemImage: icon)
            .font(.subheadline.weight(.semibold))
            .frame(maxWidth: .infinity)
            .frame(minHeight: 52)
            .foregroundStyle(Theme.textPrimary)
            .background(Theme.surfaceSunken, in: Capsule())
    }
}
