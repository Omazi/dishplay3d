import Foundation

/// Guidance shown to the user while scanning (French UI strings live in the app).
public enum Guidance: String, Sendable, CaseIterable {
    case placeBox, trackingLost, trackingLimited, frameTheDish, slowDown, tooDark, moveAround, dontRotateInPlace
    case goHigher, completeSide, keepGoing, calculatorDisconnected, paused
}

public struct FrameObservation: Sendable {
    public var timestamp: Double
    public var worldFromCameraAR: Mat4
    public var trackingNormal: Bool
    public var trackingLimitedReason: String?
    public var boxVisibility: Double   // fraction of box samples inside the image
    public var sharpness: Double       // Laplacian variance of a luma patch
    public var meanLuma: Double        // 0...255
    public init(timestamp: Double, worldFromCameraAR: Mat4, trackingNormal: Bool, trackingLimitedReason: String? = nil,
                boxVisibility: Double, sharpness: Double, meanLuma: Double) {
        self.timestamp = timestamp; self.worldFromCameraAR = worldFromCameraAR; self.trackingNormal = trackingNormal
        self.trackingLimitedReason = trackingLimitedReason; self.boxVisibility = boxVisibility; self.sharpness = sharpness
        self.meanLuma = meanLuma
    }
}

public struct KeyframeDecision: Sendable {
    public var accept: Bool
    public var reason: String
    public var guidance: Guidance?
    public var translationSinceLast: Double
    public var angularSpeedDps: Double
    public var linearSpeed: Double
}

/// Chooses keyframes automatically: the user never triggers a picture.
/// Keeps a dense sequence (small baselines, good for temporal stereo) while
/// rejecting blur, lost tracking, framing errors and pure rotation on the spot.
public struct KeyframeSelector: Sendable {
    public var minTranslation = 0.012     // m between keyframes (stereo baselines of 1-10 cm come from neighbours)
    public var minInterval = 0.25         // s  -> at most 4 keyframes/s
    public var maxAngularSpeed = 70.0     // deg/s
    public var maxLinearSpeed = 0.35      // m/s
    public var minBoxVisibility = 0.55
    public var minLuma = 35.0
    public var blurRatio = 0.45

    private var lastKey: (t: Double, pose: Mat4)?
    private var prev: (t: Double, pose: Mat4)?
    private var sharpHistory: [Double] = []
    public private(set) var accepted = 0

    public init() {}

    public mutating func reset() { lastKey = nil; prev = nil; sharpHistory = []; accepted = 0 }

    public mutating func evaluate(_ o: FrameObservation) -> KeyframeDecision {
        var ang = 0.0, lin = 0.0
        if let p = prev, o.timestamp > p.t {
            let dt = o.timestamp - p.t
            ang = rotationAngleDeg(p.pose, o.worldFromCameraAR) / dt
            lin = distance(p.pose.translation, o.worldFromCameraAR.translation) / dt
        }
        prev = (o.timestamp, o.worldFromCameraAR)
        let trans = lastKey.map { distance($0.pose.translation, o.worldFromCameraAR.translation) } ?? .infinity
        func no(_ r: String, _ g: Guidance?) -> KeyframeDecision {
            KeyframeDecision(accept: false, reason: r, guidance: g, translationSinceLast: trans, angularSpeedDps: ang, linearSpeed: lin)
        }
        if !o.trackingNormal { return no("tracking", o.trackingLimitedReason == nil ? .trackingLost : .trackingLimited) }
        if o.boxVisibility < minBoxVisibility { return no("box_not_in_view", .frameTheDish) }
        if ang > maxAngularSpeed || lin > maxLinearSpeed { return no("too_fast", .slowDown) }
        if o.meanLuma < minLuma { return no("too_dark", .tooDark) }
        if sharpHistory.count >= 8 {
            let med = sharpHistory.sorted()[sharpHistory.count / 2]
            if o.sharpness < blurRatio * med { return no("blurred", .slowDown) }
        }
        sharpHistory.append(o.sharpness)
        if sharpHistory.count > 60 { sharpHistory.removeFirst() }
        if let k = lastKey {
            if o.timestamp - k.t < minInterval { return no("rate_limit", nil) }
            if trans < minTranslation {
                let rot = rotationAngleDeg(k.pose, o.worldFromCameraAR)
                return no("not_enough_motion", rot > 8 ? .dontRotateInPlace : .moveAround)
            }
        }
        lastKey = (o.timestamp, o.worldFromCameraAR)
        accepted += 1
        return KeyframeDecision(accept: true, reason: "ok", guidance: nil, translationSinceLast: trans.isFinite ? trans : 0,
                                angularSpeedDps: ang, linearSpeed: lin)
    }
}

