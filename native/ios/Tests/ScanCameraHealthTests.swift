import Foundation

@main struct ScanCameraHealthTests {
    static func check(_ value: Bool, _ message: String) { precondition(value, message) }
    static func main() throws {
        var health = ScanCameraHealth()
        health.start(at: 100)
        check(health.failure(at: 107, lastRenderAt: nil, active: true) == nil, "Allow camera startup")
        check(health.failure(at: 108, lastRenderAt: 108, active: true) == .noFrames,
            "Rendering a blank scene must not masquerade as a camera image")
        check(!health.ready(lastRenderAt: 108), "No frame means no live camera")
        check(health.failure(at: 120, lastRenderAt: nil, active: false) == nil, "Background is not a camera failure")
        health.start(at: 130)
        health.receiveFrame(at: 131)
        check(!health.ready(lastRenderAt: 130), "A render before the first image cannot certify display")
        check(health.ready(lastRenderAt: 132), "A frame followed by rendering activates the preview")
        health.receiveFrame(at: 135)
        check(health.failure(at: 137, lastRenderAt: 132, active: true) == .noRendering,
            "Detect camera frames that arrive without continuous screen rendering")
        check(health.failure(at: 141, lastRenderAt: 141, active: true) == .stalledFrames,
            "A renderer replaying an old frame cannot hide a stopped camera")
        health.stop()
        check(health.failure(at: 200, lastRenderAt: nil, active: true) == nil, "A deliberate pause must not trigger recovery")
        check(!health.ready(lastRenderAt: 200), "A paused session is not live")
        health.start(at: 300)
        check(health.frameCount == 0 && !health.ready(lastRenderAt: 250), "Restart discards stale camera evidence")
        for frame in 0..<300 {
            let time = 300 + Double(frame)/30
            health.receiveFrame(at: time)
            check(health.failure(at: time, lastRenderAt: time, active: true) == nil, "A healthy 30fps stream stays live")
        }
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let log = ScanDiagnostics(folder: folder)
        for i in 0..<80 { log.record("event-\(i)", "startup") }
        let data = try Data(contentsOf: folder.appendingPathComponent("camera-diagnostics.json"))
        let events = try JSONSerialization.jsonObject(with: data) as! [[String: Any]]
        check(events.count == 64 && events.first?["name"] as? String == "event-16", "Startup diagnostics stay bounded")
        print("PASS: missing frames, black renderer, stalled camera, interruption, restart and bounded diagnostics")
    }
}
