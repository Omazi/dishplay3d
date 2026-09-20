import Foundation

/// Separate from capture.json: saving camera metadata cannot erase server receipts.
struct CaptureDelivery: Codable {
    enum Stage: String, Codable {
        case saved, paired, uploading, uploaded, queued, reconstructing, downloading, ready, paused, failed
    }
    var stage: Stage = .saved
    var sent = 0
    var total = 0
    var uploadedAt: Date?
    var checkedAt: Date?
    var jobID: String?
    var message: String?
    var failureCode: String?
    var dishName: String?
    var restaurantName: String?
    var dishID: String?

    var title: String {
        switch stage {
        case .saved: return "Saved on this iPhone"
        case .paired: return "Dish linked · not sent yet"
        case .uploading: return "Sending your scan…"
        case .uploaded: return "Upload confirmed"
        case .queued: return "Uploaded · waiting for your PC"
        case .reconstructing: return "Uploaded · building your 3D dish"
        case .downloading: return "3D ready · downloading to this iPhone"
        case .ready: return "Your 3D dish is ready"
        case .paused: return uploadedAt == nil ? "Upload interrupted · resume below" : "Upload confirmed · tracking interrupted"
        case .failed: return "Reconstruction failed · photos preserved"
        }
    }
    var needsTracking: Bool {
        uploadedAt != nil && stage != .ready && stage != .failed
    }
    mutating func recoverAfterInterruption() {
        if stage == .uploading || stage == .downloading { stage = .paused }
    }
    static func read(from root: URL) -> CaptureDelivery {
        guard let data = try? Data(contentsOf: root.appendingPathComponent("delivery.json")),
              var value = try? JSONDecoder().decode(Self.self, from: data) else { return Self() }
        value.recoverAfterInterruption()
        return value
    }
    func save(to root: URL) throws {
        try JSONEncoder().encode(self).write(to: root.appendingPathComponent("delivery.json"), options: .atomic)
    }
}
