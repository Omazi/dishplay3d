import Foundation

@main struct CaptureDeliveryTests {
    static func main() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        precondition(CaptureDelivery.read(from: root).uploadedAt == nil)
        var receipt = CaptureDelivery()
        receipt.stage = .uploading; receipt.sent = 6; receipt.total = 24
        try receipt.save(to: root)
        var recovered = CaptureDelivery.read(from: root)
        precondition(recovered.stage == .paused && recovered.sent == 6 && recovered.total == 24)
        precondition(recovered.uploadedAt == nil && !recovered.needsTracking)
        receipt.stage = .reconstructing; receipt.uploadedAt = Date(); receipt.jobID = UUID().uuidString
        try receipt.save(to: root)
        recovered = CaptureDelivery.read(from: root)
        precondition(recovered.stage == .reconstructing && recovered.needsTracking)
        precondition(recovered.jobID == receipt.jobID && recovered.uploadedAt == receipt.uploadedAt)
        receipt.stage = .downloading
        try receipt.save(to: root)
        recovered = CaptureDelivery.read(from: root)
        precondition(recovered.stage == .paused && recovered.needsTracking && recovered.uploadedAt != nil)
        receipt.stage = .failed; receipt.failureCode = "INSUFFICIENT_MATCHES"
        try receipt.save(to: root)
        recovered = CaptureDelivery.read(from: root)
        precondition(recovered.stage == .failed && recovered.failureCode == "INSUFFICIENT_MATCHES" && !recovered.needsTracking)
        receipt.stage = .ready
        try receipt.save(to: root)
        precondition(CaptureDelivery.read(from: root).stage == .ready)
        try Data("incomplete receipt".utf8).write(to: root.appendingPathComponent("delivery.json"))
        precondition(CaptureDelivery.read(from: root).uploadedAt == nil, "Corrupt metadata must never claim an upload succeeded")
        print("PASS: durable receipt, partial upload recovery, PC continuity, download recovery, failure and success")
    }
}
