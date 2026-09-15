import SwiftUI

@main
@MainActor
struct DishPlayCaptureApp: App {
    @StateObject private var model = CaptureModel()

    var body: some Scene {
        WindowGroup { CaptureScreen(model: model) }
    }
}
