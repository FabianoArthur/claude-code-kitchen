import KitchenCore
import SwiftUI

struct UnitRow: View {
    let unit: KitchenUnit
    let model: AppModel
    @State private var hovering = false

    var body: some View {
        HStack(alignment: .top, spacing: Theme.row) {
            Image(systemName: Theme.symbol(unit.status))
                .font(.caption)
                .foregroundStyle(Theme.color(unit.status))
                .frame(width: 14)
                .padding(.top, 2)
            VStack(alignment: .leading, spacing: 2) {
                Text(unit.unit).font(.callout.weight(.medium)).lineLimit(1)
                if !metadata.isEmpty {
                    Text(metadata).font(.caption).metadataStyle().monospacedDigit().lineLimit(1)
                }
                if !unit.reason.isEmpty {
                    Text(unit.reason).font(.caption).foregroundStyle(.orange)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if !unit.pane.isEmpty {
                    Text("› \(unit.pane)").font(.caption.monospaced()).metadataStyle()
                        .lineLimit(1).truncationMode(.tail)
                }
            }
            Spacer(minLength: Theme.inner)
            if hovering && (unit.prLink != nil || unit.attachCommand != nil) {
                HStack(spacing: Theme.inner) {
                    if let link = unit.prLink {
                        Button("PR", systemImage: "arrow.up.right") { model.open(link) }
                    }
                    if unit.attachCommand != nil, let session = unit.session {
                        Button("Attach", systemImage: "terminal") { model.attach(session) }
                    }
                }
                .buttonStyle(.glass)
                .controlSize(.small)
                .labelStyle(.titleAndIcon)
            }
        }
        .padding(Theme.row)
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(.rect)
        .kitchenSurface(radius: Theme.rowRadius)
        .onHover { hovering = $0 }
        .contextMenu { menu }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(unit.accessibilityLabel)
        .accessibilityActions { menu }
    }

    private var metadata: String {
        var parts = [unit.project]
        if let age = unit.ageText { parts.append(age) }
        if !unit.pr.isEmpty { parts.append("PR #\(unit.pr)") }
        return parts.filter { !$0.isEmpty }.joined(separator: " · ")
    }

    @ViewBuilder private var menu: some View {
        if let link = unit.prLink {
            Button("Open PR #\(unit.pr)") { model.open(link) }
        }
        if let command = unit.attachCommand, let session = unit.session {
            Button("Attach") { model.attach(session) }
            Button("Copy attach command") { model.copy(command) }
        }
        if !unit.branch.isEmpty {
            Button("Copy branch") { model.copy(unit.branch) }
        }
    }
}

struct DivergenceRow: View {
    let divergence: Divergence
    let model: AppModel

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: Theme.row) {
            Image(systemName: "circle.fill").font(.system(size: 6)).foregroundStyle(Theme.attention)
            Text(divergence.text).font(.caption).fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .contentShape(.rect)
        .contextMenu {
            if let command = divergence.attachCommand, let session = divergence.session {
                Button("Attach") { model.attach(session) }
                Button("Copy attach command") { model.copy(command) }
            }
        }
    }
}
