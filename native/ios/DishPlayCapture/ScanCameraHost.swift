import UIKit

/// Present ordinary UIKit/SwiftUI controls before allocating the AR renderer.
/// A positive layout inside a window is required before starting the camera session.
@MainActor
final class ScanCameraHost: UIView {
    var onReady: ((ScanCameraHost) -> Void)?
    private var scheduled = false
    override func didMoveToWindow() { super.didMoveToWindow(); notifyIfReady() }
    override func layoutSubviews() { super.layoutSubviews(); notifyIfReady() }
    private func notifyIfReady() {
        guard !scheduled, window != nil, bounds.width > 1, bounds.height > 1 else { return }
        scheduled = true
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.scheduled = false
            guard self.window != nil, self.bounds.width > 1, self.bounds.height > 1 else { return }
            self.onReady?(self)
        }
    }
}
