import SwiftUI

/// First launch: three sliding pages that explain the whole app, then straight to the home screen.
struct OnboardingView: View {
    let done: () -> Void
    @State private var page: Int? = 0
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private struct Page: Identifiable {
        let id: Int
        let symbol: String
        let title: String
        let text: String
    }

    private let pages: [Page] = [
        Page(id: 0, symbol: "", title: "Vos plats en 3D", text: "Tournez autour d’une assiette avec l’iPhone : sa forme se construit sous vos yeux."),
        Page(id: 1, symbol: "cube.transparent", title: "Posez la boîte", text: "Touchez la table au pied du plat, puis ajustez la boîte à sa taille."),
        Page(id: 2, symbol: "arrow.triangle.2.circlepath", title: "Faites le tour", text: "L’anneau se remplit à mesure que chaque côté est vu. Quand il est complet, terminez."),
    ]

    var body: some View {
        ZStack {
            AmbientBackground()
            VStack(spacing: 0) {
                ScrollView(.horizontal) {
                    LazyHStack(spacing: 0) {
                        ForEach(pages) { item in
                            pageView(item)
                                .containerRelativeFrame(.horizontal)
                                .scrollTransition { content, phase in
                                    content
                                        .opacity(phase.isIdentity ? 1 : 0.25)
                                        .scaleEffect(phase.isIdentity ? 1 : 0.9)
                                }
                        }
                    }
                    .scrollTargetLayout()
                }
                .scrollTargetBehavior(.paging)
                .scrollIndicators(.hidden)
                .scrollPosition(id: $page)

                HStack(spacing: 8) {
                    ForEach(pages) { item in
                        Capsule()
                            .fill(item.id == current ? Theme.accent : Color.white.opacity(0.25))
                            .frame(width: item.id == current ? 22 : 8, height: 8)
                    }
                }
                .animation(reduceMotion ? nil : .snappy, value: current)
                .padding(.bottom, 22)
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
                .padding(.horizontal, 24)

                Button("Passer", action: done)
                    .font(.subheadline).foregroundStyle(.white.opacity(0.6))
                    .frame(height: 44)
                    .opacity(current == pages.count - 1 ? 0 : 1)
                    .padding(.bottom, 8)
            }
        }
    }

    private var current: Int { page ?? 0 }

    private func pageView(_ item: Page) -> some View {
        VStack(spacing: 18) {
            Spacer(minLength: 0)
            Group {
                if item.symbol.isEmpty {
                    HeroDishView()
                } else {
                    Image(systemName: item.symbol)
                        .font(.system(size: 110, weight: .thin))
                        .foregroundStyle(Theme.accent)
                        .symbolEffect(.pulse, options: .repeating, isActive: !reduceMotion)
                        .accessibilityHidden(true)
                }
            }
            .frame(height: 300)
            Text(item.title)
                .font(.system(.largeTitle, design: .rounded).bold())
                .multilineTextAlignment(.center)
            Text(item.text)
                .font(.title3).foregroundStyle(.white.opacity(0.75))
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 28)
    }
}
