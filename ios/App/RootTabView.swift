import SwiftUI

enum AppTab: Hashable { case home, library, settings }

/// The three places of the app. The system tab bar is used on purpose: it becomes Liquid Glass on
/// iOS 26 and later and keeps the standard look on iOS 17 and 18.
struct RootTabView: View {
    @EnvironmentObject var model: AppModel
    @State private var tab: AppTab = .home

    var body: some View {
        // `tabItem` rather than the newer `Tab` type: the app still supports iOS 17, where `Tab` does not exist.
        TabView(selection: $tab) {
            HomeView(openSettings: { tab = .settings }, openLibrary: { tab = .library })
                .tabItem { Label("Scanner", systemImage: "viewfinder") }
                .tag(AppTab.home)
            LibraryView(openSettings: { tab = .settings })
                .tabItem { Label("Mes plats", systemImage: "square.grid.2x2.fill") }
                .tag(AppTab.library)
            SettingsView()
                .tabItem { Label("Réglages", systemImage: "gearshape.fill") }
                .tag(AppTab.settings)
        }
        .tint(Theme.accent)
        .minimizingTabBar()
        .sensoryFeedback(.selection, trigger: tab)
        .onAppear {
            if let wanted = model.nextTab {
                tab = wanted
                model.nextTab = nil
            }
        }
    }
}
