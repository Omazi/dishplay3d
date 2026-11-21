import RealityKit
import ScanCore
import SwiftUI
import UIKit

struct ARViewContainer: UIViewRepresentable {
    let arView: ARView
    func makeUIView(context: Context) -> ARView { arView }
    func updateUIView(_ uiView: ARView, context: Context) {}
}

/// Camera with the AR box on top, live reconstruction card below.
/// One instruction and one primary action per step.
struct ScannerView: View {
    @ObservedObject var controller: ScanController
    @ObservedObject private var box: BoundingBoxController
    @ObservedObject private var ar: ARSessionController
    @EnvironmentObject var model: AppModel
    @State private var expanded = false
    @State private var showSliders = false
    @State private var mode: PreviewMode = .both
    @State private var shareURL: URL?
    @State private var now = Date()
    @State private var openedAt = Date()
    @State private var askName = false
    @State private var confirmClose = false
    @State private var confirmFinish = false
    @State private var dishName = ""
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    private let ticker = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    init(controller: ScanController) {
        _controller = ObservedObject(wrappedValue: controller)
        _box = ObservedObject(wrappedValue: controller.box)
        _ar = ObservedObject(wrappedValue: controller.ar)
    }

    var body: some View {
        GeometryReader { geo in
            // While placing the box the camera needs the room: the preview is a slim card until the scan starts.
            let previewHeight = placing ? 112 : geo.size.height * (expanded ? 0.66 : 0.36)
            ZStack(alignment: .bottom) {
                VStack(spacing: 0) {
                    ZStack {
                        ARViewContainer(arView: controller.ar.arView).ignoresSafeArea(edges: .top)
                            .accessibilityIgnoresInvertColors()
                        // Everything floating over the camera is glass, and shares one container.
                        GlassGroup {
                            VStack(spacing: Spacing.s) {
                                topBar
                                if !expanded { instructionCard }
                                Spacer(minLength: 0)
                                if box.placed && !box.locked && !expanded { dimensions }
                                actionBar
                            }
                        }
                        .padding(.horizontal, Spacing.m).padding(.top, 6).padding(.bottom, Spacing.xxl)
                    }
                    Color.clear.frame(height: previewHeight - 28)
                }
                previewCard.frame(height: previewHeight)
            }
            .background(Color.black)
            .ignoresSafeArea(edges: .bottom)
            // Reduce Motion: the panels change size without the sliding spring.
            .animation(reduceMotion ? nil : .spring(duration: 0.35), value: expanded)
            .animation(reduceMotion ? nil : .spring(duration: 0.45), value: controller.phase)
            .animation(reduceMotion ? nil : .spring(duration: 0.3), value: showSliders)
        }
        .preferredColorScheme(.dark)
        // A scan lasts a minute or two without a touch: left alone, the iPhone dims and locks in the middle of
        // it, which stops the camera, breaks the tracking and loses the tour. Same while the model is computed.
        .onAppear { UIApplication.shared.isIdleTimerDisabled = true }
        .onDisappear { UIApplication.shared.isIdleTimerDisabled = false }
        .onReceive(ticker) { now = $0 }
        .sheet(item: $shareURL) { url in ShareSheet(items: [url]) }
        .onChange(of: controller.phase) { _, phase in
            if phase == .done { askName = true }
        }
        .confirmationDialog(closeTitle, isPresented: $confirmClose, titleVisibility: .visible) {
            switch controller.phase {
            case .scanning:
                Button("Mettre en pause") { controller.pause() }
                Button("Abandonner le scan", role: .destructive) { leave(abandon: true) }
                Button("Continuer le scan", role: .cancel) {}
            case .paused:
                // The pause card says the scan is kept: leaving must not drop it without a word.
                Button("Garder le scan pour plus tard") { leave(abandon: false) }
                Button("Abandonner le scan", role: .destructive) { leave(abandon: true) }
                Button("Rester", role: .cancel) {}
            case .uploadingRest:
                Button("Quitter") { leave(abandon: false) }
                Button("Rester", role: .cancel) {}
            default:
                Button("Quitter l’écran") { leave(abandon: false) }
                Button("Rester", role: .cancel) {}
            }
        } message: {
            Text(closeMessage)
        }
        .confirmationDialog("Le modèle risque d’être incomplet", isPresented: $confirmFinish, titleVisibility: .visible) {
            Button("Continuer le scan", role: .cancel) {}
            Button("Terminer quand même") { controller.finish() }
        } message: {
            Text(verdict.text + ". Vous pouvez continuer à tourner autour du plat avant de terminer.")
        }
        .alert("Nom du plat", isPresented: $askName) {
            TextField("Par exemple : Tajine aux pruneaux", text: $dishName)
            Button("Enregistrer", action: saveDishName)
            Button("Plus tard", role: .cancel) {}
        } message: {
            Text("Il apparaîtra sous ce nom dans Mes plats.")
        }
    }

