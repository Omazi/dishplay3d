import SwiftUI

/// Every dish scanned with this iPhone. Scan as many as needed, one after another: each keeps its own
/// name, picture and files.
struct LibraryView: View {
    let openSettings: () -> Void
    @EnvironmentObject var model: AppModel
    @State private var dishes: [DishRecord] = []
    @Namespace private var zoom
    /// The narrowest a card may be. It grows with the text size: two columns on an iPhone with the usual text,
    /// one with very large text (a name and a state need the width).
    @ScaledMetric(relativeTo: .subheadline) private var cardWidth: CGFloat = 138
    /// In a wide window (an iPad) the cards are wider rather than more numerous: three or four in a row.
    @ScaledMetric(relativeTo: .subheadline) private var wideCardWidth: CGFloat = 210
    @Environment(\.horizontalSizeClass) private var widthClass

    private var columns: [GridItem] {
        let narrowest = widthClass == .regular ? wideCardWidth : cardWidth
        return [GridItem(.adaptive(minimum: min(narrowest, 360)), spacing: Spacing.s, alignment: .top)]
    }

    var body: some View {
        NavigationStack {
            ZStack {
                ScreenBackground()
                if dishes.isEmpty {
                    ContentUnavailableView {
                        Label("Aucun plat pour l’instant", systemImage: "fork.knife")
                    } description: {
                        // The app's secondary ink: the system's grey is a little too light on the paper background.
                        Text("Les plats scannés apparaîtront ici, avec leur modèle 3D.").foregroundStyle(Theme.textSecondary)
                    } actions: {
                        // The next thing to do: scan, or first link the calculator that computes the models.
                        if model.paired && model.trackingSupported {
                            emptyAction("Scanner un plat") { model.screen = .scan }
                        } else if !model.paired {
                            emptyAction("Relier le calculateur", action: openSettings)
                        }
                    }
                } else {
                    ScrollView {
                        LazyVGrid(columns: columns, spacing: Spacing.s) {
                            ForEach(dishes) { dish in
                                NavigationLink(value: dish) {
                                    DishCard(dish: dish, progress: model.dishProgress[dish.id])
                                }
                                .buttonStyle(PressableStyle())
                                .modifier(ZoomSource(id: dish.id, namespace: zoom))
                            }
                        }
                        .padding(.horizontal, Spacing.m).padding(.top, Spacing.xs).padding(.bottom, Spacing.xl)
                        .readableColumn(900)
                    }
                    .refreshable {
                        _ = await model.refreshDishProgress()
                        reload()
                    }
                }
            }
            .navigationTitle("Mes plats")
            .toolbar {
                if model.paired && model.trackingSupported {
                    ToolbarItem(placement: .primaryAction) {
                        Button("Nouveau scan", systemImage: "plus") { model.screen = .scan }
                    }
                }
            }
            .navigationDestination(for: DishRecord.self) { dish in
                DishDetailView(dish: dish, changed: reload)
                    .modifier(ZoomDestination(id: dish.id, namespace: zoom))
            }
        }
        .onAppear(perform: reload)
        .task {
            // While this tab is on screen, keep asking the calculator where the unfinished dishes stand.
            while !Task.isCancelled {
                if await model.refreshDishProgress() { reload() }
                try? await Task.sleep(nanoseconds: 4_000_000_000)
            }
        }
    }

    /// The action of the empty screen, in the app's own action colours (the system's prominent style writes in
    /// white, which is hard to read on the lighter blue of the dark appearance).
    private func emptyAction(_ title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).font(.subheadline.weight(.semibold))
                .padding(.horizontal, Spacing.l).frame(minHeight: 48)
        }
        .buttonStyle(PrimaryButtonStyle(tint: Theme.accent, enabled: true))
    }

    private func reload() { dishes = DishLibrary.all() }
}
