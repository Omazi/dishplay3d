import Foundation

/// DPF1 frame envelope (iPhone -> calculator). Little-endian:
/// "DPF1" | u32 metaLen | meta JSON | u32 imageLen | JPEG | u32 depthLen | depth f32 | u32 confLen | conf u8
public enum FrameEnvelope {
    public static func encode(meta: Data, jpeg: Data, depth: Data = Data(), confidence: Data = Data()) -> Data {
        var out = Data("DPF1".utf8)
        for part in [meta, jpeg, depth, confidence] {
            var n = UInt32(part.count).littleEndian
            withUnsafeBytes(of: &n) { out.append(contentsOf: $0) }
            out.append(part)
        }
        return out
    }

    /// Split an envelope (used by tests and by the local export reader).
    public static func decode(_ d: Data) -> (meta: Data, jpeg: Data, depth: Data, confidence: Data)? {
        guard d.count >= 20, d.prefix(4) == Data("DPF1".utf8) else { return nil }
        var off = d.startIndex + 4
        var parts: [Data] = []
        for _ in 0..<4 {
            guard off + 4 <= d.endIndex else { return nil }
            let n = Int(d.readUInt32LE(at: off))
            off += 4
            guard off + n <= d.endIndex else { return nil }
            parts.append(d.subdata(in: off..<(off + n)))
            off += n
        }
        guard off == d.endIndex else { return nil }
        return (parts[0], parts[1], parts[2], parts[3])
    }
}

extension Data {
    func readUInt32LE(at i: Index) -> UInt32 {
        var v: UInt32 = 0
        for k in 0..<4 { v |= UInt32(self[i + k]) << (8 * UInt32(k)) }
        return v
    }
}

/// Header of a DPG1 geometry blob (see contracts/preview-message.schema.json#/$defs/geometry_header).
public struct GeometryHeader: Codable, Equatable, Sendable {
    public struct Surface: Codable, Equatable, Sendable {
        public var measured_m2: Double?
        public var interpolated_m2: Double?
        public var estimated_m2: Double?
    }
    /// The calculator's verdict on the scan so far: will it give a good model?
    public struct Quality: Codable, Equatable, Sendable {
        public var level: String?            // good, fair, poor, too_early
        public var score: Int?
        public var issues: [String]?         // sides_missing, holes, fragmented, uniform_or_shiny, few_views
        public var top_coverage: Double?
        public var measured_share: Double?
    }
    public struct Coverage: Codable, Equatable, Sendable {
        public var azimuth_bins: Int?
        public var views_per_bin: [[Int]]?
        public var visited_bins: Int?
        public var total_bins: Int?
    }
    public var schema: String?
    public var version: Int
    public var kind: String
    public var epoch: Int?
    public var box_revision: Int?
    public var box_size_m: [Double]?
    public var computed_at: Double?
    public var last_frame_ids: [Int]?
    public var integrated_frames: Int?
    public var received_frames: Int?
    public var measured_points: Int?
    public var confirmed_points: Int?
    public var point_count: Int?
    public var vertex_count: Int?
    public var triangle_count: Int?
    public var quality: Quality?
    public var surface: Surface?
    public var coverage: Coverage?
}

/// Decoded DPG1 geometry. Buffers are raw little-endian bytes ready for GPU upload.
public struct PreviewGeometry: Sendable {
    public var header: GeometryHeader
    public var pointCount: Int
    public var vertexCount: Int
    public var triangleCount: Int
    public var pointPositions: Data   // pointCount * 3 * Float32
    public var pointColors: Data      // pointCount * 4 * UInt8 (r, g, b, class)
    public var vertexPositions: Data  // vertexCount * 3 * Float32
    public var vertexColors: Data     // vertexCount * 4 * UInt8
    public var vertexNormals: Data    // vertexCount * 4 * Int8
    public var indices: Data          // triangleCount * 3 * UInt32

    public enum DecodeError: Error { case badMagic, truncated, badHeader, sizeMismatch }

    public static func decode(_ d: Data) throws -> PreviewGeometry {
        guard d.count >= 8, d.prefix(4) == Data("DPG1".utf8) else { throw DecodeError.badMagic }
        let base = d.startIndex
        let hl = Int(d.readUInt32LE(at: base + 4))
        guard 8 + hl <= d.count else { throw DecodeError.truncated }
        let header: GeometryHeader
        do { header = try JSONDecoder().decode(GeometryHeader.self, from: d.subdata(in: (base + 8)..<(base + 8 + hl))) } catch {
            throw DecodeError.badHeader
        }
        let n = header.point_count ?? 0, v = header.vertex_count ?? 0, t = header.triangle_count ?? 0
        var off = 8 + hl + (4 - hl % 4) % 4
        func take(_ bytes: Int) throws -> Data {
            guard off + bytes <= d.count else { throw DecodeError.truncated }
            defer { off += bytes }
            return d.subdata(in: (base + off)..<(base + off + bytes))
        }
        let g = PreviewGeometry(header: header, pointCount: n, vertexCount: v, triangleCount: t,
                                pointPositions: try take(n * 12), pointColors: try take(n * 4),
                                vertexPositions: try take(v * 12), vertexColors: try take(v * 4),
                                vertexNormals: try take(v * 4), indices: try take(t * 12))
        guard off == d.count else { throw DecodeError.sizeMismatch }
        return g
    }
}

/// Provenance classes shared with the server.
public enum Provenance: UInt8, Sendable {
    case measured = 0, interpolated = 1, estimated = 2, tracking = 3, provisional = 4
}
