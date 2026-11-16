import ARKit
import CoreImage
import CryptoKit
import Foundation
import ImageIO
import ScanCore

/// Everything needed to encode one keyframe AFTER the ARFrame has been released.
// Owns a private copy of the pixel buffer; handed to one background encode task only.
struct CapturedFrame: @unchecked Sendable {
    var frameID: Int
    var epoch: Int
    var timestamp: Double
    var pixelBuffer: CVPixelBuffer           // our own copy, not ARKit's pool buffer
    var intrinsics: Intrinsics
    var worldFromCameraAR: Mat4
    var trackingNormal: Bool
    var exposure: Double
    var formatText: String
    var quality: FrameMeta.Quality
    var depth: Data?
    var confidence: Data?
    var depthSize: (Int, Int)?
}

enum FrameEncoder {
    static let context = CIContext(options: [.cacheIntermediates: false])
    static let srgb = CGColorSpace(name: CGColorSpace.sRGB)!

    /// JPEG (quality 0.9, sensor-native orientation, full resolution) + contract metadata.
    static func encode(_ f: CapturedFrame, sessionID: String) throws -> (jpeg: Data, meta: Data) {
        let image = CIImage(cvPixelBuffer: f.pixelBuffer)
        let opts = [CIImageRepresentationOption(rawValue: kCGImageDestinationLossyCompressionQuality as String): 0.9]
        guard let jpeg = context.jpegRepresentation(of: image, colorSpace: srgb, options: opts) else {
            throw CocoaError(.fileWriteUnknown)
        }
        let w = CVPixelBufferGetWidth(f.pixelBuffer), h = CVPixelBufferGetHeight(f.pixelBuffer)
        let sha = SHA256.hash(data: jpeg).map { String(format: "%02x", $0) }.joined()
        var depthMeta: FrameMeta.Depth?
        if let (dw, dh) = f.depthSize {
            depthMeta = FrameMeta.Depth(width: dw, height: dh, intrinsics: f.intrinsics.scaled(toWidth: dw, height: dh), timestamp_s: f.timestamp)
        }
        let meta = FrameMeta(sessionID: sessionID, frameID: f.frameID, epoch: f.epoch, timestamp: f.timestamp,
                             image: .init(width: w, height: h, sha256: sha),
                             intrinsics: f.intrinsics, worldFromCameraAR: f.worldFromCameraAR,
                             tracking: .init(state: f.trackingNormal ? "normal" : "limited", reason: nil),
                             cameraFormat: .init(width: w, height: h, fps: 30, device: f.formatText, exposure_s: f.exposure),
                             quality: f.quality, depth: depthMeta)
        return (jpeg, try meta.jsonData())
    }

    /// Copy ARKit's pixel buffer so the ARFrame can be released immediately (ARKit's pool is small).
    static func copy(_ src: CVPixelBuffer) -> CVPixelBuffer? {
        let fmt = CVPixelBufferGetPixelFormatType(src)
        let w = CVPixelBufferGetWidth(src), h = CVPixelBufferGetHeight(src)
        var dst: CVPixelBuffer?
        let attrs = [kCVPixelBufferIOSurfacePropertiesKey as String: [:] as [String: Any]] as CFDictionary
        guard CVPixelBufferCreate(nil, w, h, fmt, attrs, &dst) == kCVReturnSuccess, let dst else { return nil }
        // Keep the YCbCr matrix / colour primaries so the JPEG has the same colours as the camera image.
        if let att = CVBufferCopyAttachments(src, .shouldPropagate) { CVBufferSetAttachments(dst, att, .shouldPropagate) }
        CVPixelBufferLockBaseAddress(src, .readOnly)
        CVPixelBufferLockBaseAddress(dst, [])
        defer {
            CVPixelBufferUnlockBaseAddress(dst, [])
            CVPixelBufferUnlockBaseAddress(src, .readOnly)
        }
        let planes = CVPixelBufferGetPlaneCount(src)
        if planes == 0 {
            copyRows(CVPixelBufferGetBaseAddress(src), CVPixelBufferGetBytesPerRow(src), CVPixelBufferGetBaseAddress(dst),
                     CVPixelBufferGetBytesPerRow(dst), h)
        } else {
            for p in 0..<planes {
                copyRows(CVPixelBufferGetBaseAddressOfPlane(src, p), CVPixelBufferGetBytesPerRowOfPlane(src, p),
                         CVPixelBufferGetBaseAddressOfPlane(dst, p), CVPixelBufferGetBytesPerRowOfPlane(dst, p),
                         CVPixelBufferGetHeightOfPlane(src, p))
            }
        }
        return dst
    }

    private static func copyRows(_ s: UnsafeMutableRawPointer?, _ sbpr: Int, _ d: UnsafeMutableRawPointer?, _ dbpr: Int, _ rows: Int) {
        guard let s, let d else { return }
        let n = min(sbpr, dbpr)
        for r in 0..<rows { memcpy(d + r * dbpr, s + r * sbpr, n) }
    }

    /// Tightly packed copy of a single-plane buffer (depth float32 / confidence uint8).
    static func packed(_ buf: CVPixelBuffer, bytesPerPixel: Int) -> Data {
        CVPixelBufferLockBaseAddress(buf, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buf, .readOnly) }
        let w = CVPixelBufferGetWidth(buf), h = CVPixelBufferGetHeight(buf), bpr = CVPixelBufferGetBytesPerRow(buf)
        guard let base = CVPixelBufferGetBaseAddress(buf) else { return Data() }
        var out = Data(count: w * h * bytesPerPixel)
        out.withUnsafeMutableBytes { dst in
            for r in 0..<h { memcpy(dst.baseAddress! + r * w * bytesPerPixel, base + r * bpr, w * bytesPerPixel) }
        }
        return out
    }

    /// Cheap sharpness (Laplacian variance) and mean luma on a sparse grid of the luma plane.
    static func lumaStats(_ buf: CVPixelBuffer, roi: CGRect?) -> (sharpness: Double, mean: Double) {
        CVPixelBufferLockBaseAddress(buf, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buf, .readOnly) }
        guard CVPixelBufferGetPlaneCount(buf) >= 1, let base = CVPixelBufferGetBaseAddressOfPlane(buf, 0) else { return (0, 0) }
        let w = CVPixelBufferGetWidthOfPlane(buf, 0), h = CVPixelBufferGetHeightOfPlane(buf, 0)
        let bpr = CVPixelBufferGetBytesPerRowOfPlane(buf, 0)
        let p = base.assumingMemoryBound(to: UInt8.self)
        let r = (roi ?? CGRect(x: 0, y: 0, width: w, height: h)).intersection(CGRect(x: 2, y: 2, width: w - 4, height: h - 4))
        guard r.width > 16, r.height > 16 else { return (0, 0) }
        let step = max(2, Int(max(r.width, r.height)) / 96)
        var sum = 0.0, sum2 = 0.0, lsum = 0.0, n = 0.0
        var y = Int(r.minY)
        while y < Int(r.maxY) {
            var x = Int(r.minX)
            while x < Int(r.maxX) {
                let c = Double(p[y * bpr + x])
                let lap = Double(p[y * bpr + x - 1]) + Double(p[y * bpr + x + 1]) + Double(p[(y - 1) * bpr + x]) + Double(p[(y + 1) * bpr + x]) - 4 * c
                sum += lap; sum2 += lap * lap; lsum += c; n += 1
                x += step
            }
            y += step
        }
        guard n > 0 else { return (0, 0) }
        let mean = sum / n
        return (sum2 / n - mean * mean, lsum / n)
    }
}
