import QuickLook
import ScanCore
import SwiftUI

/// One dish: its picture, its name, and what can be done with its files.
struct DishDetailView: View {
    let dish: DishRecord
    let changed: () -> Void
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var name: String
    @State private var picture: UIImage?
    @State private var confirmDelete = false
    @State private var exportURL: URL?
    @State private var exportError: String?
    /// The textured model being shown by iOS itself (3D view and augmented reality), nil when closed.
    @State private var arPreview: URL?
    @StateObject private var renderer = PreviewRenderer()
    @State private var modelShown = false
    @State private var mode: PreviewMode = .surface

    init(dish: DishRecord, changed: @escaping () -> Void) {
        self.dish = dish
        self.changed = changed
        _name = State(initialValue: dish.name)
    }

    var body: some View {
        ZStack {
            AmbientBackground()
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    preview
                    if dish.state != .ready && !modelShown { unfinished }
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Nom du plat").font(.footnote).foregroundStyle(.white.opacity(0.6))
                        TextField("Nom du plat", text: $name)
                            .font(.title3.weight(.semibold))
                            .submitLabel(.done)
                            .onSubmit(save)
                            .padding(14)
                            .background(Color.white.opacity(0.07), in: RoundedRectangle(cornerRadius: 14))
                    }
                    facts
                    actions
                    if let exportError {
                        Text(exportError).font(.footnote).foregroundStyle(Theme.bad)
                    }
                }
                .padding(.horizontal, 20).padding(.top, 8).padding(.bottom, 28)
            }
            .scrollDismissesKeyboard(.interactively)
        }
        .navigationTitle(name.isEmpty ? "Plat" : name)
        .navigationBarTitleDisplayMode(.inline)
        .onDisappear(perform: save)
        .task {
            if showModel(of: dish) { return }
            let d = dish
            picture = await Task.detached(priority: .userInitiated) {
                d.picture.flatMap { UIImage(contentsOfFile: $0.path) } ?? DishLibrary.photo(for: d)
            }.value
            _ = await model.refreshDishProgress()
        }
        .sheet(item: $exportURL) { url in ShareSheet(items: [url]) }
        .quickLookPreview($arPreview)
        .confirmationDialog("Supprimer ce plat de l’iPhone ?", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Supprimer", role: .destructive) {
                DishLibrary.delete(dish)
                changed()
                dismiss()
            }
        } message: {
            Text("Les vues et le modèle enregistrés sur cet iPhone seront effacés. Ce qui est sur le calculateur n’est pas touché.")
        }
    }

    @ViewBuilder private var preview: some View {
        if modelShown {
            VStack(spacing: 10) {
                PreviewView(renderer: renderer)
                    .frame(height: 330)
                    .clipShape(.rect(cornerRadius: 22))
                    .accessibilityLabel("Modèle 3D du plat. Glisser pour le tourner, pincer pour zoomer.")
                Picker("Affichage", selection: $mode) {
                    ForEach(PreviewMode.allCases) { Text($0.rawValue).tag($0) }
                }
                .pickerStyle(.segmented)
                .onChange(of: mode) { _, m in renderer.mode = m }
            }
        } else if let picture {
            Image(uiImage: picture).resizable().scaledToFit()
                .frame(maxWidth: .infinity).frame(maxHeight: 420)
                .clipShape(.rect(cornerRadius: 22))
                .accessibilityLabel(dish.state == .ready ? "Quatre vues du modèle 3D" : "Une des vues prises pendant le scan")
        } else {
            VStack(spacing: 10) {
                Image(systemName: dish.state == .ready ? "cube" : "hourglass").font(.system(size: 44)).foregroundStyle(.white.opacity(0.4))
                    .accessibilityHidden(true)
                Text(dish.state == .ready ? "Chargement…" : "Le modèle n’est pas encore sur l’iPhone.")
                    .font(.footnote).foregroundStyle(.white.opacity(0.6))
            }
            .frame(maxWidth: .infinity).frame(height: 220)
            .background(Color.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 22))
        }
    }

    /// A dish without its model yet: where it stands, and the button that finishes it.
    private var unfinished: some View {
        let progress = model.dishProgress[dish.id]
        return VStack(alignment: .leading, spacing: 12) {
            Label(progress?.text ?? "Vérification auprès du calculateur…", systemImage: "hourglass")
                .font(.subheadline.weight(.semibold))
                .fixedSize(horizontal: false, vertical: true)
            if let fraction = progress?.fraction {
                ProgressView(value: fraction).tint(Theme.accent)
            }
            if progress?.canComplete == true {
                PrimaryButton(title: "Terminer ce plat", icon: "checkmark", enabled: model.completingDish == nil) {
                    Task {
                        await model.complete(dish)
                        changed()
                    }
                }
                Text("Les vues restantes sont envoyées, puis le calculateur construit le modèle.")
                    .font(.footnote).foregroundStyle(.white.opacity(0.6))
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.white.opacity(0.07), in: RoundedRectangle(cornerRadius: 18))
        .task {
            while !Task.isCancelled {
                if await model.refreshDishProgress() {
                    changed()
                    // The model has just arrived: show it here without leaving the screen.
                    if let fresh = DishLibrary.all().first(where: { $0.id == dish.id }) { showModel(of: fresh) }
                }
                try? await Task.sleep(nanoseconds: 4_000_000_000)
            }
        }
    }

    private var facts: some View {
        VStack(spacing: 0) {
            if let date = dish.date {
                LabeledContent("Scanné le", value: date.formatted(date: .long, time: .shortened))
                Divider().overlay(Color.white.opacity(0.1))
            }
            LabeledContent("Vues prises", value: "\(dish.frames)")
        }
        .font(.subheadline)
        .padding(.horizontal, 14).padding(.vertical, 6)
        .background(Color.white.opacity(0.07), in: RoundedRectangle(cornerRadius: 14))
    }

    private var actions: some View {
        VStack(spacing: 12) {
            if let arModel = dish.arModel {
                // iOS shows the textured model itself: turned by hand, or placed on the table at real size.
                Button { arPreview = arModel } label: {
                    Label("Voir sur votre table", systemImage: "arkit")
                        .font(.headline).frame(maxWidth: .infinity).frame(height: 56)
                        .background(Theme.accent, in: Capsule()).foregroundStyle(.black)
                }
                .accessibilityHint("Ouvre le modèle avec ses vraies couleurs, en 3D ou en réalité augmentée.")
            }
            if let model = dish.model {
                ShareLink(item: model) {
                    Label("Partager le modèle 3D", systemImage: "square.and.arrow.up")
                        .font(dish.arModel == nil ? .headline : .subheadline.weight(.semibold))
                        .frame(maxWidth: .infinity).frame(height: dish.arModel == nil ? 56 : 50)
                        .background(dish.arModel == nil ? AnyShapeStyle(Theme.accent) : AnyShapeStyle(Color.white.opacity(0.10)), in: Capsule())
                        .foregroundStyle(dish.arModel == nil ? Color.black : Color.white)
                }
            }
            Button(action: exportAll) {
                Label("Exporter le dossier complet", systemImage: "archivebox")
                    .font(.subheadline.weight(.semibold)).frame(maxWidth: .infinity).frame(height: 50)
                    .background(Color.white.opacity(0.10), in: Capsule()).foregroundStyle(.white)
            }
            Button(role: .destructive) { confirmDelete = true } label: {
                Label("Supprimer", systemImage: "trash")
                    .font(.subheadline.weight(.semibold)).frame(maxWidth: .infinity).frame(height: 50)
            }
        }
        .buttonStyle(PressableStyle())
    }

    /// Put the dish's final model in the 3D viewer, if it is on the iPhone.
    @discardableResult private func showModel(of record: DishRecord) -> Bool {
        guard let url = record.geometry, let data = try? Data(contentsOf: url), let geometry = try? PreviewGeometry.decode(data) else { return false }
        renderer.followPhone = false
        renderer.mode = mode
        renderer.show(geometry)
        modelShown = true
        return true
    }

    private func save() {
        let clean = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty, clean != dish.name else { return }
        DishLibrary.rename(dish, to: clean)
        changed()
    }

    private func exportAll() {
        do {
            exportURL = try SessionStore(resuming: dish.id).exportZip()
            exportError = nil
        } catch {
            exportError = "Export impossible : \(error.localizedDescription)"
        }
    }
}
