import KitchenCore
import SwiftUI

/// The menu-bar item: a template SF Symbol (its shape carries the alarm) plus `▸N !N`.
public struct MenuBarLabel: View {
    let model: AppModel

    public init(model: AppModel) { self.model = model }

    public var body: some View {
        let summary = model.panel.menuBar
        HStack(spacing: 3) {
            Image(systemName: summary.symbol)
            if !text.isEmpty { Text(text).monospacedDigit() }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(spokenLabel)
    }

    var text: String {
        var parts = [model.panel.menuBar.text]
        if let week = shownWeeklyPercent { parts.append(Formatting.percent(week)) }
        return parts.filter { !$0.isEmpty }.joined(separator: " ")
    }

    /// What VoiceOver reads: the kitchen summary, plus the weekly usage whenever it is drawn.
    var spokenLabel: String {
        let base = model.panel.menuBar.accessibilityLabel
        guard let week = shownWeeklyPercent else { return base }
        return "\(base), \(Formatting.percent(week)) of the weekly limit used"
    }

    private var shownWeeklyPercent: Double? {
        model.showUsage && model.showWeeklyInMenuBar ? model.weeklyPercent : nil
    }
}
