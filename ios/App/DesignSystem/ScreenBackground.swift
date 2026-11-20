import SwiftUI

/// Behind every screen of the app (not the scanner, which is the camera).
struct ScreenBackground: View {
    var body: some View {
        Theme.canvas.ignoresSafeArea()
    }
}
