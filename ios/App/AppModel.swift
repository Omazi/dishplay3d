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
    @Published private(set) var messageIsError = false
    @Published private(set) var step: String?
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
            fail("Lien de jumelage invalide (HTTPS, code à 6 chiffres et empreinte attendus).")
            return
        }
        baseURLText = link.baseURL.absoluteString
        fingerprint = link.fingerprint
        code = link.code
        Task { await pair() }
    }

    func pair() async {
        guard !busy else { return }
        guard let url = URL(string: baseURLText.trimmingCharacters(in: .whitespaces)), url.scheme == "https", url.host != nil else {
            fail("Adresse attendue : https://adresse-du-pc:8765")
            return
        }
        let fp = fingerprint.lowercased().filter(\.isHexDigit)
        guard fp.count == 64 else { fail("Empreinte TLS : 64 caractères hexadécimaux, affichée par le calculateur."); return }
        guard code.count == 6 else { fail("Code de jumelage : 6 chiffres, affiché par le calculateur."); return }
        busy = true
        message = nil
        defer { busy = false; step = nil }
        let t = ScanTransport(baseURL: url, fingerprint: fp, token: nil, requestTimeout: 8)
        do {
            step = "1/2 · Contact du calculateur \(url.host ?? "")… (8 s max)"
            _ = try await t.health()
            step = "2/2 · Envoi du code de jumelage…"
            let token = try await t.pair(code: code, device: UIDevice.current.model)
            Keychain.save(token, account: url.absoluteString)
            UserDefaults.standard.set(url.absoluteString, forKey: "calc.url")
            UserDefaults.standard.set(fp, forKey: "calc.fp")
            transport = t
            paired = true
            messageIsError = false
            message = "Jumelé au calculateur. Vous pouvez ouvrir le scanner."
            await checkHealth()
        } catch {
            fail(Self.explain(error))
        }
    }

    private func fail(_ text: String) {
        messageIsError = true
        message = text
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
        let code = " [\(ns.domain) \(ns.code)]"
        if ns.domain == NSURLErrorDomain {
            switch ns.code {
            case NSURLErrorCancelled, NSURLErrorServerCertificateUntrusted, NSURLErrorSecureConnectionFailed,
                 NSURLErrorServerCertificateHasBadDate, NSURLErrorServerCertificateHasUnknownRoot, NSURLErrorClientCertificateRejected:
                return "Le PC répond, mais son certificat ne correspond pas à l’empreinte du QR. Rescanne le QR affiché actuellement par le calculateur." + code
            case NSURLErrorTimedOut:
                return "Aucune réponse du PC en 8 s. Vérifie : Réglages › DishPlay Scan › Réseau local activé ; Wi‑Fi du PC en profil « Privé » (pare‑feu Windows, port 8765) ; pas de réseau invité ; l’adresse du QR est bien celle du PC." + code
            case NSURLErrorCannotConnectToHost:
                return "Le PC refuse la connexion : le calculateur n’est pas lancé ou n’écoute pas sur ce port." + code
            case NSURLErrorNotConnectedToInternet, NSURLErrorNetworkConnectionLost, NSURLErrorCannotFindHost:
                return "iPhone non connecté au réseau du PC (Wi‑Fi coupé, 4G, ou autorisation Réseau local refusée)." + code
            default: break
            }
        }
        if let t = error as? TransportError, case .http(let status, let detail) = t {
            if status == 403 { return "Code de jumelage refusé : utilise le code affiché actuellement par le calculateur (il change à chaque démarrage)." }
            if status == 429 { return "Trop d’essais : redémarre le calculateur pour obtenir un nouveau code." }
            return "Calculateur : erreur \(status) \(detail)"
        }
        return error.localizedDescription + code
    }
}
