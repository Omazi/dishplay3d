import Foundation
import CoreImage
import CoreGraphics
import ImageIO
import simd

@main struct ScanImageMaskTests {
    static func check(_ condition: Bool, _ message: String) { precondition(condition, message) }
    static func main() throws {
        let context = CIContext(options: [.useSoftwareRenderer: true, .cacheIntermediates: false])
        let extent = CGRect(x: 0, y: 0, width: 160, height: 100)
        let original = CIImage(color: CIColor(red: 1, green: 0, blue: 0)).cropped(to: extent)
        // An asymmetric selection catches mirrored/rotated mask coordinates.
        let polygon: [SIMD2<Float>] = [SIMD2(0.1,0.1), SIMD2(0.4,0.1), SIMD2(0.4,0.3), SIMD2(0.1,0.3)]
        let selected = ScanImageMask.isolate(original, polygon: polygon)!
        check(selected.extent == original.extent, "Selection must preserve dimensions and camera calibration")
        func pixel(_ source: CIImage, x: Int, y: Int) -> [UInt8] {
            var value = [UInt8](repeating: 0, count: 4)
            context.render(source, toBitmap: &value, rowBytes: 4, bounds: CGRect(x: x,y: y,width: 1,height: 1),
                format: .RGBA8, colorSpace: CGColorSpaceCreateDeviceRGB())
            return value
        }
        let inside = pixel(selected, x: 32, y: 80)
        check(inside[0] > 240 && inside[1] < 10, "Top-left sensor selection must retain top-left source color")
        for (x,y) in [(32,20),(120,80),(120,20)] {
            let p = pixel(selected, x: x, y: y)
            check(abs(Int(p[0])-Int(p[1])) < 3 && p[0] < 150, "Pixels outside the selection must become neutral")
        }
        check(pixel(original,x: 120,y: 20)[0] > 240, "Masking must leave the preserved original unchanged")
        check(ScanImageMask.isolate(original,polygon: []) == nil, "Missing projection cannot silently upload an unmasked image")
        check(ScanImageMask.isolate(original,polygon: [SIMD2(.nan,0),SIMD2(1,0),SIMD2(1,1)]) == nil,
            "Non-finite tracking cannot become a valid selection")
        for orientation in [CGImagePropertyOrientation.up,.down,.left,.right] {
            let upright = selected.oriented(orientation)
            let data = context.jpegRepresentation(of: upright, colorSpace: CGColorSpaceCreateDeviceRGB(), options: [:])!
            let source = CGImageSourceCreateWithData(data as CFData, nil)!
            let image = CGImageSourceCreateImageAtIndex(source, 0, nil)!
            let portrait = orientation == .left || orientation == .right
            check(image.width == (portrait ? 100 : 160) && image.height == (portrait ? 160 : 100),
                "Selection and original must share the same final orientation")
        }
        print("PASS: real Core Image selection, orientation, source preservation and invalid-mask rejection")
    }
}
