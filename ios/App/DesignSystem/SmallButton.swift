import SwiftUI

/// A small secondary action inside a card.
struct SmallButton: View {
    let title: String
    let icon: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label(title, systemImage: icon).font(.footnote.weight(.semibold))
                .padding(.horizontal, 14).frame(minHeight: 44)
                .foregroundStyle(Theme.textPrimary)
                .background(Theme.surfaceSunken, in: Capsule())
        }
        .buttonStyle(PressableStyle())
    }
}
