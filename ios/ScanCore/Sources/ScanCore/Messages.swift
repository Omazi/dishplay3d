import Foundation

public struct BoxSpec: Codable, Equatable, Sendable {
    public struct Size: Codable, Equatable, Sendable {
        public var width: Double, height: Double, depth: Double
        public init(width: Double, height: Double, depth: Double) { self.width = width; self.height = height; self.depth = depth }
    }
    public var T_world_from_object: [Double]
    public var size_m: Size
    public var epoch: Int
    public var revision: Int
    public var scale_confidence: String
    public var plane: String

    public init(worldFromObject: Mat4, size: Size, epoch: Int, revision: Int = 0, plane: String) {
        T_world_from_object = worldFromObject.rowMajor
        size_m = size
        self.epoch = epoch
        self.revision = revision
        scale_confidence = "tracking_only"
        self.plane = plane
    }
}

public struct DeviceInfo: Codable, Equatable, Sendable {
    public var platform = "ios"
    public var model: String
    public var os: String
    public var app_version: String
    public var lidar_available: Bool
    public var lidar_enabled: Bool
    public init(model: String, os: String, appVersion: String, lidarAvailable: Bool, lidarEnabled: Bool) {
        self.model = model; self.os = os; app_version = appVersion; lidar_available = lidarAvailable; lidar_enabled = lidarEnabled
    }
}

public struct SessionCreate: Codable, Sendable {
    public var schema = "dishplay.session/1"
    public var client_session_id: String
    public var box: BoxSpec
    public var device: DeviceInfo
    public var reference_width_m: Double?
    public init(clientSessionID: String, box: BoxSpec, device: DeviceInfo, referenceWidth: Double?) {
        client_session_id = clientSessionID; self.box = box; self.device = device; reference_width_m = referenceWidth
    }
}

/// Frame metadata (contracts/capture-session.schema.json#/$defs/frame).
public struct FrameMeta: Codable, Sendable {
    public struct Image: Codable, Sendable {
        public var width: Int, height: Int
        public var encoding = "jpeg"
        public var sha256: String
        public var orientation = "sensor_native"
        public var transforms: [String] = []
        public init(width: Int, height: Int, sha256: String, transforms: [String] = []) {
            self.width = width; self.height = height; self.sha256 = sha256; self.transforms = transforms
        }
    }
    public struct Distortion: Codable, Sendable {
        public var status = "arkit_not_provided_assumed_negligible"
        public init() {}
    }
    public struct Tracking: Codable, Sendable {
        public var state: String
        public var reason: String?
        public init(state: String, reason: String?) { self.state = state; self.reason = reason }
    }
    public struct CameraFormat: Codable, Sendable {
        public var width: Int, height: Int, fps: Double
        public var device: String
        public var exposure_s: Double?
        public var iso: Double?
        public init(width: Int, height: Int, fps: Double, device: String, exposure_s: Double? = nil, iso: Double? = nil) {
            self.width = width; self.height = height; self.fps = fps; self.device = device; self.exposure_s = exposure_s; self.iso = iso
        }
    }
    public struct Quality: Codable, Sendable {
        public var sharpness: Double
        public var mean_luma: Double
        public var box_in_view: Double
        public var translation_since_last_m: Double
        public var angular_speed_dps: Double
        public init(sharpness: Double, mean_luma: Double, box_in_view: Double, translation_since_last_m: Double, angular_speed_dps: Double) {
            self.sharpness = sharpness; self.mean_luma = mean_luma; self.box_in_view = box_in_view
            self.translation_since_last_m = translation_since_last_m; self.angular_speed_dps = angular_speed_dps
        }
    }
    public struct Depth: Codable, Sendable {
        public var width: Int, height: Int
        public var encoding = "float32_le_m"
        public var confidence_encoding = "uint8_arkit"
        public var intrinsics: Intrinsics
        public var source = "lidar_scene_depth"
        public var timestamp_s: Double
        public init(width: Int, height: Int, intrinsics: Intrinsics, timestamp_s: Double) {
            self.width = width; self.height = height; self.intrinsics = intrinsics; self.timestamp_s = timestamp_s
        }
    }
    public var schema = "dishplay.frame/1"
    public var session_id: String
    public var frame_id: Int
    public var epoch: Int
    public var timestamp_s: Double
    public var image: Image
    public var intrinsics: Intrinsics
    public var distortion = Distortion()
    public var T_world_from_cameraAR: [Double]
    public var tracking: Tracking
    public var camera_format: CameraFormat
    public var quality: Quality
    public var depth: Depth?

