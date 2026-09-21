import Foundation

/// Detects a missing camera stream separately from a renderer that never displays it.
struct ScanCameraHealth {
    enum Failure: String { case noFrames, stalledFrames, noRendering }
    private(set) var startedAt: TimeInterval?
    private(set) var firstFrameAt: TimeInterval?
    private(set) var lastFrameAt: TimeInterval?
    private(set) var frameCount = 0

    mutating func start(at time: TimeInterval) {
        startedAt = time; firstFrameAt = nil; lastFrameAt = nil; frameCount = 0
    }
    mutating func receiveFrame(at time: TimeInterval) {
        guard startedAt != nil else { return }
        if firstFrameAt == nil { firstFrameAt = time }
        lastFrameAt = time; frameCount += 1
    }
    mutating func stop() { startedAt = nil }
    func failure(at time: TimeInterval, lastRenderAt: TimeInterval?, active: Bool) -> Failure? {
        guard active, let start = startedAt else { return nil }
        guard let first = firstFrameAt, let last = lastFrameAt else { return time-start >= 8 ? .noFrames : nil }
        if time-last >= 6 { return .stalledFrames }
        let rendered = lastRenderAt.flatMap { $0 >= first ? $0 : nil }
        if time-(rendered ?? first) >= 5 { return .noRendering }
        return nil
    }
    func ready(lastRenderAt: TimeInterval?) -> Bool {
        guard startedAt != nil, let first = firstFrameAt, let render = lastRenderAt else { return false }
        return render >= first
    }
}

/// SceneKit calls render delegates off the main thread. Keep one timestamp, not a queue of UI tasks.
final class ScanRenderHeartbeat: @unchecked Sendable {
    private let lock = NSLock()
    private var time: TimeInterval?
    func mark(at time: TimeInterval) { lock.lock(); self.time = time; lock.unlock() }
    func reset() { lock.lock(); time = nil; lock.unlock() }
    var latest: TimeInterval? { lock.lock(); defer { lock.unlock() }; return time }
}
