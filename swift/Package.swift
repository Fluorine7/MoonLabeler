// swift-tools-version: 5.9
import PackageDescription
import Foundation

let nativeLibrary = URL(fileURLWithPath: #filePath).deletingLastPathComponent().appendingPathComponent(".build/native/lib").path

let package = Package(
    name: "MoonLabelerSwift",
    platforms: [.macOS(.v14)],
    products: [.executable(name: "MoonLabelerSwift", targets: ["MoonLabelerSwift"])],
    targets: [
        .systemLibrary(name: "CMoonNative", path: "Native/Swift"),
        .target(name: "MoonCore", dependencies: ["CMoonNative"], resources: [.process("Resources")],
                linkerSettings: [.unsafeFlags(["-L" + nativeLibrary, "-Xlinker", "-rpath", "-Xlinker", "@executable_path/../Frameworks",
                                               "-Xlinker", "-rpath", "-Xlinker", nativeLibrary])]),
        .target(name: "MoonEditor", dependencies: ["MoonCore"]),
        .executableTarget(name: "MoonLabelerSwift", dependencies: ["MoonEditor"]),
        .executableTarget(name: "MoonNativeCheck", dependencies: ["MoonCore", "MoonEditor"]),
        .testTarget(name: "MoonCoreTests", dependencies: ["MoonCore"], resources: [.process("Fixtures")]),
        .testTarget(name: "MoonEditorTests", dependencies: ["MoonEditor"], resources: [.process("Fixtures")]),
    ]
)
