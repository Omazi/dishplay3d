import SwiftUI

/// Colours by role, the same ones as the dishplay website (paper, ink, blue). Their light and dark values
/// live in the asset catalog (Assets.xcassets/Colors, written by tools/ios_colors.py) and follow the
/// iPhone's appearance; the scanner, which sits on the camera image, always asks for the dark ones.
enum Theme {
    /// Behind a whole screen.
    static let canvas = Color("Canvas")
    /// Cards and grouped content.
    static let surface = Color("Surface")
    /// Fields, wells and quiet buttons sitting on a surface or on the canvas.
    static let surfaceSunken = Color("SurfaceSunken")
    /// The dark stage 3D content is shown on, in both appearances (a model reads best on dark).
    static let stage = Color("Stage")
    static let textOnStage = Color("TextOnStage")
    static let textPrimary = Color("TextPrimary")
    static let textSecondary = Color("TextSecondary")
    static let hairline = Color("Hairline")
    /// The one action colour: primary buttons, selection, progress.
    static let accent = Color("AccentColor")
    /// Text and symbols on a filled action or status colour.
    static let onAccent = Color("OnAccent")
    static let good = Color("Good")
    static let warn = Color("Warn")
    static let bad = Color("Bad")
}
