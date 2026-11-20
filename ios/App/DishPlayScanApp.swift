import SwiftUI

@main
struct DishPlayScanApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(model)
                .onOpenURL { model.handle(url: $0) }
        }
    }
}

struct RootView: View {
    @EnvironmentObject var model: AppModel
    @AppStorage("onboarding.done") private var onboarded = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack {
            switch model.screen {
            case .connect:
                home
            case .scan:
                if let t = model.transport {
                    ScannerHost(transport: t, useLidar: model.useLidar && model.lidarSupported,
                                referenceWidthCm: Double(model.referenceWidthCm.replacingOccurrences(of: ",", with: ".")))
                        .transition(.opacity)
                } else {
                    home
                }
            }
        }
        .animation(reduceMotion ? nil : .smooth(duration: 0.35), value: model.screen)
    }

    @ViewBuilder private var home: some View {
        if onboarded {
            RootTabView().transition(.opacity)
        } else {
            OnboardingView {
                withAnimation(reduceMotion ? nil : .smooth(duration: 0.5)) { onboarded = true }
            }
            .transition(.opacity)
        }
    }
}

/// Creates the scan controller exactly once for the lifetime of the scanner screen.
struct ScannerHost: View {
    @StateObject private var controller: ScanController

    init(transport: ScanTransport, useLidar: Bool, referenceWidthCm: Double?) {
        _controller = StateObject(wrappedValue: ScanController(transport: transport, useLidar: useLidar, referenceWidthCm: referenceWidthCm))
    }

    var body: some View { ScannerView(controller: controller) }
}
