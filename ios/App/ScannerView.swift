import RealityKit
import ScanCore
import SwiftUI

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
    private let ticker = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    init(controller: ScanController) {
        _controller = ObservedObject(wrappedValue: controller)
        _box = ObservedObject(wrappedValue: controller.box)
        _ar = ObservedObject(wrappedValue: controller.ar)
    }

    var body: some View {
        GeometryReader { geo in
            let previewHeight = geo.size.height * (expanded ? 0.66 : 0.36)
            ZStack(alignment: .bottom) {
                VStack(spacing: 0) {
                    ZStack {
                        ARViewContainer(arView: controller.ar.arView).ignoresSafeArea(edges: .top)
                        VStack(spacing: 12) {
                            topBar
                            instructionCard
                            Spacer(minLength: 0)
                            if box.placed && !box.locked && !expanded { dimensions }
                            actionBar
                        }
                        .padding(.horizontal, 16).padding(.top, 6).padding(.bottom, 40)
                    }
                    Color.clear.frame(height: previewHeight - 28)
                }
                previewCard.frame(height: previewHeight)
            }
            .background(Color.black)
            .ignoresSafeArea(edges: .bottom)
            .animation(.spring(duration: 0.35), value: expanded)
            .animation(.spring(duration: 0.3), value: showSliders)
        }
        .preferredColorScheme(.dark)
        .onReceive(ticker) { now = $0 }
        .sheet(item: $shareURL) { url in ShareSheet(items: [url]) }
    }

    // MARK: top bar

    private var topBar: some View {
        HStack(spacing: 10) {
            Button { controller.abandonIfUnfinished(); model.refreshPending(); model.screen = .connect } label: {
                Image(systemName: "xmark").font(.subheadline.weight(.bold)).foregroundStyle(.white)
                    .frame(width: 40, height: 40).glass(Circle())
            }
            .disabled(controller.phase == .scanning || controller.phase == .finishing || controller.phase == .uploadingRest)
            HStack(spacing: 14) {
                StatusDot(text: trackingText.0, color: trackingText.1)
                StatusDot(text: computerText.0, color: computerText.1)
                if controller.phase != .placing {
                    Spacer(minLength: 0)
                    Label("\(controller.savedFrames)", systemImage: "photo.stack").font(.footnote.weight(.semibold).monospacedDigit())
                }
            }
            .padding(.horizontal, 14).frame(height: 40).frame(maxWidth: .infinity, alignment: .leading)
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
            return box.placed
                ? ("Centre la boîte sur le plat", "Glisse pour déplacer · pince pour réduire ou agrandir · boules : chaque côté.", .white)
                : ("Place la boîte", "Touche la table au pied du plat.", .white)
        case .needsNewBox:
            return ("Replace la boîte", "Le suivi a redémarré : touche la table au pied du plat.", Theme.warn)
        case .paused:
            return ("En pause", box.locked ? "Ta session est conservée." : "Modifie la boîte puis applique : le modèle sera recalculé.", .white)
        case .uploadingRest:
            return ("Envoi des dernières vues", "\(controller.store?.pendingCount ?? 0) restantes…", .white)
        case .finishing:
            return ("Finition du modèle", controller.finishText, .white)
        case .done:
            return ("Modèle prêt", "Fais-le tourner du doigt dans l’aperçu.", Theme.good)
        case .scanning:
            if !controller.calculatorOnline {
                return ("PC injoignable", "Les vues restent sur l’iPhone ; l’aperçu est figé.", Theme.bad)
            }
            switch controller.status.guidance {
            case .trackingLost?: return ("Suivi perdu", "Reviens lentement vers le plat.", Theme.bad)
            case .trackingLimited?: return ("Ralentis", "Garde la table dans l’image.", Theme.warn)
            case .frameTheDish?: return ("Recadre", "Garde toute la boîte dans l’image.", Theme.warn)
            case .slowDown?: return ("Ralentis", "Un mouvement lent donne des vues nettes.", Theme.warn)
            case .tooDark?: return ("Trop sombre", "Ajoute de la lumière douce.", Theme.warn)
            case .dontRotateInPlace?: return ("Déplace-toi", "Ne pivote pas sur place : marche autour du plat.", Theme.warn)
            case .goHigher?: return ("Monte un peu", "Passe plus haut pour voir l’intérieur du plat.", .white)
            case .completeSide?: return ("Continue le tour", "Remplis les secteurs vides de l’anneau.", .white)
            default: return ("Tourne autour du plat", "Lentement, en gardant le plat dans l’image.", .white)
            }
        }
    }

    /// Compact on purpose: it sits on top of the camera image and must not hide the dish.
    private var instructionCard: some View {
        let i = instruction
        let scanning = controller.phase == .scanning || controller.phase == .paused
        return VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 5) {
                ForEach(0..<4, id: \.self) { k in
                    Capsule().fill(k <= stepIndex ? Theme.accent : Color.white.opacity(0.22)).frame(height: 4)
                }
            }
            HStack(alignment: .center, spacing: 12) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(i.title).font(.headline).foregroundStyle(i.color).lineLimit(1).minimumScaleFactor(0.8)
                    if scanning, i.color == .white, let hint = sideHint {
                        Text(hint).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.accent).lineLimit(1).minimumScaleFactor(0.8)
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
    }

    /// Which way to walk: the ring keeps the phone at the bottom, so "right" on the ring is the user's right.
    private var sideHint: String? {
        let az = controller.cameraAzimuthDeg * .pi / 180
        let h = Double(box.height)
        guard let s = controller.scheduler.ring.suggestion(currentCameraInObject: [cos(az), h / 2, sin(az)], boxHeight: h) else {
            return "Tour complet : tu peux terminer"
        }
        if s.0 == .goHigher { return "↑ Passe au-dessus du plat" }
        return s.direction >= 0 ? "← Va vers ta gauche" : "Va vers ta droite →"
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
            if showSliders {
                Button { box.replace() } label: {
                    Label("Replacer la boîte ailleurs", systemImage: "arrow.uturn.backward").font(.footnote.weight(.semibold))
                        .frame(maxWidth: .infinity).frame(height: 34).background(Color.white.opacity(0.12), in: Capsule()).foregroundStyle(.white)
                }
            }
            if showSliders {
                dimSlider("L", value: $box.width, range: 0.05...0.8)
                dimSlider("P", value: $box.depth, range: 0.05...0.8)
                dimSlider("H", value: $box.height, range: 0.01...0.4)
                HStack(spacing: 10) {
                    Image(systemName: "rotate.right").font(.footnote.weight(.bold)).frame(width: 16)
                    Slider(value: Binding(get: { box.yawDegrees }, set: { box.yawDegrees = $0 }), in: -90...90).tint(Theme.accent)
                }
            }
        }
        .padding(.horizontal, 14).padding(.vertical, 12)
        .glass(RoundedRectangle(cornerRadius: 22))
    }

    private func dimTile(_ label: String, _ value: Float) -> some View {
        VStack(spacing: 2) {
            Text(String(format: "%.0f cm", value * 100)).font(.headline.monospacedDigit())
            Text(label).font(.caption2).foregroundStyle(.white.opacity(0.7))
        }
        .frame(maxWidth: .infinity)
    }

    private func dimSlider(_ label: String, value: Binding<Float>, range: ClosedRange<Float>) -> some View {
        HStack(spacing: 10) {
            Text(label).font(.footnote.weight(.bold)).frame(width: 16)
            Slider(value: value, in: range).tint(Theme.accent)
        }
    }

    // MARK: actions

    @ViewBuilder private var actionBar: some View {
        HStack(spacing: 10) {
            switch controller.phase {
            case .placing:
                PrimaryButton(title: "Démarrer le scan", icon: "record.circle", enabled: box.placed) { showSliders = false; controller.start() }
            case .scanning:
                GlassIconButton(icon: "pause.fill") { controller.pause() }
                PrimaryButton(title: "Terminer", icon: "checkmark") { controller.finish() }
            case .paused:
                if box.locked {
                    GlassIconButton(icon: "cube") { controller.reviseBox() }
                    GlassIconButton(icon: "play.fill", label: "Reprendre") { controller.resume() }
                    PrimaryButton(title: "Terminer", icon: "checkmark") { controller.finish() }
                } else {
                    PrimaryButton(title: "Appliquer et recalculer", icon: "arrow.triangle.2.circlepath") { controller.applyBoxRevision() }
                }
            case .needsNewBox:
                PrimaryButton(title: "Valider la boîte", icon: "cube", enabled: box.placed) { controller.applyBoxRevision() }
            case .uploadingRest:
                GlassIconButton(icon: "xmark") { controller.cancelFinish() }
                HStack(spacing: 10) { ProgressView().tint(.white); Text("Envoi des vues…").font(.subheadline.weight(.semibold)) }
                    .frame(maxWidth: .infinity).frame(height: 56).glass(Capsule())
            case .finishing:
                HStack(spacing: 10) { ProgressView().tint(.white); Text("Calcul en cours…").font(.subheadline.weight(.semibold)) }
                    .frame(maxWidth: .infinity).frame(height: 56).glass(Capsule())
            case .done:
                PrimaryButton(title: "Exporter le modèle", icon: "square.and.arrow.up") { shareURL = controller.exportZip() }
            }
        }
    }

    // MARK: preview card

    private var previewCard: some View {
        VStack(spacing: 10) {
            Capsule().fill(Color.white.opacity(0.25)).frame(width: 36, height: 4).padding(.top, 8)
            HStack(spacing: 10) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(previewTitle).font(.headline)
                    Text(previewSubtitle).font(.caption.monospacedDigit()).foregroundStyle(.secondary).lineLimit(1).minimumScaleFactor(0.7)
                }
                Spacer(minLength: 4)
                Button { expanded.toggle() } label: {
                    Image(systemName: expanded ? "chevron.down" : "chevron.up").font(.subheadline.weight(.bold))
                        .frame(width: 36, height: 36).background(Color.white.opacity(0.10), in: Circle()).foregroundStyle(.white)
                }
            }
            .padding(.horizontal, 18)
            ZStack {
                PreviewView(renderer: controller.preview)
                if controller.lastGeometry == nil {
                    VStack(spacing: 10) {
                        Image(systemName: "circle.hexagongrid.fill").font(.system(size: 30)).foregroundStyle(Theme.accent.opacity(0.8))
                        Text(emptyPreviewText).font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
                    }
                    .padding(.horizontal, 36).allowsHitTesting(false)
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 20))
            .padding(.horizontal, 12)
            if controller.lastGeometry != nil {
                Picker("", selection: $mode) { ForEach(PreviewMode.allCases) { Text($0.rawValue).tag($0) } }
                    .pickerStyle(.segmented).padding(.horizontal, 18)
                    .onChange(of: mode) { _, m in controller.preview.mode = m }
            }
            Spacer(minLength: 0).frame(height: 22)
        }
        .frame(maxWidth: .infinity)
        .background(Theme.panel, in: UnevenRoundedRectangle(topLeadingRadius: 28, topTrailingRadius: 28))
        .overlay(alignment: .top) {
            UnevenRoundedRectangle(topLeadingRadius: 28, topTrailingRadius: 28).strokeBorder(Color.white.opacity(0.08)).allowsHitTesting(false)
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
        case .placing, .needsNewBox: return "Le nuage de points du plat apparaîtra ici, puis sa surface, pendant que tu tournes autour."
        default: return controller.calculatorOnline ? "Calcul des premières vues… continue de tourner lentement."
            : "PC injoignable : l’aperçu reprendra au retour du réseau."
        }
    }
}

extension URL: @retroactive Identifiable { public var id: String { absoluteString } }

struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController { UIActivityViewController(activityItems: items, applicationActivities: nil) }
    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}
