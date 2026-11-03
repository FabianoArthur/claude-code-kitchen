// swift-tools-version: 6.2
// Kitchen.app — the claude-code-kitchen menu-bar app (macOS 26+, Liquid Glass).
// Build the .app with `make -C macos app`; see docs/macos-app.md.
import PackageDescription

let package = Package(
    name: "Kitchen",
    platforms: [.macOS(.v26)],
    products: [
        .executable(name: "Kitchen", targets: ["Kitchen"]),
    ],
    targets: [
        // Pure logic: decoding, state reducers, formatting, polling policy, process and HTTP plumbing.
        .target(name: "KitchenCore"),
        // SwiftUI: tokens, views, the menu-bar label, the app model.
        .target(name: "KitchenUI", dependencies: ["KitchenCore"]),
        .executableTarget(name: "Kitchen", dependencies: ["KitchenUI"]),
        .testTarget(name: "KitchenCoreTests", dependencies: ["KitchenCore"], resources: [.copy("Fixtures")]),
        .testTarget(name: "KitchenUITests", dependencies: ["KitchenUI"]),
    ]
)
