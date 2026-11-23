import XCTest
@testable import ScanCore

final class CoordinateTests: XCTestCase {
    struct Vectors: Decodable {
        struct K: Decodable { var fx, fy, cx, cy: Double; var width, height: Int }
        struct Case: Decodable {
            var T_world_from_object: [Double]
            var T_world_from_cameraAR: [Double]
            var K: K
            var points_object: [[Double]]
            var T_object_from_cameraCV: [Double]
            var uv: [[Double]]
            var depth: [Double]
        }
        struct SK: Decodable { var fx, fy, cx, cy: Double }
        var cases: [Case]
        var scaled_K_640x480: SK
    }

    func vector(_ name: String) throws -> Data {
        let url = try XCTUnwrap(Bundle.module.url(forResource: name, withExtension: nil, subdirectory: "Vectors"))
        return try Data(contentsOf: url)
    }

    /// Same inputs as the Python reference (tools/make_test_vectors.py) must give the same outputs.
    func testMatchesPythonReference() throws {
        let v = try JSONDecoder().decode(Vectors.self, from: vector("coordinates.json"))
        XCTAssertEqual(v.cases.count, 6)
        for c in v.cases {
            let T = Coordinates.objectFromCameraCV(worldFromObject: Mat4(rowMajor: c.T_world_from_object),
                                                   worldFromCameraAR: Mat4(rowMajor: c.T_world_from_cameraAR))
            for (a, b) in zip(T.rowMajor, c.T_object_from_cameraCV) { XCTAssertEqual(a, b, accuracy: 1e-9) }
            let K = Intrinsics(fx: c.K.fx, fy: c.K.fy, cx: c.K.cx, cy: c.K.cy, width: c.K.width, height: c.K.height)
            let pr = Coordinates.project(K, cameraCVFromObject: T.rigidInverse, points: c.points_object)
            for (i, p) in pr.enumerated() {
                XCTAssertGreaterThan(p.z, 0)
                XCTAssertEqual(p.u, c.uv[i][0], accuracy: 1e-6)
                XCTAssertEqual(p.v, c.uv[i][1], accuracy: 1e-6)
                XCTAssertEqual(p.z, c.depth[i], accuracy: 1e-9)
            }
        }
        let s = Intrinsics(fx: 1440, fy: 1440, cx: 959.5, cy: 719.5, width: 1920, height: 1440).scaled(toWidth: 640, height: 480)
        XCTAssertEqual(s.fx, v.scaled_K_640x480.fx, accuracy: 1e-9)
        XCTAssertEqual(s.cx, v.scaled_K_640x480.cx, accuracy: 1e-9)
        XCTAssertEqual(s.cy, v.scaled_K_640x480.cy, accuracy: 1e-9)
    }

    /// simd_float4x4 is column-major: building from columns must give the row-major wire order.
    func testColumnsToRowMajor() {
        let m = Mat4(columns: [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0.1, 0.2, 0.3, 1])
        XCTAssertEqual(m.rowMajor[3], 0.1)
        XCTAssertEqual(m.rowMajor[7], 0.2)
        XCTAssertEqual(m.rowMajor[11], 0.3)
        XCTAssertEqual(m.rowMajor[12], 0)
    }

    func testRigidInverseAndYaw() {
        let T = Mat4.yawTranslation(yaw: 0.7, x: 0.2, y: -0.8, z: 1.1)
        XCTAssertTrue(T.isRigid())
        let I = T * T.rigidInverse
        for (a, b) in zip(I.rowMajor, Mat4.identity.rowMajor) { XCTAssertEqual(a, b, accuracy: 1e-12) }
        XCTAssertFalse(Mat4(rowMajor: [Double](repeating: 1, count: 16)).isRigid())
    }
}

final class WireFormatTests: XCTestCase {
    func data(_ n: String) throws -> Data {
        try Data(contentsOf: XCTUnwrap(Bundle.module.url(forResource: n, withExtension: nil, subdirectory: "Vectors")))
    }

