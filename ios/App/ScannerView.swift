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
                ZStack {
                    ARViewContainer(arView: controller.ar.arView).ignoresSafeArea(edges: .top)
                    VStack(spacing: 8) {
                        statusBar
                        if let g = guidanceText { banner(g) }
                        if let e = controller.errorText { banner(e, color: .red.opacity(0.85)) }
                        Spacer(minLength: 0)
                        controls
                    }
                    .padding(.horizontal, 12).padding(.vertical, 10)
                }
                .frame(height: expanded ? geo.size.height * 0.28 : geo.size.height * 0.62)
                .clipped()
                previewPanel.frame(maxHeight: .infinity)
            }
            .background(Color.black)
        }
        .preferredColorScheme(.dark)
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

    private var calculatorLabel: (String, Color) {
        if !controller.calculatorOnline { return ("PC injoignable", .red) }
        return (controller.serverSessionID == nil ? "PC prêt" : "PC connecté", .green)
    }

    private var statusBar: some View {
        let s = controller.status
        let t = trackingLabel
        let c = calculatorLabel
        return HStack(spacing: 10) {
            dot(t.0, t.1)
            dot(c.0, c.1)
            Spacer(minLength: 4)
            Text(ar.lidarActive ? "LiDAR" : "Stéréo").font(.caption2.weight(.semibold)).foregroundStyle(.secondary)
            if controller.phase != .placing {
                Label("\(controller.savedFrames)", systemImage: "camera.fill").font(.caption.monospacedDigit())
                Label("\(controller.scheduler.ring.visitedBins)/36", systemImage: "circle.dashed").font(.caption.monospacedDigit())
                if s.dropped > 0 { Label("\(s.dropped)", systemImage: "forward.fill").font(.caption.monospacedDigit()) }
            }
        }
        .padding(.horizontal, 12).padding(.vertical, 8)
        .background(.ultraThinMaterial, in: Capsule())
    }

    private func dot(_ text: String, _ color: Color) -> some View {
        HStack(spacing: 5) {
            Circle().fill(color).frame(width: 8, height: 8)
            Text(text).font(.caption.weight(.semibold)).lineLimit(1)
        }
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
            if !controller.calculatorOnline { return "PC injoignable : les vues restent sur l’iPhone et seront envoyées au retour du réseau. L’aperçu est figé." }
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
        VStack(spacing: 8) {
            if box.placed && !box.locked {
                VStack(spacing: 4) {
                    dimSlider("Largeur", value: $box.width, range: 0.05...0.8)
                    dimSlider("Profondeur", value: $box.depth, range: 0.05...0.8)
                    dimSlider("Hauteur", value: $box.height, range: 0.01...0.4)
                }
                .padding(10).background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 14))
            }
            HStack(spacing: 10) {
                Button { model.screen = .connect } label: {
                    Image(systemName: "chevron.left").font(.headline).frame(width: 44, height: 44)
                        .background(.ultraThinMaterial, in: Circle())
                }
                .disabled(controller.phase == .scanning || controller.phase == .finishing)
                Spacer()
                switch controller.phase {
                case .placing:
                    primary("Démarrer", "record.circle") { controller.start() }.disabled(!box.placed).opacity(box.placed ? 1 : 0.45)
                case .scanning:
                    secondary("Pause", "pause.fill") { controller.pause() }
                    primary("Terminer", "checkmark") { controller.finish() }
                case .paused:
                    if box.locked {
                        secondary("Boîte", "cube") { controller.reviseBox() }
                        secondary("Reprendre", "play.fill") { controller.resume() }
                        primary("Terminer", "checkmark") { controller.finish() }
                    } else {
                        primary("Appliquer (recalcul)", "arrow.triangle.2.circlepath") { controller.applyBoxRevision() }
                    }
                case .needsNewBox:
                    primary("Appliquer la nouvelle boîte", "cube") { controller.applyBoxRevision() }.disabled(!box.placed)
                case .uploadingRest, .finishing:
                    ProgressView().tint(.white).frame(width: 44, height: 44).background(.ultraThinMaterial, in: Circle())
                case .done:
                    primary("Exporter", "square.and.arrow.up") { shareURL = controller.exportZip() }
                }
            }
        }
    }

    private func primary(_ title: String, _ icon: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: icon).font(.headline).padding(.horizontal, 18).frame(height: 44)
                .background(Color.accentColor, in: Capsule()).foregroundStyle(.white)
        }
    }

    private func secondary(_ title: String, _ icon: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: icon).font(.subheadline.weight(.semibold)).padding(.horizontal, 14).frame(height: 44)
                .background(.ultraThinMaterial, in: Capsule()).foregroundStyle(.white)
        }
    }

    private func dimSlider(_ label: String, value: Binding<Float>, range: ClosedRange<Float>) -> some View {
        HStack {
            Text(label).font(.caption.weight(.medium)).frame(width: 78, alignment: .leading)
            Slider(value: value, in: range)
            Text(String(format: "%.1f cm", value.wrappedValue * 100)).font(.caption.monospacedDigit()).frame(width: 60)
        }
    }

    // MARK: preview

    private var previewPanel: some View {
        VStack(spacing: 0) {
            HStack(alignment: .center, spacing: 10) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(reconstructionLabel).font(.subheadline.weight(.semibold)).lineLimit(1).minimumScaleFactor(0.8)
                    if controller.lastGeometry != nil {
                        Text(geometryLine).font(.caption2.monospacedDigit()).foregroundStyle(.secondary).lineLimit(2)
                    }
                }
                Spacer(minLength: 4)
                Button { withAnimation { expanded.toggle() } } label: {
                    Image(systemName: expanded ? "arrow.down.right.and.arrow.up.left" : "arrow.up.left.and.arrow.down.right")
                        .font(.subheadline.weight(.semibold)).frame(width: 36, height: 36).background(Color.white.opacity(0.1), in: Circle())
                }
            }
            .padding(.horizontal, 14).padding(.top, 10).padding(.bottom, 8)
            ZStack {
                PreviewView(renderer: controller.preview)
                if controller.lastGeometry == nil {
                    VStack(spacing: 8) {
                        Image(systemName: "circle.hexagongrid").font(.system(size: 34)).foregroundStyle(.secondary)
                        Text(emptyPreviewText).font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
                    }
                    .padding(.horizontal, 30).allowsHitTesting(false)
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 16))
            .padding(.horizontal, 10)
            VStack(spacing: 6) {
                Picker("", selection: $mode) { ForEach(PreviewMode.allCases) { Text($0.rawValue).tag($0) } }
                    .pickerStyle(.segmented)
                    .onChange(of: mode) { _, m in controller.preview.mode = m }
                Text("Gris : repères de suivi (non reconstruits) · terne : vu une seule fois · bleuté : interpolé")
                    .font(.caption2).foregroundStyle(.secondary).lineLimit(1).minimumScaleFactor(0.6)
            }
            .padding(.horizontal, 14).padding(.vertical, 8)
        }
        .background(Color(white: 0.09))
    }

    private var emptyPreviewText: String {
        switch controller.phase {
        case .placing: return "Le nuage de points du plat apparaîtra ici, puis sa surface, pendant que tu tournes autour."
        default: return controller.calculatorOnline ? "Calcul des premières vues… continue de tourner lentement."
            : "PC injoignable : les vues sont gardées sur l’iPhone et l’aperçu reprendra au retour du réseau."
        }
    }

    private var reconstructionLabel: String {
        guard let g = controller.lastGeometry else {
            return controller.phase == .placing ? "Aperçu 3D" : "En attente du premier nuage…"
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
        Text(text).font(.subheadline.weight(.medium)).multilineTextAlignment(.center)
            .padding(.horizontal, 14).padding(.vertical, 10).frame(maxWidth: .infinity)
            .background(color, in: RoundedRectangle(cornerRadius: 14)).foregroundStyle(.white)
    }
}

extension URL: @retroactive Identifiable { public var id: String { absoluteString } }

struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController { UIActivityViewController(activityItems: items, applicationActivities: nil) }
    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}
