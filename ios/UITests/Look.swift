/// One way of looking at the app: light or dark appearance, with the text size chosen in the iPhone settings.
struct Look {
    /// Used in the names of the pictures.
    let name: String
    /// The appearance the simulator must be in during the walk. Whoever starts the walk sets it: the workflow
    /// with `xcrun simctl ui <device> appearance dark`, a person with Features > Toggle Appearance. The walk
    /// only checks it, on its first picture.
    let isDark: Bool
    /// A `UIContentSizeCategory` name, nil for the standard size.
    let textSize: String?
    /// Whether Apple's accessibility audit is run on each screen (it takes a few seconds per screen).
    let audited: Bool

    static let light = Look(name: "clair", isDark: false, textSize: nil, audited: true)
    static let dark = Look(name: "sombre", isDark: true, textSize: nil, audited: true)
    /// About 235 % of the standard size: above the 200 % that Apple's accessibility labels ask for.
    /// Not audited: at this size the pictures say more than the audit's long list of clipped texts.
    static let largeText = Look(name: "grand-texte", isDark: false, textSize: "UICTContentSizeCategoryAccessibilityXL",
                                audited: false)
}
