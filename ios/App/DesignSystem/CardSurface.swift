import SwiftUI

extension View {
    /// A content card: plain surface, soft continuous corners, a hairline. Cards are content, so they never
    /// get glass.
    func cardSurface(radius: CGFloat = Radius.card) -> some View {
        background {
            RoundedRectangle(cornerRadius: radius).fill(Theme.surface).strokeBorder(Theme.hairline)
        }
    }
}
