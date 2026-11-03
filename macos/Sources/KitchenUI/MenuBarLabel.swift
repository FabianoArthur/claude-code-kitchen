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
        .accessibilityLabel(summary.accessibilityLabel)
    }

    var text: String {
        var parts = [model.panel.menuBar.text]
        if model.showUsage, model.showWeeklyInMenuBar, let week = model.weeklyPercent {
            parts.append(Formatting.percent(week))
        }
        return parts.filter { !$0.isEmpty }.joined(separator: " ")
    }
}
