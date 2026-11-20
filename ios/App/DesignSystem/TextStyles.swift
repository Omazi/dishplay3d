import SwiftUI

/// One text style = font, letter width, tracking and case, applied with one modifier (`appText`).
/// The fonts are the system's text styles, so everything follows Dynamic Type.
struct AppTextStyle {
    var font: Font
    var width: Font.Width = .standard
    var tracking: CGFloat = 0
    var textCase: Text.Case?
}

extension AppTextStyle {
    /// The opening line of a screen.
    static let display = AppTextStyle(font: .largeTitle.bold(), tracking: -0.6)
    /// A title inside the content of a screen.
    static let title = AppTextStyle(font: .title.bold(), tracking: -0.4)
    /// The title of a section inside a screen.
    static let section = AppTextStyle(font: .title3.weight(.semibold), tracking: -0.2)
    /// The small line above a title: wide capitals.
    static let kicker = AppTextStyle(font: .caption.weight(.semibold), width: .expanded, tracking: 0.6, textCase: .uppercase)
    /// The brand name.
    static let wordmark = AppTextStyle(font: .title2.weight(.heavy), tracking: -0.8)
}

extension View {
    func appText(_ style: AppTextStyle) -> some View {
        font(style.font).fontWidth(style.width).tracking(style.tracking).textCase(style.textCase)
    }
}
