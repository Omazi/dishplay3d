import SwiftUI

/// Opening screen: the dish that builds itself, one clear action, and the latest dishes.
struct HomeView: View {
    @EnvironmentObject var model: AppModel
    let openSettings: () -> Void
    let openLibrary: () -> Void
    @State private var appeared = false
    @State private var dishes: [DishRecord] = []
    @Namespace private var zoom
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        NavigationStack {
            content
                .toolbar(.hidden, for: .navigationBar)
                .navigationDestination(for: DishRecord.self) { dish in
                    DishDetailView(dish: dish, changed: reload)
                        .modifier(ZoomDestination(id: dish.id, namespace: zoom))
                }
        }
        .task { await model.checkHealth() }
        .onAppear {
            reload()
            model.refreshPending()
            appeared = true
        }
    }

    private func reload() { dishes = Array(DishLibrary.all().prefix(8)) }

    private var content: some View {
        ZStack {
            ScreenBackground()
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    ViewThatFits(in: .horizontal) {
                        HStack {
                            Wordmark()
                            Spacer()
                            statusChip
                        }
                        VStack(alignment: .leading, spacing: Spacing.xs) {
                            Wordmark()
                            statusChip
                        }
                    }
                    .padding(.horizontal, Spacing.l).padding(.top, Spacing.xs)

                    VStack(alignment: .leading, spacing: 0) {
                        Text("Vos plats.").foregroundStyle(Theme.textPrimary)
                        Text("En trois dimensions.").foregroundStyle(Theme.textSecondary)
                    }
                    .appText(.display)
                    .accessibilityElement(children: .combine)
                    .padding(.horizontal, Spacing.l).padding(.top, Spacing.xl)
                    .staged(appeared, order: 0, reduceMotion: reduceMotion)

                    Stage {
                        HeroDishView().frame(height: 280)
                    }
                    .padding(.horizontal, Spacing.m).padding(.top, Spacing.l)
                    .staged(appeared, order: 1, reduceMotion: reduceMotion)

                    action
                        .padding(.horizontal, Spacing.l).padding(.top, Spacing.l)
                        .staged(appeared, order: 2, reduceMotion: reduceMotion)

                    if model.pendingScan != nil || model.pendingText != nil {
                        PendingScanCard()
                            .padding(.horizontal, Spacing.l).padding(.top, Spacing.l)
                            .staged(appeared, order: 3, reduceMotion: reduceMotion)
                    }
                    if !dishes.isEmpty {
                        recent
                            .padding(.top, Spacing.xl)
                            .staged(appeared, order: 3, reduceMotion: reduceMotion)
                    }
                }
                .padding(.bottom, Spacing.xl)
            }
            .scrollIndicators(.hidden)
        }
    }

    /// Where the calculator stands, one tap from its settings. Part of the page, so no glass.
    private var statusChip: some View {
        Button(action: openSettings) {
            HStack(spacing: Spacing.xs) {
                Circle().fill(model.paired ? Theme.good : Theme.warn).frame(width: 8, height: 8)
                Text(model.paired ? "Calculateur relié" : "Calculateur à relier")
                    .font(.footnote.weight(.semibold))
                Image(systemName: "chevron.right").font(.caption2.weight(.bold)).foregroundStyle(Theme.textSecondary)
                    .accessibilityHidden(true)
            }
            .padding(.horizontal, 14).frame(minHeight: 44)
            .foregroundStyle(Theme.textPrimary)
            .background { Capsule().fill(Theme.surface).strokeBorder(Theme.hairline) }
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
        VStack(alignment: .leading, spacing: Spacing.s) {
            HStack {
                Text("Derniers plats").appText(.section).foregroundStyle(Theme.textPrimary)
                Spacer()
                Button("Tout voir", action: openLibrary)
                    .font(.subheadline.weight(.semibold)).foregroundStyle(Theme.accent)
                    .frame(minHeight: 44)
            }
            .padding(.horizontal, Spacing.l)
            ScrollView(.horizontal) {
                LazyHStack(spacing: Spacing.s) {
                    ForEach(dishes) { dish in
                        NavigationLink(value: dish) {
                            DishCard(dish: dish, progress: model.dishProgress[dish.id])
                                .frame(width: 196)
                        }
                        .buttonStyle(PressableStyle())
                        .modifier(ZoomSource(id: dish.id, namespace: zoom))
                        .scrollTransition { content, phase in
                            content
                                .scaleEffect(phase.isIdentity ? 1 : 0.94)
                                .opacity(phase.isIdentity ? 1 : 0.7)
                        }
                    }
                }
                .scrollTargetLayout()
                .padding(.horizontal, Spacing.l)
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
            .offset(y: shown || reduceMotion ? 0 : 18)
            .animation(reduceMotion ? .easeOut(duration: 0.2) : .spring(duration: 0.6, bounce: 0.18).delay(0.12 + 0.09 * Double(order)),
                       value: shown)
    }
}
