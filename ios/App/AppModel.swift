import Foundation
import ScanCore
import UIKit

/// Pairing with the calculator (URL + certificate fingerprint + token) and capability diagnosis.
@MainActor
final class AppModel: ObservableObject {
    enum Screen { case connect, scan }

    @Published var screen: Screen = .connect
    /// Tab to show the next time the tab bar appears (e.g. the library right after a scan).
    var nextTab: AppTab?
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
    /// A scan interrupted by closing the app: its views are still on the iPhone.
    @Published private(set) var pendingScan: SessionStore.Unfinished?
    @Published private(set) var pendingText: String?
    @Published private(set) var pendingBusy = false

    init() {
        if let url = URL(string: baseURLText), fingerprint.count == 64, let token = Keychain.load(account: baseURLText) {
            transport = ScanTransport(baseURL: url, fingerprint: fingerprint, token: token)
            paired = true
        }
        pendingScan = SessionStore.unfinished()
    }

    func refreshPending() { pendingScan = SessionStore.unfinished() }

    func discardPending() {
        if let p = pendingScan, let store = try? SessionStore(resuming: p.localID) { store.markAbandoned() }
        pendingText = nil
        refreshPending()
    }

    /// Send the views that never reached the calculator, then start the finishing there.
    func resumePending() async {
        guard let p = pendingScan, let t = transport, !pendingBusy else { return }
        pendingBusy = true
        defer { pendingBusy = false }
        do {
            let store = try SessionStore(resuming: p.localID)
            pendingText = "Réouverture de la session sur le PC…"
            try await t.post("sessions/\(p.serverSessionID)/resume_worker")
            var sent = 0
            let total = store.pendingCount
            while let fid = store.nextPending() {
                let env = try store.envelope(frameID: fid, serverSessionID: p.serverSessionID)
                try await t.putFrame(sessionID: p.serverSessionID, frameID: fid, envelope: env)
                store.markSent(fid)
                sent += 1
                pendingText = "Envoi des vues \(sent)/\(total)…"
            }
            try await t.post("sessions/\(p.serverSessionID)/finish")
            store.markFinishRequested()
            pendingText = "Finition lancée sur le calculateur. Le plat apparaîtra dans Mes plats quand son modèle sera prêt."
            pendingScan = nil
        } catch {
            if let te = error as? TransportError, case .http(404, _) = te {
                pendingText = "Le PC ne connaît plus cette session (données déplacées ?). Vous pouvez l’ignorer."
            } else {
                pendingText = Self.explain(error)
            }
        }
    }

    /// Where an unfinished dish stands, in words for the library.
    struct DishProgress: Equatable {
        var text: String
        var fraction: Double?
        var canComplete: Bool
    }

    @Published private(set) var dishProgress: [String: DishProgress] = [:]
    @Published private(set) var completingDish: String?

    /// Ask the calculator about every dish without a model. Returns true when a model was downloaded.
    func refreshDishProgress() async -> Bool {
        var received = false
        var next: [String: DishProgress] = [:]
        for dish in DishLibrary.all() where dish.state != .ready {
            if completingDish == dish.id, let current = dishProgress[dish.id] { next[dish.id] = current; continue }
            guard let sid = dish.serverSessionID else {
                next[dish.id] = DishProgress(text: "Jamais envoyé au calculateur", fraction: nil, canComplete: false)
                continue
            }
            guard let t = transport else {
                next[dish.id] = DishProgress(text: "Calculateur non relié", fraction: nil, canComplete: false)
                continue
            }
            do {
                let info = try await t.sessionInfo(sessionID: sid)
                if info.ready {
                    if await download(dish: dish, sessionID: sid, transport: t) { received = true }
                } else if let done = info.done, let total = info.total, total > 1 {
                    let names = ["poses": "Recalage des vues", "depth": "Calcul du modèle", "neural": "Rendu neuronal"]
                    let stepKey = info.step ?? "depth"
                    let stepName = names[stepKey] ?? "Calcul du modèle"
                    next[dish.id] = DishProgress(text: "\(stepName) · \(done)/\(total)",
                                                 fraction: min(1, Double(done) / Double(total)), canComplete: false)
                } else if info.active && info.state == "finishing" {
                    next[dish.id] = DishProgress(text: "Calcul du modèle en cours…", fraction: nil, canComplete: false)
                } else if info.busyWithOther {
                    next[dish.id] = DishProgress(text: "En attente : un autre plat est en cours de calcul", fraction: nil, canComplete: false)
                } else if dish.pendingViews > 0 {
                    next[dish.id] = DishProgress(text: "\(dish.pendingViews) vues à envoyer", fraction: nil, canComplete: true)
                } else {
                    next[dish.id] = DishProgress(text: "Calcul arrêté", fraction: nil, canComplete: true)
                }
            } catch let TransportError.http(code, _) where code == 404 {
                next[dish.id] = DishProgress(text: "Inconnu du calculateur", fraction: nil, canComplete: false)
            } catch {
                next[dish.id] = DishProgress(text: "Calculateur injoignable", fraction: nil, canComplete: false)
            }
        }
        if next != dishProgress { dishProgress = next }
        return received
    }

