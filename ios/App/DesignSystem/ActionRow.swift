import SwiftUI

/// Small actions side by side; one under the other when they do not fit on a line (very large text, narrow
/// screen), so that no label is cut in the middle of a word.
struct ActionRow<Content: View>: View {
    private let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 10) { content }
            VStack(alignment: .leading, spacing: 10) { content }
        }
    }
}