    func testDecodesPythonGeometry() throws {
        let g = try PreviewGeometry.decode(data("geometry.dpg"))
        XCTAssertEqual(g.header.version, 7)
        XCTAssertEqual(g.header.kind, "points+mesh")
        XCTAssertEqual(g.pointCount, 2)
        XCTAssertEqual(g.triangleCount, 1)
        let p: [Float] = g.pointPositions.withUnsafeBytes { Array($0.bindMemory(to: Float.self)) }
        XCTAssertEqual(p, [0, 0, 0, 0.1, 0.2, 0.3])
        XCTAssertEqual(Array(g.pointColors), [255, 0, 0, 0, 0, 255, 0, 4])
        let idx: [UInt32] = g.indices.withUnsafeBytes { Array($0.bindMemory(to: UInt32.self)) }
        XCTAssertEqual(idx, [0, 1, 2])
        XCTAssertThrowsError(try PreviewGeometry.decode(data("geometry.dpg") + Data([0])))
        XCTAssertThrowsError(try PreviewGeometry.decode(Data("XXXX".utf8)))
    }

    func testEnvelopeMatchesPythonLayout() throws {
        let py = try data("frame.dpf")
        let parts = try XCTUnwrap(FrameEnvelope.decode(py))
        XCTAssertEqual(String(data: parts.meta, encoding: .utf8), "{\"frame_id\":3}")
        let swift = FrameEnvelope.encode(meta: parts.meta, jpeg: parts.jpeg, depth: parts.depth, confidence: parts.confidence)
        XCTAssertEqual(swift, py, "Swift and Python must produce byte-identical envelopes")
        XCTAssertNil(FrameEnvelope.decode(py.dropLast()))
    }

    func testFrameMetaHasContractKeys() throws {
        let meta = FrameMeta(sessionID: "abc123", frameID: 1, epoch: 0, timestamp: 12.5,
                             image: .init(width: 1920, height: 1440, sha256: String(repeating: "a", count: 64)),
                             intrinsics: Intrinsics(fx: 1400, fy: 1400, cx: 959.5, cy: 719.5, width: 1920, height: 1440),
                             worldFromCameraAR: .identity, tracking: .init(state: "normal", reason: nil),
                             cameraFormat: .init(width: 1920, height: 1440, fps: 30, device: "wide"),
                             quality: .init(sharpness: 1, mean_luma: 120, box_in_view: 0.9, translation_since_last_m: 0.02, angular_speed_dps: 5),
                             depth: nil)
        let obj = try XCTUnwrap(JSONSerialization.jsonObject(with: meta.jsonData()) as? [String: Any])
        for k in ["schema", "session_id", "frame_id", "epoch", "timestamp_s", "image", "intrinsics", "distortion", "T_world_from_cameraAR", "tracking"] {
            XCTAssertNotNil(obj[k], k)
        }
        XCTAssertNil(obj["depth"])
        XCTAssertEqual((obj["T_world_from_cameraAR"] as? [Double])?.count, 16)
    }

    func testPairingLink() throws {
        let fp = String(repeating: "ab", count: 32)
        let ok = try XCTUnwrap(URL(string: "dishplayscan://pair?u=https%3A%2F%2F192.168.1.20%3A8765&c=123456&fp=\(fp)"))
        let link = try XCTUnwrap(PairingLink(url: ok))
        XCTAssertEqual(link.baseURL.absoluteString, "https://192.168.1.20:8765")
        XCTAssertEqual(link.code, "123456")
        XCTAssertNil(PairingLink(url: URL(string: "dishplayscan://pair?u=http%3A%2F%2F1.2.3.4%3A1&c=123456&fp=\(fp)")!), "plain HTTP refused")
        XCTAssertNil(PairingLink(url: URL(string: "dishplayscan://pair?u=https%3A%2F%2F1.2.3.4%3A1&c=12&fp=\(fp)")!))
    }

