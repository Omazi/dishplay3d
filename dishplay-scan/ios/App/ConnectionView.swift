import SwiftUI

/// "Connexion au calculateur": pairing (QR link or manual entry), diagnosis, scan settings.
struct ConnectionView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        NavigationStack {
            Form {
                Section("Calculateur (même Wi-Fi)") {
                    if model.paired {
                        Label(model.baseURLText, systemImage: "desktopcomputer")
                        Text(model.healthText ?? "Vérification…").font(.footnote)
                        Button("Tester la connexion") { Task { await model.checkHealth() } }
                        Button("Oublier ce calculateur", role: .destructive) { model.forget() }
                    } else {
                        Text("Démarre le calculateur sur le PC, puis scanne son QR code avec l’appareil photo de l’iPhone. Ou saisis :")
                            .font(.footnote)
                        TextField("https://192.168.1.20:8765", text: $model.baseURLText)
                            .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                        TextField("Code de jumelage (6 chiffres)", text: $model.code).keyboardType(.numberPad)
                        TextField("Empreinte TLS (64 caractères)", text: $model.fingerprint)
                            .textInputAutocapitalization(.never).autocorrectionDisabled().font(.footnote.monospaced())
                        Button(model.busy ? "Jumelage…" : "Jumeler") { Task { await model.pair() } }.disabled(model.busy)
                    }
                    if let m = model.message { Text(m).font(.footnote).foregroundStyle(.secondary) }
                }
                Section("Capacités de cet iPhone") {
                    Label(model.trackingSupported ? "Suivi ARKit disponible" : "Suivi ARKit indisponible",
                          systemImage: model.trackingSupported ? "checkmark.circle" : "xmark.octagon")
                    Label(model.lidarSupported ? "LiDAR présent" : "Pas de LiDAR : reconstruction par stéréo des images (chemin standard)",
                          systemImage: "sensor")
                    if model.lidarSupported {
                        Toggle("Utiliser aussi le LiDAR (sinon stéréo seule)", isOn: $model.useLidar)
                    }
                    Text("Le chemin sans LiDAR fonctionne si le suivi ARKit est disponible et si le calculateur est joignable.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section("Mesure de contrôle (facultatif)") {
                    TextField("Largeur réelle du contenant, en cm", text: $model.referenceWidthCm).keyboardType(.decimalPad)
                    Text("Sert seulement à vérifier l’échelle dans le rapport final.").font(.footnote).foregroundStyle(.secondary)
                }
                Section {
                    Button("Ouvrir le scanner") { model.screen = .scan }
                        .disabled(!model.paired || !model.trackingSupported)
                }
            }
            .navigationTitle("DishPlay Scan")
            .task { await model.checkHealth() }
        }
    }
}