/// Angles visited around the box (client-side, from accepted keyframes). Distinct from the
/// server's validated surface: visiting an angle does not prove the surface was reconstructed.
public struct CoverageRing: Sendable, Equatable {
    public static let azimuthBins = 12
    public static let elevationEdges = [30.0, 55.0]
    public private(set) var counts = Array(repeating: Array(repeating: 0, count: 12), count: 3)

    public init() {}

    public static func bin(cameraInObject p: [Double], boxHeight: Double) -> (row: Int, col: Int) {
        let d = [p[0], p[1] - boxHeight / 2, p[2]]
        var az = atan2(d[2], d[0]) * 180 / .pi
        if az < 0 { az += 360 }
        let el = atan2(d[1], (d[0] * d[0] + d[2] * d[2]).squareRoot()) * 180 / .pi
        let row = el < elevationEdges[0] ? 0 : (el < elevationEdges[1] ? 1 : 2)
        return (row, min(azimuthBins - 1, Int(az / (360.0 / Double(azimuthBins)))))
    }

    public mutating func add(cameraInObject p: [Double], boxHeight: Double) {
        let b = CoverageRing.bin(cameraInObject: p, boxHeight: boxHeight)
        counts[b.row][b.col] += 1
    }

    public var visitedAzimuths: Int { (0..<12).filter { c in counts.contains { $0[c] > 0 } }.count }
    public var visitedBins: Int { counts.flatMap { $0 }.filter { $0 > 0 }.count }
    public var highViews: Int { counts[2].reduce(0, +) }

    /// Next instruction: complete the azimuth ring first, then ask for higher views.
    public func suggestion(currentCameraInObject p: [Double], boxHeight: Double) -> (Guidance, direction: Int)? {
        let cur = CoverageRing.bin(cameraInObject: p, boxHeight: boxHeight)
        let missing = (0..<12).filter { c in !counts.contains { $0[c] > 0 } }
        if !missing.isEmpty {
            // nearest missing sector, signed direction (+1 counter-clockwise seen from above)
            let best = missing.min { a, b in circDist(a, cur.col) < circDist(b, cur.col) }!
            let delta = ((best - cur.col) + 18) % 12 - 6
            return (visitedAzimuths >= 3 ? .completeSide : .moveAround, delta >= 0 ? 1 : -1)
        }
        if highViews < 6 { return (.goHigher, 0) }
        return nil
    }

    private func circDist(_ a: Int, _ b: Int) -> Int { let d = abs(a - b) % 12; return min(d, 12 - d) }
}

func distance(_ a: [Double], _ b: [Double]) -> Double {
    ((a[0] - b[0]) * (a[0] - b[0]) + (a[1] - b[1]) * (a[1] - b[1]) + (a[2] - b[2]) * (a[2] - b[2])).squareRoot()
}

/// Angle (degrees) of the relative rotation between two poses.
public func rotationAngleDeg(_ a: Mat4, _ b: Mat4) -> Double {
    var tr = 0.0
    for i in 0..<3 { for k in 0..<3 { tr += a[k, i] * b[k, i] } }  // trace(Ra^T Rb)
    return acos(max(-1, min(1, (tr - 1) / 2))) * 180 / .pi
}
