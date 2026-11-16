import Metal
import ScanCore

/// GPU buffers for the coloured point layer (reconstructed points from the calculator, plus the
/// short-lived ARKit tracking points labelled "suivi", never accumulated).
final class PointCloudRenderer {
    private let device: MTLDevice
    private let pipeline: MTLRenderPipelineState
    private var positions: MTLBuffer?
    private var colors: MTLBuffer?
    private var count = 0
    private var trackPositions: MTLBuffer?
    private var trackColors: MTLBuffer?
    private var trackCount = 0

    init(device: MTLDevice, library: MTLLibrary, pixelFormat: MTLPixelFormat, depthFormat: MTLPixelFormat) throws {
        self.device = device
        let d = MTLRenderPipelineDescriptor()
        d.vertexFunction = library.makeFunction(name: "pointVertex")
        d.fragmentFunction = library.makeFunction(name: "pointFragment")
        d.colorAttachments[0].pixelFormat = pixelFormat
        d.colorAttachments[0].isBlendingEnabled = true
        d.colorAttachments[0].sourceRGBBlendFactor = .sourceAlpha
        d.colorAttachments[0].destinationRGBBlendFactor = .oneMinusSourceAlpha
        d.depthAttachmentPixelFormat = depthFormat
        pipeline = try device.makeRenderPipelineState(descriptor: d)
    }

    func update(_ g: PreviewGeometry) {
        count = g.pointCount
        guard count > 0 else { positions = nil; colors = nil; return }
        positions = g.pointPositions.withUnsafeBytes { device.makeBuffer(bytes: $0.baseAddress!, length: $0.count) }
        colors = g.pointColors.withUnsafeBytes { device.makeBuffer(bytes: $0.baseAddress!, length: $0.count) }
    }

    /// ARKit feature points already filtered to the box, object frame.
    func updateTracking(_ pts: [SIMD3<Float>]) {
        trackCount = pts.count
        guard trackCount > 0 else { return }
        var packed = [Float]()
        packed.reserveCapacity(pts.count * 3)
        for p in pts { packed += [p.x, p.y, p.z] }
        trackPositions = device.makeBuffer(bytes: packed, length: packed.count * 4)
        let cols = [UInt8](repeating: 0, count: pts.count * 4).enumerated().map { $0.offset % 4 == 3 ? UInt8(3) : UInt8(190) }
        trackColors = device.makeBuffer(bytes: cols, length: cols.count)
    }

    func draw(_ enc: MTLRenderCommandEncoder, uniforms: inout PreviewUniforms, showTracking: Bool) {
        enc.setRenderPipelineState(pipeline)
        if let positions, let colors, count > 0 {
            enc.setVertexBuffer(positions, offset: 0, index: 0)
            enc.setVertexBuffer(colors, offset: 0, index: 1)
            enc.setVertexBytes(&uniforms, length: MemoryLayout<PreviewUniforms>.stride, index: 2)
            enc.drawPrimitives(type: .point, vertexStart: 0, vertexCount: count)
        }
        if showTracking, let tp = trackPositions, let tc = trackColors, trackCount > 0 {
            enc.setVertexBuffer(tp, offset: 0, index: 0)
            enc.setVertexBuffer(tc, offset: 0, index: 1)
            enc.setVertexBytes(&uniforms, length: MemoryLayout<PreviewUniforms>.stride, index: 2)
            enc.drawPrimitives(type: .point, vertexStart: 0, vertexCount: trackCount)
        }
    }
}
