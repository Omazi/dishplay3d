import SwiftUI

struct StatusDot: View {
    let text: String
    let color: Color
    /// What VoiceOver says instead of `text`, when the colour carries part of the meaning ("Suivi : bon").
    var spoken: String?

    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(color).frame(width: 8, height: 8)
            Text(text).font(.footnote.weight(.semibold)).lineLimit(1)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(spoken ?? text)
    }
}
