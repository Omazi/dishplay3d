import SwiftUI

/// A scan that was interrupted (app closed, Wi-Fi lost): send the rest or drop it.
struct PendingScanCard: View {
    @EnvironmentObject var model: AppModel
    @State private var confirmDiscard = false

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.s) {
            if let p = model.pendingScan {
                Label("Scan interrompu", systemImage: "exclamationmark.arrow.triangle.2.circlepath")
                    .font(.headline).foregroundStyle(Theme.warn)
                Text(p.pending > 0 ? "\(p.pending) vues sur \(p.total) n’ont pas été envoyées au calculateur."
                                   : "Les \(p.total) vues sont sur le calculateur, mais la finition n’a pas été lancée.")
                    .font(.subheadline).foregroundStyle(Theme.textPrimary).fixedSize(horizontal: false, vertical: true)
            }
            if let t = model.pendingText {
                HStack(spacing: 10) {
                    if model.pendingBusy { ProgressView() }
                    Text(t).font(.footnote).foregroundStyle(Theme.textSecondary).fixedSize(horizontal: false, vertical: true)
                }
            }
            if model.pendingScan != nil {
                ActionRow {
                    SmallButton(title: "Envoyer et terminer", icon: "arrow.up.circle") { Task { await model.resumePending() } }
                        .disabled(model.pendingBusy || !model.paired)
                    SmallButton(title: "Abandonner", icon: "trash") { confirmDiscard = true }
                        .disabled(model.pendingBusy)
                }
            }
        }
        .padding(18).frame(maxWidth: .infinity, alignment: .leading)
        .cardSurface()
        .confirmationDialog("Abandonner ce scan ?", isPresented: $confirmDiscard, titleVisibility: .visible) {
            Button("Abandonner le scan", role: .destructive) { model.discardPending() }
            Button("Le garder", role: .cancel) {}
        } message: {
            Text("Les vues prises pour ce plat seront effacées de l’iPhone.")
        }
    }
}