    /// A link that repeats a parameter used to stop the app (a dictionary built from unique keys). It is refused.
    func testPairingLinkWithARepeatedParameterIsRefused() throws {
        let fp = String(repeating: "ab", count: 32)
        let twice = try XCTUnwrap(URL(string: "dishplayscan://pair?u=https%3A%2F%2F192.168.1.20%3A8765&c=123456&c=654321&fp=\(fp)"))
        XCTAssertNil(PairingLink(url: twice))
        XCTAssertNil(PairingLink(url: try XCTUnwrap(URL(string: "dishplayscan://pair?c=1&c=2"))))
        // Doubled "&": whether the system reads empty names there or drops them, the app must not stop.
        _ = PairingLink(url: try XCTUnwrap(URL(string: "dishplayscan://pair?u=https%3A%2F%2F1.2.3.4%3A1&&c=123456&&fp=\(fp)&&")))
        // The same link written once is still accepted.
        XCTAssertNotNil(PairingLink(url: try XCTUnwrap(URL(string: "dishplayscan://pair?u=https%3A%2F%2F192.168.1.20%3A8765&c=123456&fp=\(fp)"))))
    }

    func testServerEventDecodingIgnoresUnknownFields() {
        let e = ServerEvent.decode(#"{"type":"geometry","url":"/sessions/x/preview/3","header":{"version":3,"kind":"points","extra":1},"metrics":{"a":1}}"#)
        XCTAssertEqual(e?.header?.version, 3)
        XCTAssertEqual(e?.url, "/sessions/x/preview/3")
    }
}

final class HeuristicTests: XCTestCase {
    func obs(_ t: Double, x: Double, yaw: Double = 0, sharp: Double = 100, vis: Double = 1, normal: Bool = true) -> FrameObservation {
        FrameObservation(timestamp: t, worldFromCameraAR: Mat4.yawTranslation(yaw: yaw, x: x, y: 0.3, z: 0.4), trackingNormal: normal,
                         boxVisibility: vis, sharpness: sharp, meanLuma: 120)
    }

    func testAcceptsMotionRejectsRotationInPlace() {
        var s = KeyframeSelector()
        XCTAssertTrue(s.evaluate(obs(0, x: 0)).accept)
        XCTAssertFalse(s.evaluate(obs(0.5, x: 0.005)).accept)  // not enough translation
        let rot = s.evaluate(obs(1.0, x: 0.005, yaw: 0.3))
        XCTAssertFalse(rot.accept)
        XCTAssertEqual(rot.guidance, .dontRotateInPlace)
        XCTAssertTrue(s.evaluate(obs(1.5, x: 0.03, yaw: 0.3)).accept)
    }

    func testRejectsFastBlurredLostAndOutOfFrame() {
        var s = KeyframeSelector()
        XCTAssertTrue(s.evaluate(obs(0, x: 0)).accept)
        XCTAssertEqual(s.evaluate(obs(0.1, x: 0.2)).guidance, .slowDown)      // 2 m/s
        XCTAssertEqual(s.evaluate(obs(1.0, x: 0.25, normal: false)).guidance, .trackingLost)
        XCTAssertEqual(s.evaluate(obs(2.0, x: 0.30, vis: 0.2)).guidance, .frameTheDish)
        var t = 3.0, x = 0.3
        for _ in 0..<10 { t += 0.5; x += 0.02; _ = s.evaluate(obs(t, x: x)) }
        XCTAssertEqual(s.evaluate(obs(t + 0.5, x: x + 0.02, sharp: 10)).reason, "blurred")
    }

    func testCoverageRingDuplicatesDoNotComplete() {
        var ring = CoverageRing()
        for _ in 0..<50 { ring.add(cameraInObject: [0.3, 0.2, 0.0], boxHeight: 0.08) }
        XCTAssertEqual(ring.visitedBins, 1)
        XCTAssertEqual(ring.suggestion(currentCameraInObject: [0.3, 0.2, 0], boxHeight: 0.08)?.0, .moveAround)
        for k in 0..<12 {
            let a = (Double(k) + 0.5) * Double.pi / 6
            ring.add(cameraInObject: [0.3 * cos(a), 0.2, 0.3 * sin(a)], boxHeight: 0.08)
        }
        XCTAssertEqual(ring.visitedAzimuths, 12)
        XCTAssertEqual(ring.suggestion(currentCameraInObject: [0.3, 0.2, 0], boxHeight: 0.08)?.0, .goHigher)
    }
}
