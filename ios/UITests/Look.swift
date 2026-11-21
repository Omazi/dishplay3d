/// One way of looking at the app: light or dark appearance, with the text size chosen in the iPhone settings.
struct Look {
    /// Used in the names of the pictures.
    let name: String
    let isDark: Bool
    /// A `UIContentSizeCategory` name, nil for the standard size.
    let textSize: String?

    static let light = Look(name: "clair", isDark: false, textSize: nil)
    static let dark = Look(name: "sombre", isDark: true, textSize: nil)
    /// About 235 % of the standard size: above the 200 % that Apple's accessibility labels ask for.
    static let largeText = Look(name: "grand-texte", isDark: false, textSize: "UICTContentSizeCategoryAccessibilityXL")
}
