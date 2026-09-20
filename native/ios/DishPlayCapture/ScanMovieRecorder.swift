import AVFoundation
import CoreImage
import Foundation

/// Records the AR camera feed itself; never opens a competing AVCaptureSession.
/// One admitted camera buffer, a three-buffer output pool, 720p/15fps hardware H.264.
final class ScanMovieRecorder: @unchecked Sendable {
    private let queue = DispatchQueue(label: "app.dishplay.scan.movie", qos: .utility)
    private let gate = NSLock()
    private var pending = false
    private var closing = false
    private var lastAdmitted = -Double.infinity
    private let onFailure: @Sendable () -> Void
    private let url: URL
    private let transform: CGAffineTransform
    private let context = CIContext(options: [.cacheIntermediates: false])
    private var writer: AVAssetWriter?
    private var input: AVAssetWriterInput?
    private var adaptor: AVAssetWriterInputPixelBufferAdaptor?
    private var firstTime: Double?
    private var lastTime = CMTime.zero
    private var frames = 0
    private var failure: Error?

    init(url: URL, transform: CGAffineTransform, onFailure: @escaping @Sendable () -> Void = {}) {
        self.url = url; self.transform = transform; self.onFailure = onFailure
    }
    @discardableResult
    func append(_ buffer: CVPixelBuffer, timestamp: Double) -> Bool {
        gate.lock()
        guard !closing, !pending, timestamp.isFinite, timestamp - lastAdmitted >= 1.0 / 15 else { gate.unlock(); return false }
        pending = true; lastAdmitted = timestamp
        gate.unlock()
        queue.async {
            defer { self.gate.lock(); self.pending = false; self.gate.unlock() }
            guard self.failure == nil else { return }
            do { try autoreleasepool { try self.write(buffer, timestamp: timestamp) } }
            catch { self.failure = error; self.onFailure() }
        }
        return true
    }
    private func write(_ buffer: CVPixelBuffer, timestamp: Double) throws {
        let image = CIImage(cvPixelBuffer: buffer)
        if writer == nil {
            let scale = min(1, 1280 / max(image.extent.width, image.extent.height))
            let width = Int(image.extent.width * scale) / 2 * 2
            let height = Int(image.extent.height * scale) / 2 * 2
            let writer = try AVAssetWriter(outputURL: url, fileType: .mov)
            let input = AVAssetWriterInput(mediaType: .video, outputSettings: [
                AVVideoCodecKey: AVVideoCodecType.h264, AVVideoWidthKey: width, AVVideoHeightKey: height,
                AVVideoCompressionPropertiesKey: [AVVideoAverageBitRateKey: 2_500_000, AVVideoExpectedSourceFrameRateKey: 15],
            ])
            input.expectsMediaDataInRealTime = true
            input.transform = transform
            let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
                kCVPixelBufferWidthKey as String: width, kCVPixelBufferHeightKey as String: height,
                kCVPixelBufferIOSurfacePropertiesKey as String: [:],
            ])
            guard writer.canAdd(input) else { throw MovieError.writeFailed }
            writer.add(input)
            guard writer.startWriting() else { throw writer.error ?? MovieError.writeFailed }
            writer.startSession(atSourceTime: .zero)
            self.writer = writer; self.input = input; self.adaptor = adaptor
        }
        guard let writer, let input, let adaptor else { throw MovieError.writeFailed }
        guard writer.status == .writing else { throw writer.error ?? MovieError.writeFailed }
        guard input.isReadyForMoreMediaData, let pool = adaptor.pixelBufferPool else { return }
        var output: CVPixelBuffer?
        let result = CVPixelBufferPoolCreatePixelBufferWithAuxAttributes(kCFAllocatorDefault, pool,
            [kCVPixelBufferPoolAllocationThresholdKey as String: 3] as CFDictionary, &output)
        if result == kCVReturnWouldExceedAllocationThreshold { return }
        guard result == kCVReturnSuccess, let output else { throw MovieError.writeFailed }
        let scaled = image.transformed(by: CGAffineTransform(scaleX: CGFloat(CVPixelBufferGetWidth(output)) / image.extent.width,
            y: CGFloat(CVPixelBufferGetHeight(output)) / image.extent.height))
        context.render(scaled, to: output)
        let origin = firstTime ?? timestamp
        let time = CMTime(seconds: timestamp - origin, preferredTimescale: 600)
        if frames > 0 && time <= lastTime { return }
        guard adaptor.append(output, withPresentationTime: time) else { throw writer.error ?? MovieError.writeFailed }
        firstTime = origin; lastTime = time; frames += 1
    }
    func finish() async throws -> URL? {
        try await withCheckedThrowingContinuation { continuation in
            gate.lock()
            guard !closing else { gate.unlock(); continuation.resume(throwing: MovieError.alreadyClosed); return }
            closing = true
            gate.unlock()
            queue.async {
                if let failure = self.failure {
                    self.writer?.cancelWriting()
                    continuation.resume(throwing: failure)
                    return
                }
                guard self.frames > 0, let writer = self.writer, let input = self.input else {
                    self.writer?.cancelWriting()
                    try? FileManager.default.removeItem(at: self.url)
                    continuation.resume(returning: nil)
                    return
                }
                writer.endSession(atSourceTime: self.lastTime + CMTime(value: 1, timescale: 15))
                input.markAsFinished()
                writer.finishWriting {
                    if writer.status == .completed { continuation.resume(returning: self.url) }
                    else { continuation.resume(throwing: writer.error ?? MovieError.writeFailed) }
                }
            }
        }
    }
    enum MovieError: LocalizedError {
        case writeFailed, alreadyClosed
        var errorDescription: String? { "The video could not be saved. Your captured views remain available." }
    }
}
