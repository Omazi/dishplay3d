import Foundation

// Coverage describes accepted camera observations, never reconstructed surface quality.
struct ScanCoverage {
    static let sectors = 18
    private(set) var elevations = [Double?](repeating: nil, count: sectors)
    private(set) var accepted = 0
    private(set) var lastAngle: Double?
    private(set) var lastTime = -Double.infinity

    static func sector(_ angle: Double) -> Int {
        let turn = 2 * Double.pi
        let normalized = (angle.truncatingRemainder(dividingBy: turn) + turn).truncatingRemainder(dividingBy: turn)
        return min(sectors - 1, Int(normalized / turn * Double(sectors)))
    }
    var covered: Int { elevations.compactMap { $0 }.count }
    var upperViews: Int { elevations.compactMap { $0 }.filter { $0 >= 0.65 }.count }
    var complete: Bool { covered == Self.sectors && upperViews >= 4 && accepted >= 12 }
    var progress: Double { min(1, 0.85 * Double(covered) / Double(Self.sectors) + 0.15 * Double(min(upperViews, 4)) / 4) }
    var missing: Int? { elevations.firstIndex(where: { $0 == nil }) }

    func needs(angle: Double, elevation: Double, time: Double) -> Bool {
        guard accepted < 24, time - lastTime >= 0.45 else { return false }
        let old = elevations[Self.sector(angle)]
        return old == nil || (upperViews < 4 && old! < 0.65 && elevation >= 0.65)
    }
    mutating func accept(angle: Double, elevation: Double, time: Double) {
        guard needs(angle: angle, elevation: elevation, time: time) else { return }
        let slot = Self.sector(angle)
        elevations[slot] = max(elevations[slot] ?? -.infinity, elevation)
        accepted += 1
        lastAngle = angle
        lastTime = time
    }
}
