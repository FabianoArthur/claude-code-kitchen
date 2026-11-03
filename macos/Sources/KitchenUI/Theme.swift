import KitchenCore
import SwiftUI

/// Design tokens from docs/macos-app.md. System colours only, so light, dark and
/// Increase Contrast come for free.
public enum Theme {
    public static let panelWidth: CGFloat = 360
    public static let maxListHeight: CGFloat = 520
    public static let inner: CGFloat = 4
    public static let row: CGFloat = 8
    public static let card: CGFloat = 12
    public static let margin: CGFloat = 16
    public static let cardRadius: CGFloat = 16
    public static let rowRadius: CGFloat = 12

    public static func color(_ status: UnitStatus) -> Color {
        switch status {
        case .running: .blue
        case .waiting: .orange
        case .done: .green
        case .queued, .aborted, .harvested, .unknown: .secondary
        }
    }

    /// Same symbols as the SwiftBar plugin.
    public static func symbol(_ status: UnitStatus) -> String {
        switch status {
        case .running: "play.fill"
        case .waiting: "hand.raised.fill"
        case .queued: "hourglass"
        case .done: "checkmark.circle.fill"
        case .aborted: "xmark.circle"
        case .harvested: "archivebox"
        case .unknown: "questionmark.circle"
        }
    }

    public static func color(_ severity: Severity) -> Color {
        switch severity {
        case .normal: .accentColor
        case .warning: .orange
        case .critical: .red
        }
    }

    public static let attention = Color.red
}

/// Every glass surface goes through here: opaque under Reduce Transparency, bordered under
/// Increase Contrast.
struct KitchenSurface: ViewModifier {
    var radius: CGFloat
    var tint: Color?
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.colorSchemeContrast) private var contrast

    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: radius, style: .continuous)
        if reduceTransparency {
            content
                .background {
                    shape.fill(Color(nsColor: .controlBackgroundColor))
                    if let tint { shape.fill(tint.opacity(0.12)) }
                }
                .overlay(shape.strokeBorder(Color(nsColor: .separatorColor), lineWidth: 0.5))
        } else {
            content
                .glassEffect(tint.map { Glass.regular.tint($0.opacity(0.18)) } ?? .regular, in: shape)
                .overlay {
                    if contrast == .increased { shape.strokeBorder(Color(nsColor: .separatorColor), lineWidth: 1) }
                }
        }
    }
}

extension View {
    func kitchenSurface(radius: CGFloat = Theme.cardRadius, tint: Color? = nil) -> some View {
        modifier(KitchenSurface(radius: radius, tint: tint))
    }
}

/// `.secondary`, or `.primary` under Increase Contrast.
struct MetadataStyle: ViewModifier {
    @Environment(\.colorSchemeContrast) private var contrast
    func body(content: Content) -> some View {
        content.foregroundStyle(contrast == .increased ? AnyShapeStyle(.primary) : AnyShapeStyle(.secondary))
    }
}

extension View {
    func metadataStyle() -> some View { modifier(MetadataStyle()) }
}
