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
            ScreenBackground()
            ScrollView {
                VStack(alignment: .leading, spacing: Spacing.l) {
                    preview
                    if dish.state != .ready && !modelShown { unfinished }
                    VStack(alignment: .leading, spacing: Spacing.xs) {
                        Text("Nom du plat").appText(.kicker).foregroundStyle(Theme.textSecondary)
                        TextField("Nom du plat", text: $name)
                            .font(.title3.weight(.semibold))
                            .foregroundStyle(Theme.textPrimary)
                            .submitLabel(.done)
                            .onSubmit(save)
                            .padding(14)
                            .cardSurface(radius: Radius.field)
                    }
                    facts
                    actions
                    if let exportError {
                        Text(exportError).font(.footnote).foregroundStyle(Theme.bad)
                    }
                }
                .padding(.horizontal, Spacing.m).padding(.top, Spacing.xs).padding(.bottom, Spacing.xl)
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

    /// The dish on its dark stage: the 3D model when it is on the iPhone, else a picture, else a placeholder.
    @ViewBuilder private var preview: some View {
        if modelShown {
            VStack(spacing: Spacing.s) {
                Stage {
                    PreviewView(renderer: renderer)
                        .frame(height: 340)
                        .accessibilityLabel("Modèle 3D du plat. Glisser pour le tourner, pincer pour zoomer.")
                }
                Picker("Affichage", selection: $mode) {
                    ForEach(PreviewMode.allCases) { Text($0.rawValue).tag($0) }
                }
                .pickerStyle(.segmented)
                .onChange(of: mode) { _, m in renderer.mode = m }
            }
        } else if let picture {
            Stage {
                // The picture fills the stage. A view taken with the iPhone upright is taller than the stage and
                // loses a little at the top and bottom, rather than leaving dark bars on its sides.
                Color.clear
                    .frame(height: 380)
                    .overlay {
                        Image(uiImage: picture).resizable().scaledToFill()
                            .accessibilityLabel(dish.state == .ready ? "Quatre vues du modèle 3D" : "Une des vues prises pendant le scan")
                    }
                    .clipped()
            }
        } else {
            Stage {
                VStack(spacing: 10) {
                    Image(systemName: dish.state == .ready ? "cube" : "hourglass").font(.largeTitle)
                        .foregroundStyle(Theme.textOnStage.opacity(0.4))
                        .accessibilityHidden(true)
                    Text(dish.state == .ready ? "Chargement…" : "Le modèle n’est pas encore sur l’iPhone.")
                        .font(.footnote).foregroundStyle(Theme.textOnStage.opacity(0.7))
                }
                .frame(height: 220)
            }
        }
    }

    /// A dish without its model yet: where it stands, and the button that finishes it.
    private var unfinished: some View {
        let progress = model.dishProgress[dish.id]
        return VStack(alignment: .leading, spacing: Spacing.s) {
            Label(progress?.text ?? "Vérification auprès du calculateur…", systemImage: "hourglass")
                .font(.subheadline.weight(.semibold)).foregroundStyle(Theme.textPrimary)
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
                    .font(.footnote).foregroundStyle(Theme.textSecondary)
            }
        }
        .padding(Spacing.m).frame(maxWidth: .infinity, alignment: .leading)
        .cardSurface()
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
                fact("Scanné le", date.formatted(date: .long, time: .shortened))
                Divider()
            }
            fact("Vues prises", "\(dish.frames)")
        }
        .font(.subheadline)
        .padding(.horizontal, 14)
        .cardSurface(radius: Radius.field)
    }

    /// One line of the card. The value goes under its label when both do not fit on a line (very large text).
    private func fact(_ label: String, _ value: String) -> some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: Spacing.s) {
                Text(label).foregroundStyle(Theme.textPrimary)
                Spacer(minLength: Spacing.s)
                Text(value).foregroundStyle(Theme.textSecondary)
            }
            .lineLimit(1)
            VStack(alignment: .leading, spacing: 2) {
                Text(label).foregroundStyle(Theme.textPrimary)
                Text(value).foregroundStyle(Theme.textSecondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.vertical, 12)
        .accessibilityElement(children: .combine)
    }

    private var actions: some View {
        VStack(spacing: Spacing.s) {
            if let arModel = dish.arModel {
                // iOS shows the textured model itself: turned by hand, or placed on the table at real size.
                PrimaryButton(title: "Voir sur votre table", icon: "arkit") { showOnTable(arModel) }
                    .accessibilityHint("Ouvre le modèle avec ses vraies couleurs, en 3D ou en réalité augmentée.")
            }
            if let model = dish.model {
                ShareLink(item: model) {
                    QuietButtonLabel(title: "Partager le modèle 3D", icon: "square.and.arrow.up")
                }
            }
            Button(action: exportAll) {
                QuietButtonLabel(title: "Exporter le dossier complet", icon: "archivebox")
            }
            Button(role: .destructive) { confirmDelete = true } label: {
                Label("Supprimer", systemImage: "trash")
                    .font(.subheadline.weight(.semibold)).frame(maxWidth: .infinity).frame(minHeight: 48)
                    .foregroundStyle(Theme.bad)
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

    /// iOS's viewer uses the name of the file as its title: the name of the dish, rather than "model".
    private func showOnTable(_ model: URL) {
        let clean = name.trimmingCharacters(in: .whitespacesAndNewlines).replacing("/", with: "-").replacing(":", with: "-")
        let named = URL.temporaryDirectory.appending(path: "\(clean.isEmpty ? "Plat" : clean).usdz")
        do {
            if FileManager.default.fileExists(atPath: named.path(percentEncoded: false)) {
                try FileManager.default.removeItem(at: named)
            }
            try FileManager.default.copyItem(at: model, to: named)
            arPreview = named
        } catch {
            arPreview = model   // the viewer still opens, under the file's own name
        }
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
