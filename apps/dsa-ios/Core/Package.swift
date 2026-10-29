// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "DSACore",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [.library(name: "DSACore", targets: ["DSACore"])],
    targets: [
        .target(name: "DSACore"),
        .testTarget(name: "DSACoreTests", dependencies: ["DSACore"])
    ],
    swiftLanguageVersions: [.v5]
)
