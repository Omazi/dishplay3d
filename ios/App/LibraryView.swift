import SwiftUI

/// Every dish scanned with this iPhone. Scan as many as needed, one after another: each keeps its own
/// name, picture and files.
struct LibraryView: View {
    let openSettings: () -> Void
    @EnvironmentObject var model: AppModel
    @State private var dishes: [DishRecord] = []
    @Namespace private var zoom

    private let columns = [GridItem(.flexible(), spacing: Spacing.s), GridItem(.flexible(), spacing: Spacing.s)]

    var body: some View {
        NavigationStack {
            ZStack {
                ScreenBackground()
                if dishes.isEmpty {
                    ContentUnavailableView {
                        Label("Aucun plat pour l’instant", systemImage: "fork.knife")
                    } description: {
                        Text("Les plats scannés apparaîtront ici, avec leur modèle 3D.")
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
