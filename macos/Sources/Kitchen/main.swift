import AppKit
import KitchenUI
import SwiftUI

// `Kitchen --demo [light|dark]`: a window with made-up data over a neutral backdrop, for
// screenshots (scripts/screenshots.sh). No script, keychain or network is touched.
let arguments = CommandLine.arguments
if let index = arguments.firstIndex(of: "--demo") {
    let dark = arguments.dropFirst(index + 1).first == "dark"
    MainActor.assumeIsolated { DemoWindow.run(dark: dark) }
} else {
    KitchenApp.main()
}

struct KitchenApp: App {
    @State private var model: AppModel

    init() {
        let model = AppModel()
        _model = State(initialValue: model)
        model.start()
    }

    var body: some Scene {
        MenuBarExtra {
            PanelView(model: model)
        } label: {
            MenuBarLabel(model: model)
        }
        .menuBarExtraStyle(.window)
    }
}

@MainActor
enum DemoWindow {
    private static var window: NSWindow?

    static func run(dark: Bool) {
        let app = NSApplication.shared
        app.setActivationPolicy(.regular)
        app.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
        let root = DemoBackdrop(dark: dark) { PanelView(model: DemoData.model()) }
        let host = NSHostingView(rootView: root)
        host.layoutSubtreeIfNeeded()
        let size = host.fittingSize
        let w = NSWindow(contentRect: NSRect(origin: .zero, size: size), styleMask: [.borderless],
                         backing: .buffered, defer: false)
        w.contentView = host
        w.isOpaque = true
        w.hasShadow = false
        w.center()
        w.makeKeyAndOrderFront(nil)
        window = w
        app.activate()
        print(w.windowNumber)
        fflush(stdout)
        app.run()
    }
}

/// A neutral, made-up background so the glass has something to refract and nothing real shows.
struct DemoBackdrop<Content: View>: View {
    let dark: Bool
    @ViewBuilder let content: Content

    var body: some View {
        content
            .glassEffect(.regular, in: .rect(cornerRadius: 20))
            .padding(32)
            .background {
                LinearGradient(colors: dark ? [Color(white: 0.16), Color(red: 0.12, green: 0.16, blue: 0.24)]
                                            : [Color(white: 0.93), Color(red: 0.80, green: 0.87, blue: 0.96)],
                               startPoint: .topLeading, endPoint: .bottomTrailing)
            }
    }
}
