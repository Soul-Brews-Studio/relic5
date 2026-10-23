// swift-tools-version:5.10
// RelicFeeder: the menu-bar feeder for relic5 (docs/RELICFEEDER.md). FeederCore holds everything testable; the app
// target is only the panel.
import PackageDescription

let package = Package(
    name: "RelicFeeder",
    platforms: [.macOS(.v14)],
    products: [.executable(name: "RelicFeeder", targets: ["RelicFeeder"])],
    targets: [
        .target(name: "FeederCore", linkerSettings: [.linkedFramework("IOKit")]),
        .executableTarget(name: "RelicFeeder", dependencies: ["FeederCore"]),
        .testTarget(name: "FeederCoreTests", dependencies: ["FeederCore"]),
    ]
)
