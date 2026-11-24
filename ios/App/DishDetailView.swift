import QuickLook
import ScanCore
import SwiftUI

/// One dish: its picture, its name, and what can be done with its files.
struct DishDetailView: View {
    /// The dish as it is on the iPhone now. It starts as the record the screen was opened with and is read
    /// again when files arrive (`refreshRecord`): the 3D view, "Voir sur votre table" and "Partager" then
    /// appear without leaving the screen.
    @State private var record: DishRecord
    let changed: () -> Void
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var name: String
    @State private var picture: UIImage?
    @State private var confirmDelete = false
    @State private var exportURL: URL?
    @State private var exportError: String?
    /// The folder of the dish is being zipped for sharing.
    @State private var exporting = false
    /// The textured model being shown by iOS itself (3D view and augmented reality), nil when closed.
    @State private var arPreview: URL?
    @StateObject private var renderer = PreviewRenderer()
    @State private var modelShown = false
    @State private var mode: PreviewMode = .surface

    init(dish: DishRecord, changed: @escaping () -> Void) {
        _record = State(initialValue: dish)
        self.changed = changed
        _name = State(initialValue: dish.name)
    }

    var body: some View {
        ZStack {
            ScreenBackground()
            ScrollView {
                VStack(alignment: .leading, spacing: Spacing.l) {
                    preview
                    if record.state != .ready && !modelShown { unfinished }
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
                    if let outcome = record.outcome { outcomeNotes(outcome) }
                    actions
                    if let exportError {
                        Text(exportError).font(.footnote).foregroundStyle(Theme.bad)
                    }
                }
                .padding(.horizontal, Spacing.m).padding(.top, Spacing.xs).padding(.bottom, Spacing.xl)
                .readableColumn()
            }
            .scrollDismissesKeyboard(.interactively)
        }
        .navigationTitle(name.isEmpty ? "Plat" : name)
        .navigationBarTitleDisplayMode(.inline)
        .onDisappear(perform: save)
        .task {
            if showModel(of: record) { return }
            await loadPicture(of: record)
            if await model.refreshDishProgress() { changed() }
        }
        // A file of a dish has just arrived on the iPhone (asked by this screen or by another one).
        .onChange(of: model.libraryRevision) { _, _ in refreshRecord() }
        .sheet(item: $exportURL) { url in ShareSheet(items: [url]) }
        .quickLookPreview($arPreview)
        .confirmationDialog("Supprimer ce plat de l’iPhone ?", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Supprimer", role: .destructive) {
                DishLibrary.delete(record)
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
                            .accessibilityLabel(record.state == .ready ? "Quatre vues du modèle 3D" : "Une des vues prises pendant le scan")
                    }
                    .clipped()
            }
        } else {
            Stage {
                VStack(spacing: 10) {
                    Image(systemName: record.state == .ready ? "cube" : "hourglass").font(.largeTitle)
                        .foregroundStyle(Theme.textOnStage.opacity(0.4))
                        .accessibilityHidden(true)
                    Text(record.state == .ready ? "Chargement…" : "Le modèle n’est pas encore sur l’iPhone.")
                        .font(.footnote).foregroundStyle(Theme.textOnStage.opacity(0.7))
                }
                .frame(height: 220)
            }
        }
    }

    /// A dish without its model yet: where it stands, and the button that finishes it.
    private var unfinished: some View {
        let progress = model.dishProgress[record.id]
        // After a failed calculation nothing is left to send: the button asks for the model again.
        let restart = progress?.restart == true
        return VStack(alignment: .leading, spacing: Spacing.s) {
            Label(progress?.text ?? "Vérification auprès du calculateur…", systemImage: "hourglass")
                .font(.subheadline.weight(.semibold)).foregroundStyle(Theme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
            // What brings the model when the calculator cannot be asked, or that nothing will.
            if let advice = progress?.advice {
                Text(advice).font(.footnote).foregroundStyle(Theme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let fraction = progress?.fraction {
                ProgressView(value: fraction).tint(Theme.accent)
            }
            if progress?.canComplete == true {
                PrimaryButton(title: restart ? "Relancer le calcul" : "Terminer ce plat", icon: restart ? "arrow.clockwise" : "checkmark",
                              enabled: model.completingDish == nil) {
                    let dish = record
                    Task {
                        await model.complete(dish)
                        changed()
                    }
                }
                Text(restart ? "Le calculateur refait le modèle avec les vues qu’il a déjà."
                             : "Les vues restantes sont envoyées, puis le calculateur construit le modèle.")
                    .font(.footnote).foregroundStyle(Theme.textSecondary)
            }
        }
        .padding(Spacing.m).frame(maxWidth: .infinity, alignment: .leading)
        .cardSurface()
        .task {
            while !Task.isCancelled {
                // When the model arrives, `libraryRevision` changes and this screen reads the dish again.
                if await model.refreshDishProgress() { changed() }
                try? await Task.sleep(nanoseconds: 4_000_000_000)
            }
        }
    }

    private var facts: some View {
        VStack(spacing: 0) {
            if let date = record.date {
                fact("Scanné le", date.formatted(date: .long, time: .shortened))
                Divider()
            }
            fact("Vues prises", "\(record.frames)")
            if let quality = qualityWord {
                Divider()
                fact("Qualité du modèle", quality)
            }
            // Only when a real width was typed before this scan: what the model measures next to it.
            if let check = record.scaleCheck {
                Divider()
                fact("Largeur mesurée", check.text)
            }
        }
        .font(.subheadline)
        .padding(.horizontal, 14)
        .cardSurface(radius: Radius.field)
    }

    /// The calculator's verdict on the final model, in one word; nil when it gave none.
    private var qualityWord: String? {
        switch record.outcome?.verdict?.level ?? "" {
        case "good": return "Bonne"
        case "fair": return "Correcte"
        case "poor": return "Insuffisante"
        default: return nil
        }
    }

    /// What the final calculation could not do as planned, in the calculator's own sentences.
    @ViewBuilder private func outcomeNotes(_ outcome: FinalOutcome) -> some View {
        if !outcome.fallbacks.isEmpty {
            VStack(alignment: .leading, spacing: Spacing.xs) {
                ForEach(outcome.fallbacks, id: \.self) { fallback in
                    Label(fallback.message, systemImage: "exclamationmark.triangle")
                        .font(.footnote).foregroundStyle(Theme.textPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(14).frame(maxWidth: .infinity, alignment: .leading)
            .cardSurface(radius: Radius.field)
        }
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
            if let arModel = record.arModel {
                // iOS shows the textured model itself: turned by hand, or placed on the table at real size.
                PrimaryButton(title: "Voir sur votre table", icon: "arkit") { showOnTable(arModel) }
                    .accessibilityHint("Ouvre le modèle avec ses vraies couleurs, en 3D ou en réalité augmentée.")
            }
            if let model = record.model {
                // Shared under the name of the dish: sent as "model.glb", two dishes could not be told apart.
                Button { exportURL = namedCopy(of: model) ?? model } label: {
                    QuietButtonLabel(title: "Partager le modèle 3D", icon: "square.and.arrow.up")
                }
            }
            Button(action: exportAll) {
                QuietButtonLabel(title: exporting ? "Préparation du dossier…" : "Exporter le dossier complet",
                                 icon: exporting ? "hourglass" : "archivebox")
            }
            .disabled(exporting)
            Button(role: .destructive) { confirmDelete = true } label: {
                Label("Supprimer", systemImage: "trash")
                    .font(.subheadline.weight(.semibold)).frame(maxWidth: .infinity).frame(minHeight: 48)
                    .foregroundStyle(Theme.bad)
            }
        }
        .buttonStyle(PressableStyle())
    }

    /// Read the dish again from the iPhone and show what has arrived: its model in the 3D viewer, or at
    /// least its result picture, and the actions that need its files.
    private func refreshRecord() {
        guard let fresh = DishLibrary.all().first(where: { $0.id == record.id }) else { return }
        if fresh != record { record = fresh }
        if modelShown || showModel(of: fresh) { return }
        Task { await loadPicture(of: fresh) }
    }

    /// The result picture when there is one, else one of the views taken during the scan.
    private func loadPicture(of dish: DishRecord) async {
        picture = await Task.detached(priority: .userInitiated) {
            dish.picture.flatMap { UIImage(contentsOfFile: $0.path) } ?? DishLibrary.photo(for: dish)
        }.value
    }

    /// Put the dish's final model in the 3D viewer, if it is on the iPhone.
    @discardableResult private func showModel(of dish: DishRecord) -> Bool {
        guard let url = dish.geometry, let data = try? Data(contentsOf: url), let geometry = try? PreviewGeometry.decode(data) else { return false }
        renderer.followPhone = false
        renderer.mode = mode
        renderer.show(geometry)
        modelShown = true
        return true
    }

    /// iOS's viewer uses the name of the file as its title: the name of the dish, rather than "model".
    private func showOnTable(_ model: URL) {
        arPreview = namedCopy(of: model) ?? model   // without the copy the viewer still opens, under the file's own name
    }

    /// A copy of one of the dish's files under the name of the dish, in the temporary folder: what iOS shows
    /// as a title, and what the person who receives the file sees. nil when the copy cannot be made.
    private func namedCopy(of file: URL) -> URL? {
        let clean = name.trimmingCharacters(in: .whitespacesAndNewlines).replacing("/", with: "-").replacing(":", with: "-")
        let named = URL.temporaryDirectory.appending(path: "\(clean.isEmpty ? "Plat" : clean).\(file.pathExtension)")
        do {
            if FileManager.default.fileExists(atPath: named.path(percentEncoded: false)) {
                try FileManager.default.removeItem(at: named)
            }
            try FileManager.default.copyItem(at: file, to: named)
            return named
        } catch {
            return nil
        }
    }

    private func save() {
        let clean = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty, clean != record.name else { return }
        DishLibrary.rename(record, to: clean)
        record.name = clean
        changed()
    }

    /// Everything the iPhone keeps of this dish, as one file to share. Made away from the main thread: with
    /// its views a dish weighs a few hundred megabytes, and the screen would not answer meanwhile.
    private func exportAll() {
        guard !exporting else { return }
        exporting = true
        let id = record.id
        Task {
            do {
                exportURL = try await Task.detached(priority: .userInitiated) { try SessionStore(resuming: id).exportZip() }.value
                exportError = nil
            } catch {
                exportError = "Export impossible : \(error.localizedDescription)"
            }
            exporting = false
        }
    }
}
