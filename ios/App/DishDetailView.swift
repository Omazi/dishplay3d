import ScanCore
import SwiftUI

/// One dish: its picture, its name, and what can be done with its files.
struct DishDetailView: View {
    let dish: DishRecord
    let changed: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var name: String
    @State private var picture: UIImage?
    @State private var confirmDelete = false
    @State private var exportURL: URL?
    @State private var exportError: String?
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
            if let url = dish.geometry, let data = try? Data(contentsOf: url), let geometry = try? PreviewGeometry.decode(data) {
                renderer.followPhone = false
                renderer.mode = mode
                renderer.show(geometry)
                modelShown = true
                return
            }
            let url = dish.picture
            picture = await Task.detached(priority: .userInitiated) { url.flatMap { UIImage(contentsOfFile: $0.path) } }.value
        }
        .sheet(item: $exportURL) { url in ShareSheet(items: [url]) }
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
                .clipShape(.rect(cornerRadius: 22))
                .accessibilityLabel("Quatre vues du modèle 3D")
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
            if let model = dish.model {
                ShareLink(item: model) {
                    Label("Partager le modèle 3D", systemImage: "square.and.arrow.up")
                        .font(.headline).frame(maxWidth: .infinity).frame(height: 56)
                        .background(Theme.accent, in: Capsule()).foregroundStyle(.black)
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