    private func closeTapped() {
        Haptics.tap()
        switch controller.phase {
        case .scanning, .paused, .uploadingRest, .finishing: confirmClose = true
        case .placing, .needsNewBox, .done: leave(abandon: true)
        }
    }

    /// Back to the home screen. `abandon` marks an unfinished scan as dropped; without it the views
    /// stay on the iPhone and the scan can be sent later from the home screen.
    private func leave(abandon: Bool) {
        if abandon { controller.abandonIfUnfinished() }
        if controller.phase == .scanning { controller.pause() }
        model.refreshPending()
        if controller.phase == .finishing || controller.phase == .done { model.nextTab = .library }
        model.screen = .connect
    }

    private var closeTitle: String {
        switch controller.phase {
        case .scanning: return "Arrêter ce scan ?"
        case .paused: return "Quitter ce scan ?"
        case .uploadingRest: return "Quitter pendant l’envoi ?"
        default: return "Quitter pendant le calcul ?"
        }
    }

    private var closeMessage: String {
        switch controller.phase {
        case .scanning: return "Vous pouvez le mettre en pause pour le reprendre, ou l’abandonner."
        case .paused: return "Gardé, le scan reste sur l’iPhone et vous pourrez l’envoyer depuis l’accueil. Abandonné, il est retiré."
        case .uploadingRest: return "Les vues restantes sont gardées sur l’iPhone. Vous pourrez les envoyer depuis l’accueil."
        default: return "Le calcul continue sur le calculateur. Le plat apparaîtra dans Mes plats quand son modèle sera prêt."
        }
    }

    private func saveDishName() {
        if let id = controller.store?.localID { DishLibrary.rename(id: id, to: dishName) }
    }

    private var placing: Bool { controller.phase == .placing || controller.phase == .needsNewBox }

    // MARK: top bar

    private var topBar: some View {
        HStack(spacing: 10) {
            // Always answers a tap. While something is running it asks first instead of doing nothing.
            Button(action: closeTapped) {
                Image(systemName: "xmark").font(.subheadline.weight(.bold)).foregroundStyle(.white)
                    .frame(width: 44, height: 44).glass(Circle(), interactive: true)
            }
            .accessibilityLabel("Quitter le scan")
            HStack(spacing: 14) {
                StatusDot(text: trackingText.0, color: trackingText.1)
                StatusDot(text: computerText.0, color: computerText.1)
                if controller.phase != .placing {
                    Spacer(minLength: 0)
                    Label("\(controller.savedFrames)", systemImage: "photo.stack").font(.footnote.weight(.semibold).monospacedDigit())
                }
            }
            .padding(.horizontal, 14).frame(height: 44).frame(maxWidth: .infinity, alignment: .leading)
            .glass(Capsule())
        }
    }

    private var trackingText: (String, Color) {
        switch ar.tracking {
        case .normal: return ("Suivi", Theme.good)
        case .limited: return ("Suivi limité", Theme.warn)
        case .notAvailable: return ("Suivi perdu", Theme.bad)
        }
    }

    private var computerText: (String, Color) {
        controller.calculatorOnline ? ("PC", Theme.good) : ("PC injoignable", Theme.bad)
    }

    // MARK: instruction

    private var stepIndex: Int {
        switch controller.phase {
        case .placing, .needsNewBox: return box.placed ? 1 : 0
        case .scanning, .paused: return 2
        case .uploadingRest, .finishing, .done: return 3
        }
    }

