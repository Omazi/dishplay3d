import Foundation
func require(_ condition: @autoclosure () -> Bool, _ message: String) {
    guard condition() else { fatalError(message) }
}
var stationary = ScanCoverage()
for i in 0..<100 { stationary.accept(angle: 0.1, elevation: 0.4, time: Double(i)) }
require(stationary.covered == 1, "A stationary camera must never fill the orbit")
require(!stationary.complete, "Repeated frames cannot complete a scan")
require(ScanCoverage.sector(-0.01) == 17, "Negative angles must wrap to the last sector")
require(ScanCoverage.sector(2 * .pi + 0.01) == 0, "Full turns must wrap to the first sector")
var orbit = ScanCoverage()
for i in 0..<18 { orbit.accept(angle: (Double(i)+0.5)/18 * 2 * .pi, elevation: 0.4, time: Double(i)) }
require(orbit.covered == 18 && !orbit.complete, "A flat orbit needs upper views")
for i in 0..<4 { orbit.accept(angle: (Double(i)+0.5)/18 * 2 * .pi, elevation: 0.8, time: Double(i+20)) }
require(orbit.complete && orbit.progress == 1, "The orbit and upper views complete coverage")
var gap = ScanCoverage()
for i in 1..<18 { gap.accept(angle: (Double(i)+0.5)/18 * 2 * .pi, elevation: 0.8, time: Double(i)) }
require(!gap.complete && gap.missing == 0, "A missing sector must be retained as a hole")
gap.accept(angle: 0.1, elevation: 0.8, time: 30)
require(gap.complete, "Filling only the missing sector must finish the scan")
var rapid = ScanCoverage()
rapid.accept(angle: 0.1, elevation: 0.5, time: 1)
rapid.accept(angle: 0.9, elevation: 0.5, time: 1.1)
require(rapid.accepted == 1, "Too-fast frame acceptance must be rejected")
print("Scan coverage checks passed")
