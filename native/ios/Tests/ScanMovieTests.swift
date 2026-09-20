import AVFoundation
import Foundation

@main struct ScanMovieTests {
    struct Failure: Error { let message: String }
    static func require(_ value: Bool, _ message: String) throws {
        if !value { throw Failure(message: message) }
    }
    static func main() async throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let url = folder.appendingPathComponent("scan.mov")
        let recorder = ScanMovieRecorder(url: url, transform: CGAffineTransform(rotationAngle: .pi / 2))
        var maybeBuffer: CVPixelBuffer?
        CVPixelBufferCreate(kCFAllocatorDefault, 1600, 1000, kCVPixelFormatType_32BGRA,
                            [kCVPixelBufferIOSurfacePropertiesKey as String: [:]] as CFDictionary, &maybeBuffer)
        guard let buffer = maybeBuffer else { throw Failure(message: "Pixel buffer allocation") }
        CVPixelBufferLockBaseAddress(buffer, [])
        memset(CVPixelBufferGetBaseAddress(buffer), 180, CVPixelBufferGetDataSize(buffer))
        CVPixelBufferUnlockBaseAddress(buffer, [])
        try require(recorder.append(buffer, timestamp: 900), "First frame accepted")
        try require(!recorder.append(buffer, timestamp: 900), "Duplicate timestamps rejected")
        try require(!recorder.append(buffer, timestamp: 899), "Out-of-order timestamps rejected")
        for index in 1...20 {
            try await Task.sleep(for: .milliseconds(45))
            recorder.append(buffer, timestamp: 900 + Double(index) * 0.1)
        }
        let output = try await recorder.finish()
        try require(output == url, "A real movie is saved")
        try require(!recorder.append(buffer, timestamp: 904), "Closed writer cannot accept more camera buffers")
        let asset = AVURLAsset(url: url)
        let duration = try await asset.load(.duration).seconds
        try require(duration > 0.2 && duration < 3, "Relative timestamps produce a short movie, not device uptime")
        guard let track = try await asset.loadTracks(withMediaType: .video).first else { throw Failure(message: "Missing video track") }
        let size = try await track.load(.naturalSize)
        try require(max(size.width, size.height) <= 1280, "Recording resolution is capped")
        let transform = try await track.load(.preferredTransform)
        try require(abs(transform.b - 1) < 0.01, "Portrait camera orientation preserved")
        let generator = AVAssetImageGenerator(asset: asset)
        generator.appliesPreferredTrackTransform = true
        let frame = try await generator.image(at: CMTime(seconds: 0.1, preferredTimescale: 600)).image
        try require(frame.height > frame.width, "Movie decodes upright in portrait")
        let emptyURL = folder.appendingPathComponent("empty.mov")
        let empty = ScanMovieRecorder(url: emptyURL, transform: .identity)
        let absent = try await empty.finish()
        try require(absent == nil && !FileManager.default.fileExists(atPath: emptyURL.path), "Closing before the first camera frame is safe")
        let duplicate = ScanMovieRecorder(url: url, transform: .identity)
        duplicate.append(buffer, timestamp: 0)
        var failed = false
        do { _ = try await duplicate.finish() } catch { failed = true }
        try require(failed, "Existing originals must never be overwritten")
        let preserved = try await AVURLAsset(url: url).load(.duration).seconds
        try require(preserved == duration, "Existing video preserved on encoder error")
        print("PASS: real AR-feed movie encoding/decoding, orientation, backpressure, timestamps, close, empty and preserved originals")
    }
}
