import AVFoundation
import Foundation
import ImageIO
import UniformTypeIdentifiers

enum VideoPreparationError: Error {
    case unreadable, tooLarge, duration, tooFewViews, saveFailed

    var message: String {
        switch self {
        case .unreadable: return "This video could not be opened. Choose another video or record your dish again."
        case .tooLarge: return "Choose a video smaller than 250 MB, or film your dish in the app."
        case .duration: return "Use a video lasting 5 to 90 seconds. Aim for a slow 20–40 second tour of the dish."
        case .tooFewViews: return "Video saved, but there are too few clear, different views. Try again in good light, moving slowly around the stationary dish."
        case .saveFailed: return "The video could not be prepared. Free some storage, then retry from your saved video."
        }
    }
}

/// A bounded, sequential conversion. Only one decoded frame and 24 small fingerprints are retained.
/// This checks image usability, not angular coverage, object recognition or reconstruction success.
enum VideoFrameExtractor {
    static let maximumBytes = 250 * 1024 * 1024
    static let maximumFrames = 24
    static let minimumFrames = 8

    static func validateSize(_ video: URL) throws {
        let bytes = try video.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        guard bytes > 0 else { throw VideoPreparationError.unreadable }
        guard bytes <= maximumBytes else { throw VideoPreparationError.tooLarge }
    }

    static func extract(from video: URL, to destination: URL,
                        progress: @escaping @Sendable (Double) async -> Void = { _ in }) async throws -> Int {
        try validateSize(video)
        let asset = AVURLAsset(url: video)
        let duration: Double
        do {
            duration = try await asset.load(.duration).seconds
            guard !(try await asset.loadTracks(withMediaType: .video)).isEmpty else {
                throw VideoPreparationError.unreadable
            }
        } catch { throw VideoPreparationError.unreadable }
        guard duration.isFinite, (5...90).contains(duration) else { throw VideoPreparationError.duration }
        let generator = AVAssetImageGenerator(asset: asset)
        generator.appliesPreferredTrackTransform = true
        generator.maximumSize = CGSize(width: 1600, height: 1600)
        generator.requestedTimeToleranceBefore = CMTime(seconds: 0.08, preferredTimescale: 600)
        generator.requestedTimeToleranceAfter = CMTime(seconds: 0.08, preferredTimescale: 600)

        // Never expose a partial set to upload. Failed/cancelled conversions preserve the source movie.
        let staging = destination.deletingLastPathComponent().appendingPathComponent("VideoFrames-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: staging, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: staging); generator.cancelAllCGImageGeneration() }
        var fingerprints: [[UInt8]] = []
        for slot in 0..<maximumFrames {
            try Task.checkCancellation()
            var best: (score: Double, fingerprint: [UInt8], jpeg: Data)?
            for offset in [0.3, 0.7] {
                let seconds = (Double(slot) + offset) * duration / Double(maximumFrames)
                do {
                    let (image, _) = try await generator.image(at: CMTime(seconds: seconds, preferredTimescale: 600))
                    let candidate = autoreleasepool { usableJPEG(image, previous: fingerprints) }
                    if let candidate, best == nil || candidate.score > best!.score { best = candidate }
                } catch is CancellationError { throw CancellationError() }
                catch { continue } // A damaged sample must not discard every other usable view.
            }
            if let best {
                let filename = String(format: "video-%03d.jpg", fingerprints.count)
                try best.jpeg.write(to: staging.appendingPathComponent(filename), options: .atomic)
                fingerprints.append(best.fingerprint)
            }
            await progress(Double(slot + 1) / Double(maximumFrames))
        }
        guard fingerprints.count >= minimumFrames else { throw VideoPreparationError.tooFewViews }
        // A retry must not silently overwrite another capture's originals.
        try FileManager.default.createDirectory(at: destination, withIntermediateDirectories: true)
        let existing = try FileManager.default.contentsOfDirectory(atPath: destination.path)
        guard existing.isEmpty else { throw VideoPreparationError.saveFailed }
        try FileManager.default.removeItem(at: destination)
        try FileManager.default.moveItem(at: staging, to: destination)
        return fingerprints.count
    }

    private static func usableJPEG(_ image: CGImage, previous: [[UInt8]]) -> (score: Double, fingerprint: [UInt8], jpeg: Data)? {
        guard min(image.width, image.height) >= 240 else { return nil }
        let side = 96
        var gray = [UInt8](repeating: 0, count: side * side)
        let rendered = gray.withUnsafeMutableBytes { bytes -> Bool in
            guard let context = CGContext(data: bytes.baseAddress, width: side, height: side, bitsPerComponent: 8,
                                          bytesPerRow: side, space: CGColorSpaceCreateDeviceGray(), bitmapInfo: 0) else { return false }
            context.interpolationQuality = .medium
            context.draw(image, in: CGRect(x: 0, y: 0, width: side, height: side))
            return true
        }
        guard rendered else { return nil }
        let mean = gray.reduce(0.0) { $0 + Double($1) } / Double(gray.count)
        let clipped = Double(gray.filter { $0 < 8 || $0 > 248 }.count) / Double(gray.count)
        guard mean > 18, mean < 240, clipped < 0.8 else { return nil }
        var squared = 0.0, sum = 0.0
        for y in 8..<88 {
            for x in 8..<88 {
                let i = y * side + x
                let laplacian = Double(4 * Int(gray[i]) - Int(gray[i-1]) - Int(gray[i+1]) - Int(gray[i-side]) - Int(gray[i+side]))
                sum += laplacian; squared += laplacian * laplacian
            }
        }
        let sharpness = squared / 6400 - pow(sum / 6400, 2)
        guard sharpness >= 10 else { return nil }
        // Average 6x6 cells rather than sampling individual pixels, to tolerate codec noise.
        var fingerprint: [UInt8] = []
        for y in 0..<16 {
            for x in 0..<16 {
                var total = 0
                for dy in 0..<6 { for dx in 0..<6 { total += Int(gray[(y*6+dy)*side+x*6+dx]) } }
                fingerprint.append(UInt8(total / 36))
            }
        }
        guard !previous.contains(where: { old in
            zip(old, fingerprint).reduce(0.0) { $0 + abs(Double($1.0) - Double($1.1)) } / 256 < 2.0
        }) else { return nil }
        let bytes = NSMutableData()
        guard let encoder = CGImageDestinationCreateWithData(bytes, UTType.jpeg.identifier as CFString, 1, nil) else { return nil }
        CGImageDestinationAddImage(encoder, image, [kCGImageDestinationLossyCompressionQuality: 0.9] as CFDictionary)
        guard CGImageDestinationFinalize(encoder) else { return nil }
        return (sharpness, fingerprint, bytes as Data)
    }
}
