import SwiftUI
import UIKit

/// Calculator link and capture options.
struct SettingsView: View {
    @AppStorage("preview.showProvenance") private var showProvenance = false
    @EnvironmentObject var model: AppModel
    @State private var manual = false

    var body: some View {
        NavigationStack {
            ZStack {
                ScreenBackground()
                ScrollView {
                    VStack(alignment: .leading, spacing: Spacing.m) {
                        computerCard
                        deviceCard
                        measureCard
                        Text("DishPlay Scan \(version)")
                            .font(.footnote).foregroundStyle(Theme.textSecondary)
                            .frame(maxWidth: .infinity)
                    }
                    .padding(.horizontal, Spacing.m).padding(.top, Spacing.xs).padding(.bottom, Spacing.xl)
                }
                .scrollDismissesKeyboard(.interactively)
            }
            .navigationTitle("Réglages")
        }
        .task { await model.checkHealth() }
    }

    private var version: String {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? ""
    }

    private var computerCard: some View {
        card {
            if model.paired {
                HStack(spacing: 14) {
                    Image(systemName: "desktopcomputer").font(.title2).foregroundStyle(Theme.good).accessibilityHidden(true)
                        .frame(width: 48, height: 48).background(Theme.good.opacity(0.14), in: Circle())
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Ordinateur relié").font(.headline).foregroundStyle(Theme.textPrimary)
                        Text(model.healthText ?? "Vérification…").font(.footnote).foregroundStyle(Theme.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Spacer(minLength: 0)
                }
                HStack(spacing: 10) {
                    SmallButton(title: "Tester", icon: "arrow.clockwise") { Task { await model.checkHealth() } }
                    SmallButton(title: "Changer d’ordinateur", icon: "xmark") { model.forget() }
                }
            } else {
                Text("Relier l’ordinateur").font(.headline).foregroundStyle(Theme.textPrimary)
                step(1, "Lancez le calculateur sur votre PC.")
                step(2, "Scannez son QR code avec l’appareil photo de l’iPhone.")
                if let st = model.step {
                    HStack(spacing: 10) { ProgressView(); Text(st).font(.footnote).foregroundStyle(Theme.textPrimary) }
                }
                if let m = model.message {
                    Text(m).font(.footnote.weight(.semibold)).foregroundStyle(model.messageIsError ? Theme.bad : Theme.good)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if model.messageIsError {
                    SmallButton(title: "Réglages › Réseau local", icon: "gear") {
                        if let u = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(u) }
                    }
                }
                DisclosureGroup("Saisie manuelle", isExpanded: $manual) {
                    VStack(spacing: 10) {
                        field("https://192.168.1.20:8765", text: $model.baseURLText, keyboard: .URL)
                        field("Code à 6 chiffres", text: $model.code, keyboard: .numberPad)
                        field("Empreinte (64 caractères)", text: $model.fingerprint, keyboard: .asciiCapable)
                        SmallButton(title: model.busy ? "Jumelage…" : "Jumeler", icon: "link") { Task { await model.pair() } }
                            .disabled(model.busy)
                    }
                    .padding(.top, 10)
                }
                .font(.subheadline).foregroundStyle(Theme.textPrimary).tint(Theme.textSecondary)
            }
        }
    }

    private var deviceCard: some View {
        card {
            if !model.trackingSupported {
                Label("Cet iPhone ne prend pas en charge le suivi AR.", systemImage: "xmark.octagon").foregroundStyle(Theme.bad)
            }
            Toggle(isOn: $showProvenance) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Colorer les zones estimées").font(.subheadline.weight(.semibold)).foregroundStyle(Theme.textPrimary)
                    Text("Teinte en bleu ou en rose ce qui n’a pas été mesuré directement. Sinon, le modèle garde ses vraies couleurs.")
                        .font(.footnote).foregroundStyle(Theme.textSecondary)
                }
            }
            .tint(Theme.accent)
            if model.lidarSupported {
                Toggle(isOn: $model.useLidar) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Utiliser le LiDAR").font(.subheadline.weight(.semibold)).foregroundStyle(Theme.textPrimary)
                        Text("Sinon, reconstruction à partir des images seules.").font(.footnote).foregroundStyle(Theme.textSecondary)
                    }
                }
                .tint(Theme.accent)
            }
        }
    }

    private var measureCard: some View {
        card {
            Text("Largeur réelle du contenant").font(.subheadline.weight(.semibold)).foregroundStyle(Theme.textPrimary)
            HStack {
                TextField("facultatif", text: $model.referenceWidthCm).keyboardType(.decimalPad)
                    .foregroundStyle(Theme.textPrimary)
                Text("cm").foregroundStyle(Theme.textSecondary)
            }
            .padding(Spacing.s).background(Theme.surfaceSunken, in: RoundedRectangle(cornerRadius: Radius.field))
            Text("Sert à vérifier l’échelle du modèle final.").font(.footnote).foregroundStyle(Theme.textSecondary)
        }
    }

    // MARK: pieces

    private func card<Content: View>(@ViewBuilder _ content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 14) { content() }
            .padding(18).frame(maxWidth: .infinity, alignment: .leading)
            .cardSurface()
    }

    private func step(_ n: Int, _ text: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Text("\(n)").font(.footnote.bold()).frame(minWidth: 24, minHeight: 24).background(Theme.accent, in: Circle()).foregroundStyle(Theme.onAccent)
            Text(text).font(.subheadline).foregroundStyle(Theme.textPrimary).fixedSize(horizontal: false, vertical: true)
        }
    }

    private func field(_ placeholder: String, text: Binding<String>, keyboard: UIKeyboardType) -> some View {
        TextField(placeholder, text: text).keyboardType(keyboard)
            .textInputAutocapitalization(.never).autocorrectionDisabled()
            .font(.footnote.monospaced()).foregroundStyle(Theme.textPrimary)
            .padding(Spacing.s).background(Theme.surfaceSunken, in: RoundedRectangle(cornerRadius: Radius.field))
    }
}
