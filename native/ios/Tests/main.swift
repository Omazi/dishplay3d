import Foundation
func require(_ condition: @autoclosure () -> Bool, _ message: String) {
    guard condition() else { fatalError(message) }
}
var stationary = ScanCoverage()
for i in 0..<100 { stationary.accept(angle: 0.1, elevation: 0.4, time: Double(i)) }
require(stationary.covered == 1, "A stationary camera must never fill the orbit")
require(!stationary.complete, "Repeated frames cannot complete a scan")
require(ScanCoverage.sector(-0.01) == ScanCoverage.sectors - 1, "Negative angles must wrap to the last sector")
require(ScanCoverage.sector(2 * .pi + 0.01) == 0, "Full turns must wrap to the first sector")
var orbit = ScanCoverage()
for i in 0..<ScanCoverage.sectors { orbit.accept(angle: (Double(i)+0.5)/Double(ScanCoverage.sectors) * 2 * .pi, elevation: 0.4, time: Double(i)) }
require(orbit.covered == ScanCoverage.sectors && !orbit.complete, "A flat orbit needs upper views")
for i in 0..<4 { orbit.accept(angle: (Double(i)+0.5)/Double(ScanCoverage.sectors) * 2 * .pi, elevation: 0.8, time: Double(i+20)) }
require(orbit.complete && orbit.progress == 1, "The orbit and upper views complete coverage")
var gap = ScanCoverage()
for i in 1..<ScanCoverage.sectors { gap.accept(angle: (Double(i)+0.5)/Double(ScanCoverage.sectors) * 2 * .pi, elevation: 0.8, time: Double(i)) }
require(!gap.complete && gap.missing == 0, "A missing sector must be retained as a hole")
gap.accept(angle: 0.1, elevation: 0.8, time: 30)
require(gap.complete, "Filling only the missing sector must finish the scan")
var rapid = ScanCoverage()
rapid.accept(angle: 0.1, elevation: 0.5, time: 1)
rapid.accept(angle: 0.9, elevation: 0.5, time: 1.1)
require(rapid.accepted == 1, "Too-fast frame acceptance must be rejected")

require(gap.nextNeeded(from: 1) == nil, "A complete orbit must not request extra sectors")
var directed = ScanCoverage()
directed.accept(angle: 0.1, elevation: 0.8, time: 1)
require(directed.nextNeeded(from: 0.1, direction: 1) == 1, "Forward guidance must point to the next missing sector")
require(directed.nextNeeded(from: 0.1, direction: -1) == ScanCoverage.sectors - 1, "Reverse guidance must follow the actual orbit direction")
print("Scan coverage checks passed")