    private var instruction: (title: String, detail: String?, color: Color) {
        if let e = controller.errorText, controller.phase != .scanning { return ("Un problème est survenu", e, Theme.bad) }
        switch controller.phase {
        case .placing:
            // Not in the first seconds: the calculator has not answered the first ping yet.
            if !controller.calculatorOnline && now.timeIntervalSince(openedAt) > 3 {
                return ("Calculateur injoignable", "Allumez le calculateur sur le PC et gardez l’iPhone sur le même Wi‑Fi : le scan pourra alors démarrer.", Theme.warn)
            }
            return box.placed
                ? ("Centrez la boîte sur le plat", "Glissez pour déplacer, pincez pour ajuster la taille. Les poignées règlent chaque côté.", .white)
                : ("Placez la boîte", "Touchez la table au pied du plat.", .white)
        case .needsNewBox:
            return ("Replacez la boîte", "Le suivi a redémarré : touchez la table au pied du plat.", Theme.warn)
        case .paused:
            return box.locked
                ? ("En pause", "Votre scan est conservé.", .white)
                : ("Modifiez la boîte", "« Recalculer » refait le modèle avec la nouvelle boîte. « Annuler » ne change rien.", .white)
        case .uploadingRest:
            return ("Envoi des dernières vues", "\(controller.store?.pendingCount ?? 0) restantes…", .white)
        case .finishing:
            return ("Finition du modèle", "Le calculateur assemble le modèle final.", .white)
        case .done:
            if let g = controller.lastGeometry, g.kind == "final", (g.triangle_count ?? 0) == 0 {
                return ("Aucun modèle obtenu", "Ce scan n’a pas donné de surface. Refaites-le en tournant lentement tout autour du plat.", Theme.bad)
            }
            return ("Modèle prêt", "Faites-le tourner du doigt, puis retrouvez-le dans Mes plats.", Theme.good)
        case .scanning:
            if !controller.calculatorOnline {
                return ("PC injoignable", "Les vues restent sur l’iPhone ; l’aperçu est figé.", Theme.bad)
            }
            switch controller.status.guidance {
            case .trackingLost?: return ("Suivi perdu", "Revenez lentement vers le plat.", Theme.bad)
            case .trackingLimited?: return ("Ralentissez", "Gardez la table dans l’image.", Theme.warn)
            case .frameTheDish?: return ("Recadrez", "Gardez toute la boîte dans l’image.", Theme.warn)
            case .slowDown?: return ("Ralentissez", "Un mouvement lent donne des vues nettes.", Theme.warn)
            case .tooDark?: return ("Trop sombre", "Ajoutez de la lumière douce.", Theme.warn)
            case .dontRotateInPlace?: return ("Déplacez-vous", "Ne pivotez pas sur place : marchez autour du plat.", Theme.warn)
            case .goHigher?: return ("Montez un peu", "Passez plus haut pour voir l’intérieur du plat.", .white)
            case .completeSide?: return ("Continuez le tour", "Remplissez les secteurs vides de l’anneau.", .white)
            default: return ("Tournez autour du plat", "Lentement, en gardant le plat dans l’image.", .white)
            }
        }
    }

