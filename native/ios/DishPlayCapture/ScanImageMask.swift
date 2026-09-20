import Foundation
import CoreImage
import CoreGraphics
import simd

enum ScanImageMask {
    /// Restrict an image to the projected box without changing its dimensions or camera intrinsics.
    /// This removes pixels outside the selection, not occluders or background inside its footprint.
    static func isolate(_ image: CIImage, polygon: [SIMD2<Float>]) -> CIImage? {
        guard polygon.count >= 3, polygon.allSatisfy({ $0.x.isFinite && $0.y.isFinite }) else { return nil }
        let width = Int(image.extent.width), height = Int(image.extent.height)
        guard width > 0, height > 0, width <= 4096, height <= 4096,
              let canvas = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8,
                  bytesPerRow: width, space: CGColorSpaceCreateDeviceGray(), bitmapInfo: CGImageAlphaInfo.none.rawValue) else { return nil }
        canvas.setFillColor(gray: 1, alpha: 1)
        canvas.beginPath()
        for (index, point) in polygon.enumerated() {
            let p = CGPoint(x: CGFloat(point.x) * CGFloat(width), y: (1-CGFloat(point.y)) * CGFloat(height))
            if index == 0 { canvas.move(to: p) } else { canvas.addLine(to: p) }
        }
        canvas.closePath(); canvas.fillPath()
        guard let cgMask = canvas.makeImage() else { return nil }
        let mask = CIImage(cgImage: cgMask).transformed(by: CGAffineTransform(translationX: image.extent.minX, y: image.extent.minY))
        return image.applyingFilter("CIBlendWithMask", parameters: [
            kCIInputBackgroundImageKey: CIImage(color: CIColor(red: 0.12, green: 0.12, blue: 0.12)).cropped(to: image.extent),
            kCIInputMaskImageKey: mask
        ]).cropped(to: image.extent)
    }
}
