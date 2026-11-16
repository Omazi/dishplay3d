import Foundation
import ScanCore
import UIKit

/// Pairing with the calculator (URL + certificate fingerprint + token) and capability diagnosis.
@MainActor
final class AppModel: ObservableObject {
    enum Screen { case connect, scan }

    @Published var screen: Screen = .connect
    @Published var baseURLText: String = UserDefaults.standard.string(forKey: "calc.url") ?? ""
    @Published var fingerprint: String = UserDefaults.standard.string(forKey: "calc.fp") ?? ""
    @Published var code = ""
    @Published var useLidar: Bool = UserDefaults.standard.bool(forKey: "useLidar") {
        didSet { UserDefaults.standard.set(useLidar, forKey: "useLidar") }
    }
    @Published var referenceWidthCm = ""
    @Published private(set) var paired = false
    @Published private(set) var busy = false
    @Published private(set) var message: String?
    @Published private(set) var healthText: String?
    @Published private(set) var transport: ScanTransport?

    init() {
        if let url = URL(string: baseURLText), fingerprint.count == 64, let token = Keychain.load(account: baseURLText) {
            transport = ScanTransport(baseURL: url, fingerprint: fingerprint, token: token)
            paired = true
        }
    }

    var lidarSupported: Bool { ARSessionController.lidarSupported }
    var trackingSupported: Bool { ARSessionController.worldTrackingSupported }

    func handle(url: URL) {
        guard let link = PairingLink(url: url) else {
            message = "Lien de jumelage invalide (HTTPS, code à 6 chiffres et empreinte attendus)."
            return
        }
        baseURLText = link.baseURL.absoluteString
        fingerprint = link.fingerprint
        code = link.code
        Task { await pair() }
    }

    func pair() async {
        guard let url = URL(string: baseURLText.trimmingCharacters(in: .whitespaces)), url.scheme == "https" else {
            message = "Adresse attendue : https://adresse-du-pc:8765"
            return
        }
        let fp = fingerprint.lowercased().filter(\.isHexDigit)
        guard fp.count == 64 else { message = "Empreinte TLS : 64 caractères hexadécimaux, affichée par le calculateur."; return }
        busy = true
        defer { busy = false }
        let t = ScanTransport(baseURL: url, fingerprint: fp, token: nil)
        do {
            _ = try await t.health()
            let token = try await t.pair(code: code, device: UIDevice.current.model)
            Keychain.save(token, account: url.absoluteString)
            UserDefaults.standard.set(url.absoluteString, forKey: "calc.url")
            UserDefaults.standard.set(fp, forKey: "calc.fp")
            transport = t
            paired = true
            message = "Jumelé au calculateur."
            await checkHealth()
        } catch {
            message = Self.explain(error)
        }
    }

    func checkHealth() async {
        guard let t = transport else { healthText = nil; return }
        do {
            let (h, rtt) = try await t.health()
            healthText = "Calculateur joignable (\(Int(rtt * 1000)) ms) · moteur \(h.engine)"
        } catch {
            healthText = Self.explain(error)
        }
    }

    func forget() {
        transport = nil
        paired = false
        UserDefaults.standard.removeObject(forKey: "calc.url")
        UserDefaults.standard.removeObject(forKey: "calc.fp")
    }

    static func explain(_ error: Error) -> String {
        let ns = error as NSError
        if ns.domain == NSURLErrorDomain {
            switch ns.code {
            case NSURLErrorCancelled, NSURLErrorServerCertificateUntrusted, NSURLErrorSecureConnectionFailed:
                return "Certificat du calculateur différent de l’empreinte jumelée : rescanne le QR affiché par le PC."
            case NSURLErrorTimedOut, NSURLErrorCannotConnectToHost, NSURLErrorNetworkConnectionLost, NSURLErrorNotConnectedToInternet:
                return "Calculateur injoignable. Vérifie : même Wi-Fi, calculateur démarré, Réglages › DishPlay Scan › Réseau local activé, pare-feu du PC (port 8765), pas d’isolation des appareils sur le Wi-Fi."
            default: break
            }
        }
        return error.localizedDescription
    }
}
