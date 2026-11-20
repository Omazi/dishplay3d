import SwiftUI

/// Every dish scanned with this iPhone. Scan as many as needed, one after another: each keeps its own
/// name, picture and files.
struct LibraryView: View {
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
                        if model.paired && model.trackingSupported {
                            Button("Scanner un plat") { model.screen = .scan }
                                .buttonStyle(.borderedProminent).buttonBorderShape(.capsule).tint(Theme.accent)
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

    private func reload() { dishes = DishLibrary.all() }
}
