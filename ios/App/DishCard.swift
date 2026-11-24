import SwiftUI

/// One dish in a grid or a carousel: its picture first, then its name and where it stands.
struct DishCard: View {
    let dish: DishRecord
    var progress: AppModel.DishProgress?
    @State private var picture: UIImage?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ZStack {
                Theme.stage
                if let picture {
                    Image(uiImage: picture).resizable().scaledToFill()
                        .accessibilityHidden(true)
                } else {
                    Image(systemName: dish.state == .ready ? "cube" : "hourglass")
                        .font(.largeTitle).foregroundStyle(Theme.textOnStage.opacity(0.4))
                        .accessibilityHidden(true)
                }
            }
            .frame(height: 148).frame(maxWidth: .infinity).clipped()
            .accessibilityIgnoresInvertColors()
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                // Two lines are kept for the name even when it fills one: the cards of a row, or of the carousel
                // of the home screen, then have the same height and a long name is not cut after one line.
                Text(dish.name).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.textPrimary)
                    .lineLimit(2, reservesSpace: true)
                    .multilineTextAlignment(.leading)
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Circle().fill(stateColour).frame(width: 7, height: 7)
                    Text(stateText).font(.caption).foregroundStyle(Theme.textSecondary)
                        .lineLimit(2).fixedSize(horizontal: false, vertical: true)
                }
                if let fraction = progress?.fraction {
                    ProgressView(value: fraction).tint(Theme.accent)
                }
            }
            .padding(.horizontal, Spacing.s).padding(.vertical, 10)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(Theme.surface)
        .clipShape(.rect(cornerRadius: Radius.card))
        .overlay { RoundedRectangle(cornerRadius: Radius.card).strokeBorder(Theme.hairline) }
        .task(id: dish.id + (dish.state == .ready ? "-ready" : "")) {
            let d = dish
            picture = await Task.detached(priority: .utility) { DishLibrary.thumbnail(for: d) }.value
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(dish.name), \(stateText)")
    }

    /// What the calculator last said of the dish; until it answers, what the iPhone itself knows.
    private var stateText: String { progress?.text ?? dish.ownStateText }

    private var stateColour: Color {
        switch dish.state {
        case .ready: return Theme.good
        case .processing: return Theme.accent
        case .interrupted: return Theme.warn
        }
    }
}
