import SwiftUI
import UIKit

/// Home: connect to the computer, then open the scanner. One clear next action at the bottom.
struct ConnectionView: View {
    @EnvironmentObject var model: AppModel
    @State private var manual = false

    var body: some View {
        ZStack {
            LinearGradient(colors: [Color(red: 0.10, green: 0.09, blue: 0.13), .black], startPoint: .top, endPoint: .bottom)
                .ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    header
                    computerCard
                    if model.pendingScan != nil || model.pendingText != nil { pendingCard }
                    if model.lidarSupported || !model.trackingSupported { deviceCard }
                    measureCard
                }
                .padding(.horizontal, 20).padding(.top, 28).padding(.bottom, 120)
            }
            .scrollDismissesKeyboard(.interactively)
            VStack {
                Spacer()
                PrimaryButton(title: "Scanner un plat", icon: "viewfinder", enabled: model.paired && model.trackingSupported) {
                    model.screen = .scan
                }
                .padding(.horizontal, 20).padding(.bottom, 12)
            }
        }
        .preferredColorScheme(.dark)
        .task { await model.checkHealth() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            Image(systemName: "cube.transparent").font(.system(size: 40, weight: .medium)).foregroundStyle(Theme.accent).accessibilityHidden(true)
            Text("DishPlay Scan").font(.system(size: 34, weight: .bold, design: .rounded))
            Text("Tourne autour d’un plat, sa forme 3D se construit en direct.")
                .font(.body).foregroundStyle(.secondary)
        }
    }

    private var computerCard: some View {
        card {
            if model.paired {
                HStack(spacing: 14) {
                    Image(systemName: "desktopcomputer").font(.title2).foregroundStyle(Theme.good).accessibilityHidden(true)
                        .frame(width: 48, height: 48).background(Theme.good.opacity(0.15), in: Circle())
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Ordinateur relié").font(.headline)
                        Text(model.healthText ?? "Vérification…").font(.footnote).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Spacer(minLength: 0)
                }
                HStack(spacing: 10) {
                    smallButton("Tester", "arrow.clockwise") { Task { await model.checkHealth() } }
                    smallButton("Changer d’ordinateur", "xmark") { model.forget() }
                }
            } else {
                Text("Relier l’ordinateur").font(.headline)
                step(1, "Lance le calculateur sur ton PC.")
                step(2, "Scanne son QR code avec l’appareil photo de l’iPhone.")
                if let st = model.step {
                    HStack(spacing: 10) { ProgressView(); Text(st).font(.footnote) }
                }
                if let m = model.message {
                    Text(m).font(.footnote.weight(.semibold)).foregroundStyle(model.messageIsError ? Theme.bad : Theme.good)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if model.messageIsError {
                    smallButton("Réglages › Réseau local", "gear") {
                        if let u = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(u) }
                    }
                }
                DisclosureGroup("Saisie manuelle", isExpanded: $manual) {
                    VStack(spacing: 10) {
                        field("https://192.168.1.20:8765", text: $model.baseURLText, keyboard: .URL)
                        field("Code à 6 chiffres", text: $model.code, keyboard: .numberPad)
                        field("Empreinte (64 caractères)", text: $model.fingerprint, keyboard: .asciiCapable)
                        smallButton(model.busy ? "Jumelage…" : "Jumeler", "link") { Task { await model.pair() } }
                            .disabled(model.busy)
                    }
                    .padding(.top, 10)
                }
                .font(.subheadline).tint(.secondary)
            }
        }
    }

    private var pendingCard: some View {
        card {
            if let p = model.pendingScan {
                Label("Scan interrompu", systemImage: "exclamationmark.arrow.triangle.2.circlepath").font(.headline).foregroundStyle(Theme.warn)
                Text(p.pending > 0 ? "\(p.pending) vues sur \(p.total) n’ont pas été envoyées au PC." : "Les \(p.total) vues sont sur le PC, mais la finition n’a pas été lancée.")
                    .font(.subheadline).fixedSize(horizontal: false, vertical: true)
            }
            if let t = model.pendingText {
                HStack(spacing: 10) {
                    if model.pendingBusy { ProgressView() }
                    Text(t).font(.footnote).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
            }
            if model.pendingScan != nil {
                HStack(spacing: 10) {
                    smallButton("Envoyer et terminer", "arrow.up.circle") { Task { await model.resumePending() } }
                        .disabled(model.pendingBusy || !model.paired)
                    smallButton("Ignorer", "trash") { model.discardPending() }.disabled(model.pendingBusy)
                }
            }
        }
    }

    private var deviceCard: some View {
        card {
            if !model.trackingSupported {
                Label("Cet iPhone ne prend pas en charge le suivi AR.", systemImage: "xmark.octagon").foregroundStyle(Theme.bad)
            }
            if model.lidarSupported {
                Toggle(isOn: $model.useLidar) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Utiliser le LiDAR").font(.subheadline.weight(.semibold))
                        Text("Sinon, reconstruction à partir des images seules.").font(.footnote).foregroundStyle(.secondary)
                    }
                }
                .tint(Theme.accent)
            }
        }
    }

    private var measureCard: some View {
        card {
            Text("Largeur réelle du contenant").font(.subheadline.weight(.semibold))
            HStack {
                TextField("facultatif", text: $model.referenceWidthCm).keyboardType(.decimalPad)
                Text("cm").foregroundStyle(.secondary)
            }
            .padding(12).background(Color.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 12))
            Text("Sert à vérifier l’échelle du modèle final.").font(.footnote).foregroundStyle(.secondary)
        }
    }

    // MARK: pieces

    private func card<Content: View>(@ViewBuilder _ content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 14) { content() }
            .padding(18).frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.white.opacity(0.06), in: RoundedRectangle(cornerRadius: Theme.corner))
            .overlay(RoundedRectangle(cornerRadius: Theme.corner).strokeBorder(Color.white.opacity(0.08)))
    }

    private func step(_ n: Int, _ text: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Text("\(n)").font(.footnote.bold()).frame(width: 24, height: 24).background(Theme.accent, in: Circle()).foregroundStyle(.black)
            Text(text).font(.subheadline).fixedSize(horizontal: false, vertical: true)
        }
    }

    private func smallButton(_ title: String, _ icon: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: icon).font(.footnote.weight(.semibold))
                .padding(.horizontal, 14).frame(height: 38)
                .background(Color.white.opacity(0.10), in: Capsule()).foregroundStyle(.white)
        }
    }

    private func field(_ placeholder: String, text: Binding<String>, keyboard: UIKeyboardType) -> some View {
        TextField(placeholder, text: text).keyboardType(keyboard)
            .textInputAutocapitalization(.never).autocorrectionDisabled()
            .font(.footnote.monospaced())
            .padding(12).background(Color.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 12))
    }
}
