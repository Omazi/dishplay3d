// swift-tools-version:5.9
// Platform-independent core of DishPlay Scan: coordinates, wire formats, capture heuristics.
// No ARKit/RealityKit/Metal here, so it is unit-tested with `swift test` on the macOS CI runner.
import PackageDescription

let package = Package(
    name: "ScanCore",
    platforms: [.iOS(.v17), .macOS(.v13)],
    products: [.library(name: "ScanCore", targets: ["ScanCore"])],
    targets: [
        .target(name: "ScanCore"),
        .testTarget(name: "ScanCoreTests", dependencies: ["ScanCore"], resources: [.copy("Vectors")]),
    ]
)