    /// Send the views still on the iPhone, then start (or restart) the final calculation for this dish.
    func complete(_ dish: DishRecord) async {
        guard completingDish == nil, let t = transport, let sid = dish.serverSessionID else { return }
        completingDish = dish.id
        defer { completingDish = nil }
        func say(_ text: String, _ fraction: Double? = nil) { dishProgress[dish.id] = DishProgress(text: text, fraction: fraction, canComplete: false) }
        do {
            let store = try SessionStore(resuming: dish.id)
            say("Réouverture du scan sur le calculateur…")
            try await t.post("sessions/\(sid)/resume_worker")
            let total = store.pendingCount
            var sent = 0
            while let fid = store.nextPending() {
                let env = try store.envelope(frameID: fid, serverSessionID: sid)
                try await t.putFrame(sessionID: sid, frameID: fid, envelope: env)
                store.markSent(fid)
                sent += 1
                say("Envoi des vues \(sent)/\(total)", Double(sent) / Double(max(total, 1)))
            }
            try await t.post("sessions/\(sid)/finish")
            store.markFinishRequested()
            say("Calcul du modèle lancé…")
        } catch let TransportError.http(code, _) where code == 409 {
            dishProgress[dish.id] = DishProgress(text: "Un autre plat est en cours de calcul. Réessayez quand il sera terminé.", fraction: nil, canComplete: true)
        } catch {
            dishProgress[dish.id] = DishProgress(text: Self.explain(error), fraction: nil, canComplete: true)
        }
    }

    private func download(dish: DishRecord, sessionID sid: String, transport t: ScanTransport) async -> Bool {
        guard let files = try? await t.artifacts(sessionID: sid), let store = try? SessionStore(resuming: dish.id) else { return false }
        var got = false
        for name in ["final_preview.dpg", "apercu.png", "model.glb", "report.json"] where files.contains(name) {
            if let d = try? await t.download("sessions/\(sid)/artifacts/\(name)"), (try? store.saveArtifact(name: name, data: d)) != nil { got = true }
        }
        return got
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
        let code = " (code \(ns.code))"
        if ns.domain == NSURLErrorDomain {
            switch ns.code {
            case NSURLErrorCancelled, NSURLErrorServerCertificateUntrusted, NSURLErrorSecureConnectionFailed,
                 NSURLErrorServerCertificateHasBadDate, NSURLErrorServerCertificateHasUnknownRoot, NSURLErrorClientCertificateRejected:
                return "Le PC répond, mais son certificat ne correspond pas à l’empreinte du QR. Rescannez le QR affiché actuellement par le calculateur." + code
            case NSURLErrorTimedOut:
                return "Aucune réponse du PC en 8 s. Vérifiez : Réglages › DishPlay Scan › Réseau local activé ; Wi‑Fi du PC en profil « Privé » (pare‑feu Windows, port 8765) ; pas de réseau invité ; l’adresse du QR est bien celle du PC." + code
            case NSURLErrorCannotConnectToHost:
                return "Le PC refuse la connexion : le calculateur n’est pas lancé ou n’écoute pas sur ce port." + code
            case NSURLErrorNotConnectedToInternet, NSURLErrorNetworkConnectionLost, NSURLErrorCannotFindHost:
                return "iPhone non connecté au réseau du PC (Wi‑Fi coupé, 4G, ou autorisation Réseau local refusée)." + code
            default: break
            }
        }
        if let t = error as? TransportError, case .http(let status, let detail) = t {
            if status == 403 { return "Code de jumelage refusé : utilisez le code affiché actuellement par le calculateur (il change à chaque démarrage)." }
            if status == 429 { return "Trop d’essais : redémarrez le calculateur pour obtenir un nouveau code." }
            return "Le calculateur a refusé la demande (erreur \(status)). Relancez-le si le problème persiste. (Détail : \(detail))"
        }
        return error.localizedDescription + code
    }
}
