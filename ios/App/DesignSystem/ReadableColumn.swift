import SwiftUI

extension View {
    /// On an iPad, and in any wide window, the content keeps the width of a comfortable column and sits in the
    /// middle, instead of stretching buttons and pictures from one edge to the other. On an iPhone held
    /// upright nothing changes: the screen is narrower than the column.
    func readableColumn(_ width: CGFloat = 640) -> some View {
        frame(maxWidth: width).frame(maxWidth: .infinity)
    }
}
