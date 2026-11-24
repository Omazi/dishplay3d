import SwiftUI

/// First launch: three sliding pages that explain the whole app, then straight to the home screen.
struct OnboardingView: View {
    let done: () -> Void
    @State private var page: Int? = 0
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private struct Page: Identifiable {
        let id: Int
        let symbol: String
        let kicker: String
        let title: String
        let text: String
    }

    private let pages: [Page] = [
        Page(id: 0, symbol: "", kicker: "Bienvenue", title: "Vos plats en 3D",
             text: "Tournez autour d’une assiette avec l’iPhone : sa forme se construit sous vos yeux."),
        Page(id: 1, symbol: "cube.transparent", kicker: "Étape 1", title: "Posez la boîte",
             text: "Touchez la table au pied du plat, puis ajustez la boîte à sa taille."),
        Page(id: 2, symbol: "arrow.triangle.2.circlepath", kicker: "Étape 2", title: "Faites le tour",
             text: "L’anneau se remplit à mesure que chaque côté est vu. Quand il est complet, terminez."),
    ]

    var body: some View {
        ZStack {
            ScreenBackground()
            VStack(spacing: 0) {
                HStack {
                    Wordmark()
                    Spacer()
                    Button(action: done) {
                        Text("Passer")
                            .font(.subheadline.weight(.semibold)).foregroundStyle(Theme.textSecondary)
                            .frame(minWidth: 44, minHeight: 44)
                            .contentShape(.rect)
                    }
                    .opacity(current == pages.count - 1 ? 0 : 1)
                }
                .padding(.horizontal, Spacing.l).padding(.top, Spacing.xs)

                ScrollView(.horizontal) {
                    LazyHStack(spacing: 0) {
                        ForEach(pages) { item in
                            pageView(item)
                                .containerRelativeFrame(.horizontal)
                                .scrollTransition { content, phase in
                                    content
                                        .opacity(phase.isIdentity ? 1 : 0.25)
                                        .scaleEffect(phase.isIdentity ? 1 : 0.94)
                                }
                        }
                    }
                    .scrollTargetLayout()
                }
                .scrollTargetBehavior(.paging)
                .scrollIndicators(.hidden)
                .scrollPosition(id: $page)

                HStack(spacing: Spacing.xs) {
                    ForEach(pages) { item in
                        Capsule()
                            .fill(item.id == current ? Theme.textPrimary : Theme.hairline)
                            .frame(width: item.id == current ? 22 : 8, height: 8)
                    }
                }
                .animation(reduceMotion ? nil : .snappy, value: current)
                .padding(.bottom, Spacing.l)
                .accessibilityHidden(true)

                PrimaryButton(title: current == pages.count - 1 ? "Commencer" : "Continuer", icon: "arrow.right") {
                    if current == pages.count - 1 {
                        Haptics.success()
                        done()
                    } else {
                        Haptics.tap()
                        withAnimation(reduceMotion ? nil : .smooth(duration: 0.45)) { page = current + 1 }
                    }
                }
                .padding(.horizontal, Spacing.l).padding(.bottom, Spacing.m)
            }
            .readableColumn()
        }
    }

    private var current: Int { page ?? 0 }

    /// The page as designed when it fits. When it does not (very large text), a smaller picture and a page that
    /// scrolls, so that no line of the explanation is lost.
    private func pageView(_ item: Page) -> some View {
        ViewThatFits(in: .vertical) {
            VStack(spacing: 0) {
                Spacer(minLength: 0)
                pageContent(item, pictureHeight: 300)
                Spacer(minLength: 0)
            }
            ScrollView {
                pageContent(item, pictureHeight: 170)
            }
            .scrollIndicators(.hidden)
        }
        .padding(.horizontal, Spacing.m).padding(.top, Spacing.s)
    }

    private func pageContent(_ item: Page, pictureHeight: CGFloat) -> some View {
        VStack(alignment: .leading, spacing: Spacing.m) {
            Stage {
                Group {
                    if item.symbol.isEmpty {
                        HeroDishView()
                    } else {
                        Image(systemName: item.symbol)
                            .font(.system(size: pictureHeight / 3, weight: .thin))
                            .foregroundStyle(Theme.textOnStage)
                            .symbolEffect(.pulse, options: .repeating, isActive: !reduceMotion)
                            .accessibilityHidden(true)
                    }
                }
                .frame(height: pictureHeight)
            }
            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text(item.kicker).appText(.kicker).foregroundStyle(Theme.accent)
                Text(item.title).appText(.display).foregroundStyle(Theme.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                Text(item.text)
                    .font(.title3).foregroundStyle(Theme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(.horizontal, Spacing.xxs)
        }
    }
}
