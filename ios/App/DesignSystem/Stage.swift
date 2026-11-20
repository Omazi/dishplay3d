import SwiftUI

/// The dark stage a dish is shown on: the animated dish of the home screen, a 3D model, a photo.
struct Stage<Content: View>: View {
    private let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        content
            .frame(maxWidth: .infinity)
            .background(Theme.stage)
            .clipShape(.rect(cornerRadius: Radius.stage))
    }
}
