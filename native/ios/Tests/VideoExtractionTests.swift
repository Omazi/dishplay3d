import AVFoundation
import Foundation
import ImageIO

/// Real movie encode/decode tests, run on the hosted Mac. They do not simulate a physical camera.
@main
struct VideoExtractionTests {
    static func require(_ condition: @autoclosure () throws -> Bool, _ message: String) throws {
        if try condition() == false { throw TestFailure(message: message) }
    }
    struct TestFailure: Error { let message: String }

    static func movie(at url: URL, moving: Bool = true, dark: Bool = false, seconds: Int = 6) async throws {
        let writer = try AVAssetWriter(outputURL: url, fileType: .mov)
        let input = AVAssetWriterInput(mediaType: .video, outputSettings: [
            AVVideoCodecKey: AVVideoCodecType.h264,
            AVVideoWidthKey: 480, AVVideoHeightKey: 320,
        ])
        // The JPEG output must respect this portrait track transform.
        input.transform = CGAffineTransform(rotationAngle: .pi / 2)
        let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32ARGB,
            kCVPixelBufferWidthKey as String: 480, kCVPixelBufferHeightKey as String: 320,
        ])
        writer.add(input)
        try require(writer.startWriting(), "Writer should start")
        writer.startSession(atSourceTime: .zero)
        for index in 0..<(seconds * 12) {
            while !input.isReadyForMoreMediaData {
                try require(writer.status == .writing, "Writer failed while waiting")
                try await Task.sleep(for: .milliseconds(5))
            }
            var buffer: CVPixelBuffer?
            CVPixelBufferPoolCreatePixelBuffer(nil, adaptor.pixelBufferPool!, &buffer)
            let pixels = buffer!
            CVPixelBufferLockBaseAddress(pixels, [])
            let base = CVPixelBufferGetBaseAddress(pixels)!.assumingMemoryBound(to: UInt8.self)
            let stride = CVPixelBufferGetBytesPerRow(pixels)
            for y in 0..<320 {
                for x in 0..<480 {
                    let p = base + y * stride + x * 4
                    let shifted = x + (moving ? index * 7 : 0)
                    let checker = ((shifted / 29) + (y / 23)) % 2
                    p[0] = 255
                    p[1] = dark ? 0 : UInt8(40 + (shifted / 3 + y / 4) % 140)
                    p[2] = dark ? 0 : UInt8(checker == 0 ? 60 : 200)
                    p[3] = dark ? 0 : UInt8(60 + (shifted / 5 + y / 3) % 130)
                }
            }
            CVPixelBufferUnlockBaseAddress(pixels, [])
            try require(adaptor.append(pixels, withPresentationTime: CMTime(value: Int64(index), timescale: 12)), "Frame should encode")
        }
        input.markAsFinished()
        writer.endSession(atSourceTime: CMTime(seconds: Double(seconds), preferredTimescale: 600))
        await writer.finishWriting()
        try require(writer.status == .completed, "Movie should finish")
    }

    static func main() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("dishplay-video-tests-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        for kind in ["moving", "stationary", "dark", "short"] {
            let video = root.appendingPathComponent(kind + ".mov")
            let photos = root.appendingPathComponent(kind + "-photos")
            try FileManager.default.createDirectory(at: photos, withIntermediateDirectories: true)
            try await movie(at: video, moving: kind != "stationary", dark: kind == "dark", seconds: kind == "short" ? 2 : 6)
            let original = try Data(contentsOf: video)
            if kind == "moving" {
                let count = try await VideoFrameExtractor.extract(from: video, to: photos)
                try require((8...24).contains(count), "A changing movie should yield 8–24 views")
                let images = try FileManager.default.contentsOfDirectory(at: photos, includingPropertiesForKeys: nil)
                try require(images.count == count, "Only final JPEGs should be exposed")
                for file in images {
                    let source = CGImageSourceCreateWithURL(file as CFURL, nil)!
                    let image = CGImageSourceCreateImageAtIndex(source, 0, nil)!
                    try require(image.height > image.width, "Track orientation must be applied")
                    try require(max(image.width, image.height) <= 1600, "Decoded images must be bounded")
                }
                do {
                    _ = try await VideoFrameExtractor.extract(from: video, to: photos)
                    throw TestFailure(message: "Existing photos must never be overwritten")
                } catch VideoPreparationError.saveFailed {}
                try require(try FileManager.default.contentsOfDirectory(atPath: photos.path).count == count, "Retry must preserve existing photos")
            } else {
                do {
                    _ = try await VideoFrameExtractor.extract(from: video, to: photos)
                    throw TestFailure(message: "Unusable movie should not become a scan: " + kind)
                } catch let failure as VideoPreparationError {
                    if kind == "short" {
                        guard case .duration = failure else { throw failure }
                    } else {
                        guard case .tooFewViews = failure else { throw failure }
                    }
                }
                let partials = try FileManager.default.contentsOfDirectory(atPath: photos.path)
                try require(partials.isEmpty, "Failed conversion must not expose partial frames")
            }
            try require(try Data(contentsOf: video) == original, "The original movie must remain intact")
            print("PASS video extraction: " + kind)
        }
        let remaining = try FileManager.default.contentsOfDirectory(atPath: root.path)
        try require(!remaining.contains(where: { $0.hasPrefix("VideoFrames-") }), "Staging directories should be cleaned")
    }
}