    /// Compact on purpose: it sits on top of the camera image and must not hide the dish.
    private var instructionCard: some View {
        let i = instruction
        let scanning = controller.phase == .scanning || (controller.phase == .paused && box.locked)
        return VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 5) {
                ForEach(0..<4, id: \.self) { k in
                    Capsule().fill(k <= stepIndex ? Theme.accent : Color.white.opacity(0.22)).frame(height: 4)
                }
            }
            HStack(alignment: .center, spacing: 12) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(i.title).font(.headline).foregroundStyle(i.color).lineLimit(1).minimumScaleFactor(0.8)
                        .id(i.title)
                        .transition(reduceMotion ? AnyTransition.opacity : AnyTransition(.blurReplace))
                    if scanning, i.color == .white, let hint = sideHint {
                        Text(hint).font(.subheadline.weight(.semibold))
                            .foregroundStyle(controller.tourComplete ? verdict.color : Theme.accent).lineLimit(2).minimumScaleFactor(0.8)
                    } else if let d = i.detail, !d.isEmpty {
                        Text(d).font(.subheadline).foregroundStyle(.white.opacity(0.85)).lineLimit(2).minimumScaleFactor(0.85)
                    }
                    if scanning {
                        let ring = controller.scheduler.ring
                        Text("Tour \(ring.visitedAzimuths)/12 · vues hautes \(min(ring.highViews, 6))/6")
                            .font(.caption.monospacedDigit()).foregroundStyle(.white.opacity(0.7))
                    }
                }
                Spacer(minLength: 0)
                if scanning {
                    CoverageRingView(counts: controller.scheduler.ring.counts, azimuthDeg: controller.cameraAzimuthDeg)
                        .frame(width: 60, height: 60)
                }
            }
        }
        .padding(.horizontal, 14).padding(.vertical, 12).frame(maxWidth: .infinity, alignment: .leading)
        .glass(RoundedRectangle(cornerRadius: 20))
        .animation(reduceMotion ? nil : .smooth(duration: 0.3), value: i.title)
    }

    /// Which way to walk: the ring keeps the phone at the bottom, so "right" on the ring is the user's right.
    private var sideHint: String? {
        let az = controller.cameraAzimuthDeg * .pi / 180
        let h = Double(box.height)
        guard let s = controller.scheduler.ring.suggestion(currentCameraInObject: [cos(az), h / 2, sin(az)], boxHeight: h) else {
            // Every side has been seen. Whether that is enough is the calculator's verdict on the model itself.
            return verdict.text
        }
        if s.0 == .goHigher { return "↑ Passez au-dessus du plat" }
        return s.direction >= 0 ? "← Allez vers votre gauche" : "Allez vers votre droite →"
    }

    /// The calculator's judgement of the model built so far, in the user's words.
    private var verdict: (text: String, color: Color, good: Bool) {
        let q = controller.lastGeometry?.quality
        let issues = q?.issues ?? []
        let advice: String
        if issues.contains("box_too_low") {
            // The calculator keeps what rises a little above the box; beyond that the top of the dish is cut.
            advice = "le plat dépasse la boîte, montez-la (pause, puis Boîte)"
        } else if issues.contains("sides_missing") {
            advice = "il manque des côtés, continuez le tour"
        } else if issues.contains("holes") || issues.contains("fragmented") {
            advice = "des zones sont vides, repassez dessus lentement"
        } else if issues.contains("few_views") {
            advice = "pas assez de vues nettes, tournez plus lentement"
        } else if issues.contains("uniform_or_shiny") {
            advice = "surface unie ou brillante, ajoutez de la lumière douce"
        } else {
            advice = "continuez encore un peu"
        }
        switch q?.level {
        case "good": return ("Scan réussi : vous pouvez terminer", Theme.good, true)
        case "fair": return ("Scan correct : " + advice, Theme.warn, false)
        case "poor": return ("Scan insuffisant : " + advice, Theme.bad, false)
        default: return ("Analyse du modèle en cours…", .white, false)
        }
    }

    /// "Terminer" goes straight to the final model when the verdict is good; otherwise it asks first.
    private func finishTapped() {
        if verdict.good || controller.lastGeometry?.quality?.level == "fair" {
            controller.finish()
        } else {
            confirmFinish = true
        }
    }

    // MARK: box dimensions

    private var dimensions: some View {
        VStack(spacing: 10) {
            Button { showSliders.toggle() } label: {
                HStack(spacing: 0) {
                    dimTile("Largeur", box.width)
                    Divider().frame(height: 26).overlay(Color.white.opacity(0.2))
                    dimTile("Profondeur", box.depth)
                    Divider().frame(height: 26).overlay(Color.white.opacity(0.2))
                    dimTile("Hauteur", box.height)
                    Image(systemName: showSliders ? "chevron.down" : "slider.horizontal.3")
                        .font(.subheadline.weight(.semibold)).frame(width: 40)
                }
                .foregroundStyle(.white)
            }
            .accessibilityLabel("Dimensions de la boîte")
            .accessibilityHint(showSliders ? "Masque les réglages" : "Affiche les réglages")
            if showSliders {
                Button { box.replace() } label: {
                    Label("Replacer la boîte ailleurs", systemImage: "arrow.uturn.backward").font(.footnote.weight(.semibold))
                        .frame(maxWidth: .infinity).frame(height: 44).background(Color.white.opacity(0.12), in: Capsule()).foregroundStyle(.white)
                }
            }
            if showSliders {
                dimSlider("L", name: "Largeur", value: $box.width, range: 0.05...0.8)
                dimSlider("P", name: "Profondeur", value: $box.depth, range: 0.05...0.8)
                dimSlider("H", name: "Hauteur", value: $box.height, range: 0.01...0.4)
                HStack(spacing: 10) {
                    Image(systemName: "rotate.right").font(.footnote.weight(.bold)).frame(width: 16).accessibilityHidden(true)
                    Slider(value: Binding(get: { box.yawDegrees }, set: { box.yawDegrees = $0 }), in: -90...90).tint(Theme.accent)
                        .accessibilityLabel("Rotation de la boîte")
                        .accessibilityValue("\(Int(box.yawDegrees.rounded())) degrés")
                }
            }
        }
        .padding(.horizontal, 14).padding(.vertical, 12)
        .glass(RoundedRectangle(cornerRadius: 22))
    }

    private func dimTile(_ label: String, _ value: Float) -> some View {
        VStack(spacing: 2) {
            Text(String(format: "%.0f cm", value * 100)).font(.system(.headline, design: .rounded).monospacedDigit())
                .contentTransition(.numericText()).animation(.snappy, value: value)
            Text(label).font(.caption).foregroundStyle(.white.opacity(0.7))
        }
        .frame(maxWidth: .infinity)
    }

    private func dimSlider(_ label: String, name: String, value: Binding<Float>, range: ClosedRange<Float>) -> some View {
        HStack(spacing: 10) {
            Text(label).font(.footnote.weight(.bold)).frame(width: 16).accessibilityHidden(true)
            Slider(value: value, in: range).tint(Theme.accent)
                .accessibilityLabel(name)
                .accessibilityValue("\(Int((value.wrappedValue * 100).rounded())) centimètres")
        }
    }

    // MARK: actions

    @ViewBuilder private var actionBar: some View {
        HStack(spacing: 10) {
            switch controller.phase {
            case .placing:
                // Without the calculator the views would stay on the iPhone with no way to finish the dish.
                PrimaryButton(title: "Démarrer le scan", icon: "record.circle", enabled: box.placed && controller.calculatorOnline) {
                    showSliders = false
                    controller.start()
                }
            case .scanning:
                GlassIconButton(icon: "pause.fill", name: "Mettre en pause") { Haptics.tap(); controller.pause() }
                PrimaryButton(title: verdict.good ? "Terminer le scan" : "Terminer", icon: "checkmark",
                              tint: verdict.good ? Theme.good : Theme.accent, action: finishTapped)
            case .paused:
                if box.locked {
                    GlassIconButton(icon: "cube", label: "Boîte") { controller.reviseBox() }
                    GlassIconButton(icon: "play.fill", name: "Reprendre le scan") { controller.resume() }
                    PrimaryButton(title: "Terminer", icon: "checkmark",
                                  tint: verdict.good ? Theme.good : Theme.accent, action: finishTapped)
                } else {
                    GlassIconButton(icon: "xmark", label: "Annuler") { controller.cancelBoxRevision() }
                    PrimaryButton(title: "Recalculer", icon: "arrow.triangle.2.circlepath") { controller.applyBoxRevision() }
                }
            case .needsNewBox:
                PrimaryButton(title: "Valider la boîte", icon: "cube", enabled: box.placed) { controller.applyBoxRevision() }
            case .uploadingRest:
                GlassIconButton(icon: "xmark", name: "Annuler l'envoi") { controller.cancelFinish() }
                HStack(spacing: 10) { ProgressView().tint(.white); Text("Envoi des vues…").font(.subheadline.weight(.semibold)) }
                    .frame(maxWidth: .infinity).frame(height: 56).glass(Capsule())
            case .finishing:
                VStack(spacing: 8) {
                    HStack(spacing: 10) {
                        if controller.finishFraction == nil { ProgressView().tint(.white) }
                        Text(controller.finishText ?? "Calcul en cours…").font(.subheadline.weight(.semibold)).lineLimit(1).minimumScaleFactor(0.8)
                    }
                    if let f = controller.finishFraction {
                        ProgressView(value: f).tint(Theme.accent).padding(.horizontal, 24)
                    }
                }
                .frame(maxWidth: .infinity).frame(height: 56).glass(Capsule())
            case .done:
                GlassIconButton(icon: "square.and.arrow.up", name: "Exporter le dossier du scan") { shareURL = controller.exportZip() }
                PrimaryButton(title: "Voir dans Mes plats", icon: "square.grid.2x2.fill", tint: Theme.good) {
                    saveDishName()
                    model.nextTab = .library
                    model.screen = .connect
                }
            }
        }
    }

    // MARK: preview card

    private var previewCard: some View {
        Group {
            if placing { compactPreview } else { fullPreview }
        }
        .frame(maxWidth: .infinity)
        .background(Theme.canvas, in: UnevenRoundedRectangle(topLeadingRadius: Radius.stage, topTrailingRadius: Radius.stage))
        .overlay(alignment: .top) {
            UnevenRoundedRectangle(topLeadingRadius: Radius.stage, topTrailingRadius: Radius.stage).strokeBorder(Theme.hairline).allowsHitTesting(false)
        }
    }

    private var compactPreview: some View {
        HStack(spacing: 14) {
            Image(systemName: "circle.hexagongrid.fill").font(.title2).foregroundStyle(Theme.accent).accessibilityHidden(true)
                .frame(width: 44, height: 44).background(Theme.accent.opacity(0.14), in: Circle())
            VStack(alignment: .leading, spacing: 2) {
                Text("Aperçu 3D").font(.headline)
                Text("Le plat se construira ici pendant le scan.").font(.footnote).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 18).padding(.top, 18).frame(maxHeight: .infinity, alignment: .top)
    }

    private var fullPreview: some View {
        VStack(spacing: 10) {
            Capsule().fill(Color.white.opacity(0.25)).frame(width: 36, height: 4).padding(.top, 8)
            HStack(spacing: 10) {
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 8) {
                        Text(previewTitle).font(.headline)
                        if let level = controller.lastGeometry?.quality?.level, level != "too_early", controller.phase != .done {
                            Text(level == "good" ? "Bon" : level == "fair" ? "Correct" : "Insuffisant")
                                .font(.caption.weight(.semibold))
                                .padding(.horizontal, 8).padding(.vertical, 3)
                                .background(verdict.color.opacity(0.18), in: Capsule())
                                .foregroundStyle(verdict.color)
                                .accessibilityLabel("Qualité du scan : \(level == "good" ? "bonne" : level == "fair" ? "correcte" : "insuffisante")")
                        }
                    }
                    Text(previewSubtitle).font(.caption.monospacedDigit()).foregroundStyle(.secondary).lineLimit(1).minimumScaleFactor(0.7)
                }
                Spacer(minLength: 4)
                Button { expanded.toggle() } label: {
                    Image(systemName: expanded ? "chevron.down" : "chevron.up").font(.subheadline.weight(.bold))
                        .frame(width: 44, height: 44).background(Color.white.opacity(0.10), in: Circle()).foregroundStyle(.white)
                }
                .accessibilityLabel(expanded ? "Réduire l'aperçu 3D" : "Agrandir l'aperçu 3D")
            }
            .padding(.horizontal, 18)
            ZStack {
                PreviewView(renderer: controller.preview)
                    .accessibilityLabel("Aperçu 3D du plat")
                    .accessibilityIgnoresInvertColors()
                if controller.lastGeometry == nil {
                    VStack(spacing: 10) {
                        Image(systemName: "circle.hexagongrid.fill").font(.system(size: 30)).foregroundStyle(Theme.accent.opacity(0.8))
                        Text(emptyPreviewText).font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
                    }
                    .padding(.horizontal, 36).allowsHitTesting(false)
                }
            }
            .clipShape(.rect(cornerRadius: Radius.card))
            .padding(.horizontal, Spacing.s)
            if controller.lastGeometry != nil {
                Picker("", selection: $mode) { ForEach(PreviewMode.allCases) { Text($0.rawValue).tag($0) } }
                    .pickerStyle(.segmented).padding(.horizontal, 18)
                    .onChange(of: mode) { _, m in controller.preview.mode = m }
            }
            Spacer(minLength: 0).frame(height: 22)
        }
    }

    private var previewTitle: String {
        guard let g = controller.lastGeometry else { return "Aperçu 3D" }
        switch g.kind {
        case "points": return "Nuage de points"
        case "points+mesh": return "Nuage + surface"
        case "final": return "Modèle final"
        default: return g.kind
        }
    }

    private var previewSubtitle: String {
        guard let g = controller.lastGeometry, let t = controller.lastGeometryReceivedAt else { return "En direct pendant le scan" }
        if g.kind == "final" { return "\(g.triangle_count ?? 0) triangles · \(g.point_count ?? 0) points" }
        let age = max(0, Int(now.timeIntervalSince(t)))
        return "\(g.integrated_frames ?? 0) vues · \(g.point_count ?? 0) points · \(g.triangle_count ?? 0) triangles · il y a \(age) s"
    }

    private var emptyPreviewText: String {
        switch controller.phase {
        case .placing, .needsNewBox: return "Le nuage de points du plat apparaîtra ici, puis sa surface, pendant que vous tournez autour."
        default: return controller.calculatorOnline ? "Calcul des premières vues… continuez de tourner lentement."
            : "Calculateur injoignable : l’aperçu reprendra au retour du réseau."
        }
    }
}

extension URL: @retroactive Identifiable { public var id: String { absoluteString } }

struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController { UIActivityViewController(activityItems: items, applicationActivities: nil) }
    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}
