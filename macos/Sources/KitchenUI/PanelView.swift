import KitchenCore
import SwiftUI

/// The menu-bar panel: header, banners, usage, attention, unit sections, footer.
public struct PanelView: View {
    @Bindable var model: AppModel
    @State private var listHeight: CGFloat = 0
    @State private var earlierOpen = false
    @Namespace private var glass

    public init(model: AppModel) { self.model = model }

    static let docsURL = URL(string: "https://github.com/FabianoArthur/claude-code-kitchen/blob/main/docs/menubar.md#configuration")!

    public var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
                .padding(.horizontal, Theme.margin)
                .padding(.top, Theme.card)
                .padding(.bottom, Theme.row)
            ScrollView {
                GlassEffectContainer(spacing: Theme.row) {
                    content
                        .padding(.horizontal, Theme.margin)
                        .padding(.bottom, Theme.row)
                }
                .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { listHeight = $0 }
            }
            .scrollBounceBehavior(.basedOnSize)
            .frame(height: min(max(listHeight, 1), Theme.maxListHeight))
            Divider()
            footer
                .padding(.horizontal, Theme.margin)
                .padding(.vertical, Theme.row)
        }
        .frame(width: Theme.panelWidth)
        .onReceive(NotificationCenter.default.publisher(for: NSWindow.didBecomeKeyNotification)) { _ in
            model.panelOpened()
        }
    }

    // MARK: header

    private var header: some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Kitchen").font(.headline)
                Text(model.panel.summary).font(.caption).metadataStyle()
            }
            Spacer()
            if model.refreshing {
                ProgressView().controlSize(.small)
            } else if let updated = model.panel.updated {
                Text(updated).font(.caption).metadataStyle().monospacedDigit()
                    .accessibilityLabel("updated at \(updated)")
            }
            Button {
                model.refresh()
            } label: {
                Image(systemName: "arrow.clockwise")
            }
            .buttonStyle(.glass)
            .controlSize(.small)
            .help("Refresh")
            .accessibilityLabel("Refresh")
        }
    }

    // MARK: content

    @ViewBuilder private var content: some View {
        VStack(alignment: .leading, spacing: Theme.row) {
            ForEach(model.panel.banners) { banner($0) }
            if model.showUsage {
                UsageCard(state: model.usage, now: model.now, retry: model.retryUsage)
            }
            if !model.panel.attention.isEmpty { attention }
            switch model.panel.body {
            case .loading:
                ForEach(0..<2, id: \.self) { _ in placeholderRow }
            case .noGlobs:
                empty("No manifest globs configured", button: ("How to configure", { NSWorkspace.shared.open(Self.docsURL) }))
            case .noRows:
                empty("No units in the configured manifests", button: nil)
            case .failed(let text):
                empty(text, button: ("Try again", model.refresh))
            case .units:
                ForEach(model.panel.sections) { section($0) }
            }
        }
    }

    private func banner(_ banner: PanelBanner) -> some View {
        let (symbol, color): (String, Color) = switch banner {
        case .stale: ("clock.badge.exclamationmark", .orange)
        case .tmux: ("bolt.slash", .secondary)
        case .warning: ("exclamationmark.triangle.fill", .orange)
        }
        return Label(banner.text, systemImage: symbol)
            .font(.caption)
            .foregroundStyle(color)
            .fixedSize(horizontal: false, vertical: true)
    }

    private var attention: some View {
        VStack(alignment: .leading, spacing: Theme.inner + 2) {
            Label("Needs attention (\(model.panel.attention.count))", systemImage: "exclamationmark.triangle.fill")
                .font(.caption.weight(.semibold))
                .foregroundStyle(Theme.attention)
            ForEach(model.panel.attention) { DivergenceRow(divergence: $0, model: model) }
        }
        .padding(Theme.card)
        .frame(maxWidth: .infinity, alignment: .leading)
        .kitchenSurface(tint: Theme.attention)
        .accessibilityElement(children: .contain)
    }

    private func section(_ section: UnitSection) -> some View {
        VStack(alignment: .leading, spacing: Theme.inner + 2) {
            Label("\(section.title.uppercased()) · \(section.count)", systemImage: Theme.symbol(section.status))
                .font(.caption.weight(.semibold))
                .foregroundStyle(Theme.color(section.status))
                .padding(.top, Theme.inner)
                .accessibilityAddTraits(.isHeader)
            ForEach(section.units) { UnitRow(unit: $0, model: model) }
            if !section.earlier.isEmpty {
                DisclosureGroup("Earlier (\(section.earlier.count))", isExpanded: $earlierOpen) {
                    VStack(spacing: Theme.inner + 2) {
                        ForEach(section.earlier) { UnitRow(unit: $0, model: model) }
                    }
                    .padding(.top, Theme.inner)
                }
                .font(.caption)
                .metadataStyle()
            }
        }
    }

    private var placeholderRow: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("unit-name-here").font(.callout.weight(.medium))
            Text("project · 12m").font(.caption)
        }
        .padding(Theme.row)
        .frame(maxWidth: .infinity, alignment: .leading)
        .kitchenSurface(radius: Theme.rowRadius)
        .redacted(reason: .placeholder)
    }

    private func empty(_ text: String, button: (String, () -> Void)?) -> some View {
        VStack(spacing: Theme.row) {
            Image(systemName: "tray").font(.title2).foregroundStyle(.secondary)
            Text(text).font(.callout).multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
            if let (title, action) = button {
                Button(title, action: action).buttonStyle(.glass).controlSize(.small)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(Theme.margin)
    }

    // MARK: footer

    private var footer: some View {
        HStack(spacing: Theme.row) {
            Button("Manifests", systemImage: "folder", action: model.openManifests)
                .disabled((model.feed.snapshot?.manifestDir ?? "").isEmpty)
            if model.panel.harvested > 0 {
                Text("\(model.panel.harvested) harvested").font(.caption).metadataStyle()
            }
            Spacer()
            Menu {
                Picker("Refresh every", selection: $model.refreshInterval) {
                    ForEach(AppModel.refreshChoices, id: \.self) { Text(interval($0)).tag($0) }
                }
                Toggle("Show Claude usage", isOn: $model.showUsage)
                Toggle("Show weekly usage in the menu bar", isOn: $model.showWeeklyInMenuBar)
                    .disabled(!model.showUsage)
            } label: {
                Label("Settings", systemImage: "gearshape").font(.caption)
            }
            .menuStyle(.button)
            .buttonStyle(.borderless)
            .controlSize(.mini)
            .menuIndicator(.hidden)
            .fixedSize()
            Button("Quit") { NSApp.terminate(nil) }
                .keyboardShortcut("q")
        }
        .buttonStyle(.borderless)
        .font(.caption)
        .controlSize(.small)
        .labelStyle(.titleAndIcon)
    }

    private func interval(_ seconds: TimeInterval) -> String {
        seconds < 60 ? "\(Int(seconds)) s" : "\(Int(seconds / 60)) min"
    }
}
