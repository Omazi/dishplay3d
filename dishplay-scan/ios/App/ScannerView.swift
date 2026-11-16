import RealityKit
import ScanCore
import SwiftUI

struct ARViewContainer: UIViewRepresentable {
    let arView: ARView
    func makeUIView(context: Context) -> ARView { arView }
    func updateUIView(_ uiView: ARView, context: Context) {}
}

/// Top: camera + AR box. Bottom third: live reconstruction (own virtual camera, neutral background).
struct ScannerView: View {
    @ObservedObject var controller: ScanController
    @ObservedObject private var box: BoundingBoxController
    @ObservedObject private var ar: ARSessionController
    @EnvironmentObject var model: AppModel
    @State private var expanded = false
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
            VStack(spacing: 0) {
                ZStack(alignment: .top) {
                    ARViewContainer(arView: controller.ar.arView).ignoresSafeArea(edges: .top)
                    VStack(spacing: 6) {
                        statusBar
                        if let g = guidanceText { banner(g) }
                        if let e = controller.errorText { banner(e, color: .red.opacity(0.85)) }
                        Spacer()
                        controls
                    }
                    .padding(8)
                }
                .frame(height: expanded ? geo.size.height * 0.25 : geo.size.height * 0.64)
                previewPanel.frame(maxHeight: .infinity)
            }
        }
        .onReceive(ticker) { now = $0 }
        .sheet(item: $shareURL) { url in ShareSheet(items: [url]) }
    }

    // MARK: status

    private var trackingLabel: (String, Color) {
        switch ar.tracking {
        case .normal: return ("Suivi OK", .green)
        case .limited(let r): return ("Suivi limité : \(r)", .orange)
        case .notAvailable: return ("Suivi perdu", .red)
        }
    }

    private var statusBar: some View {
        let s = controller.status
        let t = trackingLabel
        return VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                chip(t.0, t.1)
                chip(controller.calculatorOnline ? "Calculateur connecté" : "Calculateur déconnecté",
                     controller.calculatorOnline ? .green : .red)
                if ar.lidarActive { chip("LiDAR", .blue) } else { chip("Stéréo", .purple) }
            }
            HStack(spacing: 6) {
                chip("Vues : \(controller.savedFrames) (envoyées \(controller.sentFrames))", .gray)
                chip("Angles : \(controller.scheduler.ring.visitedBins)/36", .gray)
                if s.dropped > 0 { chip("Ignorées : \(s.dropped)", .gray) }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var guidanceText: String? {
        switch controller.phase {
        case .placing:
            return box.placed ? "Ajuste la boîte : poignées orange (largeur), bleues (profondeur), jaune (hauteur), disque (déplacer), deux doigts (tourner)."
                : "Touche la table à côté du plat pour placer la boîte."
        case .needsNewBox: return "Suivi réinitialisé : nouveau repère. Replace la boîte puis applique la révision (les vues déjà envoyées sont conservées)."
        case .paused: return "Pause : la session est conservée."
        case .uploadingRest: return "Envoi des dernières vues (\(controller.store?.pendingCount ?? 0))…"
        case .finishing: return controller.finishText
        case .done: return controller.finishText
        case .scanning:
            if !controller.calculatorOnline { return "Calculateur déconnecté : les vues restent sur l’iPhone et seront envoyées au retour du réseau. L’aperçu est figé." }
            switch controller.status.guidance {
            case .trackingLost?: return "Suivi perdu : reviens vers le plat lentement."
            case .trackingLimited?: return "Suivi limité : ralentis, garde la table dans l’image."
            case .frameTheDish?: return "Garde toute la boîte dans l’image."
            case .slowDown?: return "Ralentis."
            case .tooDark?: return "Trop sombre : ajoute de la lumière diffuse."
            case .moveAround?: return "Avance autour du plat."
            case .dontRotateInPlace?: return "Ne tourne pas sur place : déplace-toi autour du plat."
            case .goHigher?: return "Monte légèrement pour voir l’intérieur du plat."
            case .completeSide?: return "Complète ce côté du plat."
            default: return nil
            }
        }
    }

    // MARK: controls

    @ViewBuilder private var controls: some View {
        VStack(spacing: 6) {
            if box.placed && !box.locked {
                VStack(spacing: 2) {
                    dimSlider("Largeur", value: $box.width, range: 0.05...0.8)
                    dimSlider("Profondeur", value: $box.depth, range: 0.05...0.8)
                    dimSlider("Hauteur", value: $box.height, range: 0.01...0.4)
                }
                .padding(6).background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 10))
            }
            HStack {
                Button { model.screen = .connect } label: { Image(systemName: "chevron.left") }
                    .buttonStyle(.bordered)
                    .disabled(controller.phase == .scanning || controller.phase == .finishing)
                Spacer()
                switch controller.phase {
                case .placing:
                    Button("Démarrer") { controller.start() }.buttonStyle(.borderedProminent).disabled(!box.placed)
                case .scanning:
                    Button("Pause") { controller.pause() }.buttonStyle(.bordered)
                    Button("Terminer") { controller.finish() }.buttonStyle(.borderedProminent)
                case .paused:
                    if box.locked {
                        Button("Réviser la boîte") { controller.reviseBox() }.buttonStyle(.bordered)
                        Button("Reprendre") { controller.resume() }.buttonStyle(.bordered)
                        Button("Terminer") { controller.finish() }.buttonStyle(.borderedProminent)
                    } else {
                        Button("Appliquer (recalcul)") { controller.applyBoxRevision() }.buttonStyle(.borderedProminent)
                    }
                case .needsNewBox:
                    Button("Appliquer la nouvelle boîte") { controller.applyBoxRevision() }.buttonStyle(.borderedProminent).disabled(!box.placed)
                case .uploadingRest, .finishing:
                    ProgressView()
                case .done:
                    Button("Exporter") { shareURL = controller.exportZip() }.buttonStyle(.borderedProminent)
                }
            }
        }
    }

    private func dimSlider(_ label: String, value: Binding<Float>, range: ClosedRange<Float>) -> some View {
        HStack {
            Text(label).font(.caption).frame(width: 78, alignment: .leading)
            Slider(value: value, in: range)
            Text(String(format: "%.1f cm", value.wrappedValue * 100)).font(.caption.monospacedDigit()).frame(width: 60)
        }
    }

    // MARK: preview

    private var previewPanel: some View {
        ZStack(alignment: .topLeading) {
            PreviewView(renderer: controller.preview)
            VStack(alignment: .leading, spacing: 2) {
                Text(reconstructionLabel).font(.caption.bold())
                Text(geometryLine).font(.caption2.monospacedDigit())
                Text("Gris = suivi ARKit (non reconstruit) · terne = vue unique · bleuté = interpolé").font(.caption2).foregroundStyle(.secondary)
            }
            .padding(6).background(.black.opacity(0.45), in: RoundedRectangle(cornerRadius: 8)).foregroundStyle(.white).padding(6)
            VStack {
                HStack {
                    Spacer()
                    Picker("", selection: $mode) { ForEach(PreviewMode.allCases) { Text($0.rawValue).tag($0) } }
                        .pickerStyle(.segmented).frame(width: 210)
                        .onChange(of: mode) { _, m in controller.preview.mode = m }
                    Button { expanded.toggle() } label: { Image(systemName: expanded ? "arrow.down.right.and.arrow.up.left" : "arrow.up.left.and.arrow.down.right") }
                        .buttonStyle(.bordered)
                }
                Spacer()
            }
            .padding(6)
        }
        .background(Color(white: 0.13))
    }

    private var reconstructionLabel: String {
        guard let g = controller.lastGeometry else {
            return controller.phase == .placing ? "Aperçu : points de suivi seulement" : "En attente du premier nuage reconstruit…"
        }
        switch g.kind {
        case "points": return "Nuage reconstruit (provisoire) v\(g.version)"
        case "points+mesh": return "Nuage + surface partielle v\(g.version)"
        case "final": return "Modèle final (inspectable)"
        default: return g.kind
        }
    }

    private var geometryLine: String {
        guard let g = controller.lastGeometry, let t = controller.lastGeometryReceivedAt else { return "—" }
        let age = Int(now.timeIntervalSince(t))
        let last = g.last_frame_ids?.last.map { "#\($0)" } ?? "—"
        let area = (g.surface?.measured_m2 ?? 0) * 10000
        return "vues intégrées \(g.integrated_frames ?? 0) · dernière \(last) · il y a \(age) s · \(g.point_count ?? 0) pts · \(g.triangle_count ?? 0) tri · surface mesurée \(Int(area)) cm²"
    }

    // MARK: helpers

    private func chip(_ text: String, _ color: Color) -> some View {
        Text(text).font(.caption2.bold()).padding(.horizontal, 6).padding(.vertical, 3)
            .background(color.opacity(0.75), in: Capsule()).foregroundStyle(.white)
    }

    private func banner(_ text: String, color: Color = .black.opacity(0.6)) -> some View {
        Text(text).font(.callout).multilineTextAlignment(.center).padding(8).frame(maxWidth: .infinity)
            .background(color, in: RoundedRectangle(cornerRadius: 10)).foregroundStyle(.white)
    }
}

extension URL: @retroactive Identifiable { public var id: String { absoluteString } }

struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController { UIActivityViewController(activityItems: items, applicationActivities: nil) }
    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}