    public init(sessionID: String, frameID: Int, epoch: Int, timestamp: Double, image: Image, intrinsics: Intrinsics,
                worldFromCameraAR: Mat4, tracking: Tracking, cameraFormat: CameraFormat, quality: Quality, depth: Depth?) {
        session_id = sessionID; frame_id = frameID; self.epoch = epoch; timestamp_s = timestamp; self.image = image
        self.intrinsics = intrinsics; T_world_from_cameraAR = worldFromCameraAR.rowMajor; self.tracking = tracking
        camera_format = cameraFormat; self.quality = quality; self.depth = depth
    }

    public func jsonData() throws -> Data {
        let e = JSONEncoder()
        e.outputFormatting = [.sortedKeys]
        return try e.encode(self)
    }
}

/// Event received on WS /sessions/{id}/events. Unknown fields are ignored, and a known field that is not of
/// the expected kind is read as absent: one odd value must not make the app miss an event (the end of a
/// calculation, for example). Only `type` is required.
public struct ServerEvent: Codable, Sendable {
    public var type: String
    public var session_id: String?
    public var state: String?
    public var queue: Int?
    public var frame_id: Int?
    public var status: String?
    public var reason: String?
    public var points: Int?
    public var url: String?
    public var header: GeometryHeader?
    public var step: String?
    public var done: Int?
    public var total: Int?
    public var files: [String]?
    public var code: String?
    public var message: String?
    /// With a status "failed": one short French sentence from the calculator.
    public var error: String?
    /// With "artifacts": the calculator's verdict on the final model and what the calculation gave up.
    public var report: FinalOutcome?
    public var server_time: Double?

    private enum CodingKeys: String, CodingKey {
        case type, session_id, state, queue, frame_id, status, reason, points, url, header, step, done, total
        case files, code, message, error, report, server_time
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        type = try c.decode(String.self, forKey: .type)
        session_id = c.lenient(String.self, .session_id)
        state = c.lenient(String.self, .state)
        queue = c.lenientInt(.queue)
        frame_id = c.lenientInt(.frame_id)
        status = c.lenient(String.self, .status)
        reason = c.lenient(String.self, .reason)
        points = c.lenientInt(.points)
        url = c.lenient(String.self, .url)
        header = c.lenient(GeometryHeader.self, .header)
        step = c.lenient(String.self, .step)
        done = c.lenientInt(.done)
        total = c.lenientInt(.total)
        files = c.lenient([String].self, .files)
        code = c.lenient(String.self, .code)
        message = c.lenient(String.self, .message)
        error = c.lenient(String.self, .error)
        let outcome = c.lenient(FinalOutcome.self, .report)
        report = (outcome?.isEmpty == false) ? outcome : nil
        server_time = c.lenient(Double.self, .server_time)
    }

    public static func decode(_ text: String) -> ServerEvent? {
        try? JSONDecoder().decode(ServerEvent.self, from: Data(text.utf8))
    }

    /// Whether this event is about the scan `sessionID`. The app keeps one connection for events and scans
    /// several dishes one after another: an event of the previous dish must never be taken for the current one.
    /// Before a scan exists on the calculator (`sessionID` nil) no event can be about it. An event that names
    /// no scan is accepted: the connection it came through is opened for one scan only.
    public func isAbout(_ sessionID: String?) -> Bool {
        guard let sessionID, !sessionID.isEmpty else { return false }
        guard let named = session_id, !named.isEmpty else { return true }
        return named == sessionID
    }
}

/// dishplayscan://pair?u=<https url>&c=<code>&fp=<sha256 hex>
public struct PairingLink: Equatable, Sendable {
    public var baseURL: URL
    public var code: String
    public var fingerprint: String

    public init?(url: URL) {
        guard url.scheme == "dishplayscan", url.host == "pair",
              let comps = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return nil }
        // Not `Dictionary(uniqueKeysWithValues:)`: it stops the program on a repeated name. A link that says the
        // same thing twice is damaged or forged, and is refused like any other bad link.
        var q: [String: String] = [:]
        for item in comps.queryItems ?? [] {
            guard q[item.name] == nil else { return nil }
            q[item.name] = item.value ?? ""
        }
        guard let u = q["u"], let base = URL(string: u), base.scheme == "https",
              let c = q["c"], c.count == 6, c.allSatisfy(\.isNumber),
              let fp = q["fp"]?.lowercased(), fp.count == 64, fp.allSatisfy(\.isHexDigit) else { return nil }
        baseURL = base; code = c; fingerprint = fp
    }

    public init(baseURL: URL, code: String, fingerprint: String) {
        self.baseURL = baseURL; self.code = code; self.fingerprint = fingerprint.lowercased()
    }
}
