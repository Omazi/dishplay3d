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
    /// Whether the linked calculator answered the last time it was asked; nil while that is not known.
    @Published private(set) var reachable: Bool?
    /// The linked calculator answered and is older than this app expects (engine before p1-0.11.0): it cannot
    /// take a new scan while it finishes a dish. False while nothing is known.
    @Published private(set) var calculatorOutdated = false
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
        #if DEBUG
        // Screen check: linked to a calculator that does not answer (nothing listens on that port).
        if UITestMode.paired, let nowhere = URL(string: "https://127.0.0.1:9") {
            transport = ScanTransport(baseURL: nowhere, fingerprint: String(repeating: "0", count: 64), token: "screen-check")
            paired = true
            if UITestMode.scanMoment != nil { screen = .scan }
        }
        #endif
        // Scans abandoned with an earlier version of the app were only hidden: their views leave the iPhone now.
        SessionStore.removeLeftovers()
        // The views of the scans already on the iPhone leave its backups (the new ones never enter them).
        SessionStore.keepViewsOutOfBackups()
        pendingScan = SessionStore.unfinished()
    }

    func refreshPending() { pendingScan = SessionStore.unfinished() }

    /// The person gives the interrupted scan up: its views are removed from the iPhone, as the card says.
    func discardPending() {
        if let p = pendingScan { SessionStore.delete(localID: p.localID) }
        pendingText = nil
        refreshPending()
    }

    /// Send the views that never reached the calculator, then ask it for the final model.
    func resumePending() async {
        guard let p = pendingScan, let t = transport, !pendingBusy else { return }
        pendingBusy = true
        defer { pendingBusy = false }
        do {
            let store = try SessionStore(resuming: p.localID)
            pendingText = "Réouverture du scan sur le calculateur…"
            // Needed by a calculator older than the queue, which answers 409 here while it finishes another dish;
            // harmless with a newer one, which keeps the views and the request whatever it is doing.
            _ = try await t.resumeWorker(sessionID: p.serverSessionID)
            var sent = 0
            let total = store.pendingCount
            while let fid = store.nextPending() {
                let env = try store.envelope(frameID: fid, serverSessionID: p.serverSessionID)
                try await t.putFrame(sessionID: p.serverSessionID, frameID: fid, envelope: env)
                store.markSent(fid)
                sent += 1
                pendingText = "Envoi des vues \(sent)/\(total)…"
            }
            let answer = try await t.finish(sessionID: p.serverSessionID)
            store.markFinishRequested()
            pendingText = answer.queued
                ? "Le calculateur termine un autre plat : celui-ci passera ensuite, tout seul. Il apparaîtra dans Mes plats quand son modèle sera prêt."
                : "Finition lancée sur le calculateur. Le plat apparaîtra dans Mes plats quand son modèle sera prêt."
            pendingScan = nil
        } catch let TransportError.http(code, _) where code == 404 {
            pendingText = "Le calculateur ne connaît plus ce scan. Vous pouvez l’abandonner."
        } catch let TransportError.http(code, _) where code == 409 {
            pendingText = Self.busyText
        } catch {
            pendingText = Self.explain(error, brief: true)
        }
    }

    /// Said when a calculator without a queue refuses a dish because it is finishing another one.
    static let busyText = "Le calculateur termine un autre plat. Réessayez quand il aura fini."

    /// Where an unfinished dish stands, in words for the library.
    struct DishProgress: Equatable {
        var text: String
        /// What the person can do about it, when the first line alone would leave them without a next step
        /// (calculator switched off, scan unknown to it). Shown on the dish screen, under the first line.
        var advice: String?
        var fraction: Double?
        /// The dish screen shows its button.
        var canComplete: Bool
        /// The final calculation failed: the button asks for it again (nothing is left to send).
        var restart = false

        init(text: String, advice: String? = nil, fraction: Double?, canComplete: Bool, restart: Bool = false) {
            self.text = text
            self.advice = advice
            self.fraction = fraction
            self.canComplete = canComplete
            self.restart = restart
        }

        /// From what the calculator answers about the dish (`DishStanding`, in ScanCore, where it is tested).
        init(_ standing: DishStanding) {
            text = standing.text
            advice = nil
            fraction = standing.fraction
            canComplete = standing.action != nil
            restart = standing.action == .restart
        }

        /// The calculator cannot be asked: the dish keeps the state the iPhone knows, and one line says what
        /// brings its model.
        static func withoutCalculator(_ dish: DishRecord, linked: Bool) -> DishProgress {
            let advice: String
            if !linked {
                advice = "Reliez le calculateur dans Réglages pour terminer ce plat."
            } else if dish.state == .processing {
                advice = "Calculateur injoignable. Allumez-le : le modèle arrivera tout seul."
            } else {
                advice = "Calculateur injoignable. Allumez-le pour terminer ce plat."
            }
            return DishProgress(text: dish.ownStateText, advice: advice, fraction: nil, canComplete: false)
        }

        /// The calculator answers, and does not have this scan (or never had it): only the iPhone's copy is left.
        static func lost(_ text: String) -> DishProgress {
            DishProgress(text: text, advice: "Ce scan ne peut plus être terminé. Supprimez-le, puis scannez le plat de nouveau.",
                         fraction: nil, canComplete: false)
        }
    }

    @Published private(set) var dishProgress: [String: DishProgress] = [:]
    @Published private(set) var completingDish: String?
    /// Goes up each time a file of a dish arrives on the iPhone: the screens that show a dish read it again.
    @Published private(set) var libraryRevision = 0

    /// Ask the calculator about every dish without a model. Returns true when a model was downloaded.
    func refreshDishProgress() async -> Bool {
        var received = false
        var next: [String: DishProgress] = [:]
        for dish in DishLibrary.all() where dish.state != .ready {
            if completingDish == dish.id, let current = dishProgress[dish.id] { next[dish.id] = current; continue }
            guard let sid = dish.serverSessionID else {
                next[dish.id] = .lost("Jamais envoyé au calculateur")
                continue
            }
            guard let t = transport else {
                next[dish.id] = .withoutCalculator(dish, linked: false)
                continue
            }
            do {
                let info = try await t.sessionInfo(sessionID: sid)
                if info.ready {
                    if await download(dish: dish, sessionID: sid, transport: t, outcome: info.outcome) { received = true }
                } else {
                    // Waiting its turn (with its place), being calculated, failed (with the calculator's sentence
                    // and a button to ask again), views to send, or stopped.
                    next[dish.id] = DishProgress(DishStanding(info, pendingViews: dish.pendingViews))
                }
            } catch let TransportError.http(code, _) where code == 404 {
                next[dish.id] = .lost("Inconnu du calculateur")
            } catch {
                // Its own state stays in view: with the calculator off, every dish used to read "Calculateur
                // injoignable" and nothing told which one still had views to send.
                next[dish.id] = .withoutCalculator(dish, linked: true)
            }
        }
        if next != dishProgress { dishProgress = next }
        // Finished dishes that miss a file. Only when the calculator is known to answer, and no further than the
        // first dish it does not answer for: otherwise every dish would wait for its own time-out.
        if reachable == true {
            let dishes = DishLibrary.all()
            for dish in dishes where dish.state == .ready {
                guard let arrived = await completeFiles(of: dish) else { break }
                if arrived { received = true }
            }
            await sendNames(of: dishes)
        }
        if received { libraryRevision += 1 }
        return received
    }

    /// Dishes whose name the calculator did not take since the app was opened (an older calculator, or a dish
    /// it no longer knows): not asked again until the app is opened again.
    private var namesNotTaken: Set<String> = []

    /// The names given to the dishes go to the calculator: on the PC a dish is otherwise a folder named after a
    /// date, and nobody can tell which one is the tajine. Sent from here, so that a name given while the
    /// calculator was off reaches it later.
    private func sendNames(of dishes: [DishRecord]) async {
        guard let t = transport else { return }
        for dish in dishes where !namesNotTaken.contains(dish.id) {
            guard let sid = dish.serverSessionID, let name = dish.nameToSend else { continue }
            do {
                try await t.setName(sessionID: sid, name: name)
                SessionStore.markNameSent(name, in: dish.root)
            } catch is TransportError {
                namesNotTaken.insert(dish.id)
            } catch {
                return   // the calculator is away: the names wait for the next time
            }
        }
    }

    /// How many times the missing files of a dish were asked for since the app was opened.
    private var fileRequests: [String: Int] = [:]
    /// Dishes whose missing files are being fetched right now (several screens ask at the same time).
    private var fileFetches: Set<String> = []

    /// A finished dish can miss some of its files: a download was cut, or the dish was received by an earlier
    /// version of the app that did not know them (the model for augmented reality). Returns true when a file
    /// arrived, false when there was nothing to do, nil when the calculator did not answer.
    private func completeFiles(of dish: DishRecord) async -> Bool? {
        var wanted: [String] = []
        if dish.arModel == nil { wanted.append("model.usdz") }
        if dish.model == nil { wanted.append("model.glb") }
        if dish.geometry == nil { wanted.append("final_preview.dpg") }
        guard !wanted.isEmpty, !fileFetches.contains(dish.id), fileRequests[dish.id, default: 0] < 2,
              let t = transport, let sid = dish.serverSessionID else { return false }
        fileFetches.insert(dish.id)
        defer { fileFetches.remove(dish.id) }
        let files: [String]
        do {
            files = try await t.artifacts(sessionID: sid)
        } catch is TransportError {
            // The calculator answered, but not with this dish's files (it no longer knows the dish, for example).
            fileRequests[dish.id, default: 0] += 1
            return false
        } catch {
            return nil
        }
        fileRequests[dish.id, default: 0] += 1
        guard let store = try? SessionStore(resuming: dish.id) else { return false }
        var arrived = false
        for name in wanted where files.contains(name) {
            if let data = try? await t.download("sessions/\(sid)/artifacts/\(name)"), (try? store.saveArtifact(name: name, data: data)) != nil {
                arrived = true
            }
        }
        return arrived
    }

    /// Send the views still on the iPhone, then ask for the final model of this dish (again, after a failure).
    func complete(_ dish: DishRecord) async {
        guard completingDish == nil, let t = transport, let sid = dish.serverSessionID else { return }
        completingDish = dish.id
        defer { completingDish = nil }
        func say(_ text: String, _ fraction: Double? = nil) { dishProgress[dish.id] = DishProgress(text: text, fraction: fraction, canComplete: false) }
        do {
            let store = try SessionStore(resuming: dish.id)
            say("Réouverture du scan sur le calculateur…")
            // See `resumePending`: an older calculator needs this, and refuses it (409) while it finishes another dish.
            _ = try await t.resumeWorker(sessionID: sid)
            let total = store.pendingCount
            var sent = 0
            while let fid = store.nextPending() {
                let env = try store.envelope(frameID: fid, serverSessionID: sid)
                try await t.putFrame(sessionID: sid, frameID: fid, envelope: env)
                store.markSent(fid)
                sent += 1
                say("Envoi des vues \(sent)/\(total)", Double(sent) / Double(max(total, 1)))
            }
            let answer = try await t.finish(sessionID: sid)
            store.markFinishRequested()
            say(answer.queued ? QueueWording.waiting(answer.position) : "Calcul du modèle lancé…")
        } catch let TransportError.http(code, _) where code == 409 {
            dishProgress[dish.id] = DishProgress(text: Self.busyText, fraction: nil, canComplete: true)
        } catch {
            dishProgress[dish.id] = DishProgress(text: Self.explain(error, brief: true), fraction: nil, canComplete: true)
        }
    }

    private func download(dish: DishRecord, sessionID sid: String, transport t: ScanTransport, outcome: FinalOutcome?) async -> Bool {
        guard let files = try? await t.artifacts(sessionID: sid), let store = try? SessionStore(resuming: dish.id) else { return false }
        // What the calculator says of the final model is kept with the dish, for the screens to show.
        if let outcome { store.saveOutcome(outcome) }
        var got = false
        for name in Self.keptFiles where files.contains(name) {
            if let d = try? await t.download("sessions/\(sid)/artifacts/\(name)"), (try? store.saveArtifact(name: name, data: d)) != nil { got = true }
        }
        return got
    }

    /// The files of a finished dish the app fetches and keeps: the model in the app's own format, its picture,
    /// the two files that are shared or opened by iOS, and the report (verdict, check of the real width). The
    /// calculator makes others (point cloud, untextured surface): nothing in the app reads them, so they stay
    /// on the PC instead of filling the iPhone.
    static let keptFiles = ["final_preview.dpg", "apercu.png", "model.glb", "model.usdz", "report.json"]

    var lidarSupported: Bool { ARSessionController.lidarSupported }
    var trackingSupported: Bool {
        #if DEBUG
        if UITestMode.sessions != nil { return true }
        #endif
        return ARSessionController.worldTrackingSupported
    }

    func handle(url: URL) {
        guard let link = PairingLink(url: url) else {
            fail("Ce QR code n’est pas celui d’un calculateur DishPlay. Scannez celui que le calculateur affiche sur le PC.")
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
            fail("Adresse attendue, comme l’affiche le calculateur : https://adresse-du-pc:8765")
            return
        }
        let fp = fingerprint.lowercased().filter(\.isHexDigit)
        guard fp.count == 64 else { fail("Empreinte : les 64 caractères affichés par le calculateur."); return }
        guard code.count == 6 else { fail("Code : les 6 chiffres affichés par le calculateur."); return }
        busy = true
        message = nil
        defer { busy = false; step = nil }
        let t = ScanTransport(baseURL: url, fingerprint: fp, token: nil, requestTimeout: 8)
        do {
            step = "1/2 · Recherche du calculateur \(url.host ?? "")…"
            _ = try await t.health()
            step = "2/2 · Envoi du code…"
            let token = try await t.pair(code: code, device: UIDevice.current.model)
            Keychain.save(token, account: url.absoluteString)
            UserDefaults.standard.set(url.absoluteString, forKey: "calc.url")
            UserDefaults.standard.set(fp, forKey: "calc.fp")
            transport = t
            paired = true
            messageIsError = false
            message = "Calculateur relié. Vous pouvez scanner un plat."
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
        guard let t = transport else { healthText = nil; reachable = nil; calculatorOutdated = false; return }
        do {
            let (h, rtt) = try await t.health()
            healthText = "Il répond en \(Int(rtt * 1000)) ms · moteur \(h.engine)"
            reachable = true
            calculatorOutdated = !EngineVersion.hasQueue(h.engine)
        } catch {
            healthText = Self.explain(error)
            reachable = false
        }
    }

    /// Stop using the linked calculator. Its token leaves the iPhone's keychain too: it used to stay there.
    func forget() {
        if let t = transport { Keychain.delete(account: t.baseURL.absoluteString) }
        if let saved = UserDefaults.standard.string(forKey: "calc.url") { Keychain.delete(account: saved) }
        transport?.disconnectEvents()
        transport = nil
        paired = false
        healthText = nil
        reachable = nil
        calculatorOutdated = false
        UserDefaults.standard.removeObject(forKey: "calc.url")
        UserDefaults.standard.removeObject(forKey: "calc.fp")
    }

    /// One sentence, in French, for what went wrong when talking to the calculator. `brief`: for a card or the
    /// scan screen, where there is room for one line; otherwise with what to check (settings, linking).
    static func explain(_ error: Error, brief: Bool = false) -> String {
        let ns = error as NSError
        if ns.domain == NSURLErrorDomain {
            switch ns.code {
            case NSURLErrorCancelled, NSURLErrorServerCertificateUntrusted, NSURLErrorSecureConnectionFailed,
                 NSURLErrorServerCertificateHasBadDate, NSURLErrorServerCertificateHasUnknownRoot, NSURLErrorClientCertificateRejected:
                // The calculator at this address does not show the key the iPhone was linked with.
                return brief ? "Le calculateur a changé : reliez-le de nouveau dans Réglages."
                    : "Le calculateur répond, mais sa clé de sécurité n’est plus celle du QR code scanné. Reliez-le de nouveau avec le QR code qu’il affiche en ce moment."
            case NSURLErrorTimedOut:
                return brief ? "Le calculateur ne répond pas."
                    : "Le calculateur ne répond pas. À vérifier : le PC est allumé et le calculateur lancé ; l’iPhone est sur le même Wi‑Fi que le PC (pas un réseau invité) ; « Réseau local » est activé pour DishPlay Scan dans les Réglages de l’iPhone ; sur le PC, ce Wi‑Fi est un réseau « privé »."
            case NSURLErrorCannotConnectToHost:
                return brief ? "Le calculateur n’est pas lancé sur le PC."
                    : "Le PC répond, mais le calculateur n’y est pas lancé. Lancez-le sur le PC, puis touchez « Tester »."
            case NSURLErrorNotConnectedToInternet, NSURLErrorNetworkConnectionLost, NSURLErrorCannotFindHost:
                return brief ? "L’iPhone n’est pas sur le réseau du PC."
                    : "L’iPhone n’est pas sur le réseau du PC : vérifiez le Wi‑Fi et, dans les Réglages de l’iPhone, l’autorisation « Réseau local » de DishPlay Scan."
            default: break
            }
        }
        guard let refusal = error as? TransportError else {
            // Not a case the app knows: the system's own words, with its code for whoever helps.
            return "\(error.localizedDescription) (code \(ns.code))"
        }
        guard case .http(let status, let detail) = refusal else { return refusal.localizedDescription }
        switch status {
        case 403:
            return "Code refusé : utilisez celui que le calculateur affiche en ce moment (il change à chaque démarrage)."
        case 429:
            // A calculator that keeps a queue says how long to wait, in French; an older one stays closed.
            return detail.hasPrefix("Trop d") ? detail : "Trop d’essais : redémarrez le calculateur pour obtenir un nouveau code."
        case 401:
            // Never "restart the calculator" here: it may be in the middle of another dish, which that would stop.
            return "Le calculateur ne reconnaît plus cet iPhone. Reliez-le de nouveau dans Réglages."
        case 404:
            return "Le calculateur ne connaît plus ce scan."
        case 409:
            return busyText
        case 507:
            // The PC has no room left: the calculator's own sentence says so and what to do.
            return detail.isEmpty ? "Le PC n’a plus de place pour enregistrer ce scan : libérez de la place sur son disque." : detail
        default:
            // Its other refusals are written in English for developers: they are not shown.
            return "Le calculateur n’a pas accepté la demande. Réessayez dans un instant."
        }
    }
}
