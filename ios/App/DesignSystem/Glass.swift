import SwiftUI

extension View {
    /// Real Liquid Glass on iOS 26 and later, the system material before. For the navigation layer only
    /// (bars, floating controls over the camera): never on content, never on another glass element.
    @ViewBuilder func glass<S: Shape>(_ shape: S, interactive: Bool = false) -> some View {
        if #available(iOS 26.0, *) {
            self.glassEffect(Glass.regular.interactive(interactive), in: shape)
        } else {
            self.background(.ultraThinMaterial, in: shape)
        }
    }
}

extension View {
    /// On iOS 26 and later the tab bar recedes while the content scrolls down and comes back on the way up.
    @ViewBuilder func minimizingTabBar() -> some View {
        if #available(iOS 26.0, *) {
            self.tabBarMinimizeBehavior(.onScrollDown)
        } else {
            self
        }
    }
}
