import Metal
import ScanCore

/// GPU buffers for the partial surface (indexed triangles) sent by the calculator.
final class MeshRenderer {
    private let device: MTLDevice
    private let pipeline: MTLRenderPipelineState
    private var positions: MTLBuffer?
    private var colors: MTLBuffer?
    private var normals: MTLBuffer?
    private var indices: MTLBuffer?
    private(set) var indexCount = 0

    init(device: MTLDevice, library: MTLLibrary, pixelFormat: MTLPixelFormat, depthFormat: MTLPixelFormat) throws {
        self.device = device
        let d = MTLRenderPipelineDescriptor()
        d.vertexFunction = library.makeFunction(name: "meshVertex")
        d.fragmentFunction = library.makeFunction(name: "meshFragment")
        d.colorAttachments[0].pixelFormat = pixelFormat
        d.depthAttachmentPixelFormat = depthFormat
        pipeline = try device.makeRenderPipelineState(descriptor: d)
    }

    func update(_ g: PreviewGeometry) {
        indexCount = g.triangleCount * 3
        guard indexCount > 0, g.vertexCount > 0 else { indexCount = 0; return }
        func buf(_ d: Data) -> MTLBuffer? { d.withUnsafeBytes { device.makeBuffer(bytes: $0.baseAddress!, length: $0.count) } }
        positions = buf(g.vertexPositions)
        colors = buf(g.vertexColors)
        normals = buf(g.vertexNormals)
        indices = buf(g.indices)
    }

    func draw(_ enc: MTLRenderCommandEncoder, uniforms: inout PreviewUniforms) {
        guard indexCount > 0, let positions, let colors, let normals, let indices else { return }
        enc.setRenderPipelineState(pipeline)
        enc.setCullMode(.none)
        enc.setVertexBuffer(positions, offset: 0, index: 0)
        enc.setVertexBuffer(colors, offset: 0, index: 1)
        enc.setVertexBuffer(normals, offset: 0, index: 2)
        enc.setVertexBytes(&uniforms, length: MemoryLayout<PreviewUniforms>.stride, index: 3)
        enc.setFragmentBytes(&uniforms, length: MemoryLayout<PreviewUniforms>.stride, index: 0)
        enc.drawIndexedPrimitives(type: .triangle, indexCount: indexCount, indexType: .uint32, indexBuffer: indices, indexBufferOffset: 0)
    }
}
