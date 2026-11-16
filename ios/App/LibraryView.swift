import SwiftUI

/// Every dish scanned with this iPhone. Scan as many as needed, one after another: each keeps its own
/// name, picture and files.
struct LibraryView: View {
    @EnvironmentObject var model: AppModel
    @State private var dishes: [DishRecord] = []
    @Namespace private var zoom

    private let columns = [GridItem(.flexible(), spacing: 14), GridItem(.flexible(), spacing: 14)]

    var body: some View {
        NavigationStack {
            ZStack {
                AmbientBackground()
                if dishes.isEmpty {
                    ContentUnavailableView {
                        Label("Aucun plat pour l’instant", systemImage: "fork.knife")
                    } description: {
                        Text("Les plats scannés apparaîtront ici, avec leur modèle 3D.")
                    } actions: {
                        if model.paired && model.trackingSupported {
                            Button("Scanner un plat") { model.screen = .scan }
                                .buttonStyle(.borderedProminent).tint(Theme.accent)
                        }
                    }
                } else {
                    ScrollView {
                        LazyVGrid(columns: columns, spacing: 14) {
                            ForEach(dishes) { dish in
                                NavigationLink(value: dish) {
                                    DishCard(dish: dish)
                                }
                                .buttonStyle(PressableStyle())
                                .modifier(ZoomSource(id: dish.id, namespace: zoom))
                            }
                        }
                        .padding(.horizontal, 20).padding(.top, 8).padding(.bottom, 24)
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
    }

    private func reload() { dishes = DishLibrary.all() }
}

/// One dish in a grid or a carousel.
struct DishCard: View {
    let dish: DishRecord
    @State private var picture: UIImage?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ZStack {
                Color(red: 0.13, green: 0.13, blue: 0.15)
                if let picture {
                    Image(uiImage: picture).resizable().scaledToFill()
                        .accessibilityHidden(true)
                } else {
                    Image(systemName: dish.state == .ready ? "cube" : "hourglass")
                        .font(.largeTitle).foregroundStyle(.white.opacity(0.35))
                        .accessibilityHidden(true)
                }
            }
            .frame(height: 132).frame(maxWidth: .infinity).clipped()
            VStack(alignment: .leading, spacing: 4) {
                Text(dish.name).font(.subheadline.weight(.semibold)).foregroundStyle(.white).lineLimit(1)
                HStack(spacing: 6) {
                    Circle().fill(stateColour).frame(width: 7, height: 7)
                    Text(stateText).font(.caption).foregroundStyle(.white.opacity(0.7)).lineLimit(1)
                }
            }
            .padding(.horizontal, 12).padding(.vertical, 10)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(Color.white.opacity(0.07))
        .clipShape(.rect(cornerRadius: 20))
        .overlay(RoundedRectangle(cornerRadius: 20).strokeBorder(Color.white.opacity(0.09)))
        .task(id: dish.id) {
            let d = dish
            picture = await Task.detached(priority: .utility) { DishLibrary.thumbnail(for: d) }.value
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(dish.name), \(stateText)")
    }

    private var stateText: String {
        switch dish.state {
        case .ready: return "Modèle prêt"
        case .processing: return "Calcul lancé"
        case .interrupted: return "Scan interrompu"
        }
    }

    private var stateColour: Color {
        switch dish.state {
        case .ready: return Theme.good
        case .processing: return Theme.accent
        case .interrupted: return Theme.warn
        }
    }
}

/// The card grows into the detail screen on iOS 18 and later; a standard push before.
struct ZoomSource: ViewModifier {
    let id: String
    let namespace: Namespace.ID

    func body(content: Content) -> some View {
        if #available(iOS 18.0, *) {
            content.matchedTransitionSource(id: id, in: namespace)
        } else {
            content
        }
    }
}

struct ZoomDestination: ViewModifier {
    let id: String
    let namespace: Namespace.ID

    func body(content: Content) -> some View {
        if #available(iOS 18.0, *) {
            content.navigationTransition(.zoom(sourceID: id, in: namespace))
        } else {
            content
        }
    }
}
