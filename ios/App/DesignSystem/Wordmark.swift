import SwiftUI

/// The brand name as on the website: lower case, with its blue full stop.
struct Wordmark: View {
    var body: some View {
        let name = Text("dishplay").foregroundStyle(Theme.textPrimary)
        let stop = Text(".").foregroundStyle(Theme.accent)
        Text("\(name)\(stop)")
            .appText(.wordmark)
            .accessibilityLabel("DishPlay")
    }
}
