import SwiftUI

/// Opening screen: the dish that builds itself, one clear action, and the latest dishes.
struct HomeView: View {
    @EnvironmentObject var model: AppModel
    let openSettings: () -> Void
    let openLibrary: () -> Void
    @State private var appeared = false
    @State private var dishes: [DishRecord] = []
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack {
            AmbientBackground()
            ScrollView {
                VStack(spacing: 0) {
                    HeroDishView()
                        .frame(height: 300)
                        .padding(.top, 8)
                    VStack(spacing: 10) {
                        Text("DishPlay")
                            .font(.system(size: 44, weight: .bold, design: .rounded))
                        Text("Vos plats en 3D, en un tour d’assiette.")
                            .font(.title3).foregroundStyle(.white.opacity(0.75))
                            .multilineTextAlignment(.center)
                    }
                    .staged(appeared, order: 0, reduceMotion: reduceMotion)

                    statusChip
                        .padding(.top, 18)
                        .staged(appeared, order: 1, reduceMotion: reduceMotion)

                    action
                        .padding(.horizontal, 24).padding(.top, 22)
                        .staged(appeared, order: 2, reduceMotion: reduceMotion)

                    if model.pendingScan != nil || model.pendingText != nil {
                        PendingScanCard()
                            .padding(.horizontal, 20).padding(.top, 22)
                            .staged(appeared, order: 3, reduceMotion: reduceMotion)
                    }
                    if !dishes.isEmpty {
                        recent
                            .padding(.top, 30)
                            .staged(appeared, order: 3, reduceMotion: reduceMotion)
                    }
                }
                .padding(.bottom, 32)
            }
            .scrollIndicators(.hidden)
        }
        .task { await model.checkHealth() }
        .onAppear {
            dishes = Array(DishLibrary.all().prefix(8))
            model.refreshPending()
            appeared = true
        }
    }

    private var statusChip: some View {
        Button(action: openSettings) {
            HStack(spacing: 8) {
                Circle().fill(model.paired ? Theme.good : Theme.warn).frame(width: 8, height: 8)
                Text(model.paired ? "Calculateur relié" : "Calculateur à relier")
                    .font(.footnote.weight(.semibold))
                Image(systemName: "chevron.right").font(.caption2.weight(.bold)).foregroundStyle(.white.opacity(0.5))
            }
            .padding(.horizontal, 14).frame(height: 44)
            .foregroundStyle(.white)
            .glass(Capsule())
        }
        .buttonStyle(PressableStyle())
        .accessibilityHint("Ouvre les réglages du calculateur")
    }

    @ViewBuilder private var action: some View {
        if !model.trackingSupported {
            Label("Cet iPhone ne prend pas en charge le suivi AR.", systemImage: "xmark.octagon")
                .font(.subheadline).foregroundStyle(Theme.bad)
        } else if model.paired {
            PrimaryButton(title: "Scanner un plat", icon: "viewfinder") {
                Haptics.tap(.medium)
                model.screen = .scan
            }
        } else {
            PrimaryButton(title: "Relier le calculateur", icon: "link", action: openSettings)
        }
    }

    private var recent: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Derniers plats").font(.title3.bold())
                Spacer()
                Button("Tout voir", action: openLibrary)
                    .font(.subheadline.weight(.semibold)).foregroundStyle(Theme.accent)
                    .frame(minHeight: 44)
            }
            .padding(.horizontal, 20)
            ScrollView(.horizontal) {
                LazyHStack(spacing: 14) {
                    ForEach(dishes) { dish in
                        Button(action: openLibrary) {
                            DishCard(dish: dish)
                                .frame(width: 168)
                        }
                        .buttonStyle(PressableStyle())
                        .scrollTransition { content, phase in
                            content
                                .scaleEffect(phase.isIdentity ? 1 : 0.92)
                                .opacity(phase.isIdentity ? 1 : 0.6)
                        }
                    }
                }
                .scrollTargetLayout()
                .padding(.horizontal, 20)
            }
            .scrollTargetBehavior(.viewAligned)
            .scrollIndicators(.hidden)
        }
    }
}

private extension View {
    /// Blocks arrive one after another when the screen opens.
    func staged(_ shown: Bool, order: Int, reduceMotion: Bool) -> some View {
        self
            .opacity(shown ? 1 : 0)
            .offset(y: shown || reduceMotion ? 0 : 22)
            .animation(reduceMotion ? .easeOut(duration: 0.2) : .spring(duration: 0.7, bounce: 0.22).delay(0.9 + 0.12 * Double(order)),
                       value: shown)
    }
}

/// A scan that was interrupted (app closed, Wi-Fi lost): send the rest or drop it.
struct PendingScanCard: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let p = model.pendingScan {
                Label("Scan interrompu", systemImage: "exclamationmark.arrow.triangle.2.circlepath")
                    .font(.headline).foregroundStyle(Theme.warn)
                Text(p.pending > 0 ? "\(p.pending) vues sur \(p.total) n’ont pas été envoyées au calculateur."
                                   : "Les \(p.total) vues sont sur le calculateur, mais la finition n’a pas été lancée.")
                    .font(.subheadline).fixedSize(horizontal: false, vertical: true)
            }
            if let t = model.pendingText {
                HStack(spacing: 10) {
                    if model.pendingBusy { ProgressView() }
                    Text(t).font(.footnote).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
            }
            if model.pendingScan != nil {
                HStack(spacing: 10) {
                    SmallButton(title: "Envoyer et terminer", icon: "arrow.up.circle") { Task { await model.resumePending() } }
                        .disabled(model.pendingBusy || !model.paired)
                    SmallButton(title: "Ignorer", icon: "trash") { model.discardPending() }
                        .disabled(model.pendingBusy)
                }
            }
        }
        .padding(18).frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.white.opacity(0.07), in: RoundedRectangle(cornerRadius: Theme.corner))
        .overlay(RoundedRectangle(cornerRadius: Theme.corner).strokeBorder(Color.white.opacity(0.09)))
    }
}

struct SmallButton: View {
    let title: String
    let icon: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label(title, systemImage: icon).font(.footnote.weight(.semibold))
                .padding(.horizontal, 14).frame(minHeight: 44)
                .background(Color.white.opacity(0.10), in: Capsule()).foregroundStyle(.white)
        }
        .buttonStyle(PressableStyle())
    }
}
