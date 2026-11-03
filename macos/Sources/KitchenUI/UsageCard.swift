import KitchenCore
import SwiftUI

/// Claude usage: two rings (Week, 5 hours), a thin bar per model limit, and a footnote.
struct UsageCard: View {
    let state: UsageState
    let now: Date
    let retry: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.row) {
            Label("Claude usage", systemImage: "gauge.with.dots.needle.33percent")
                .font(.caption.weight(.semibold))
                .metadataStyle()
            content
        }
        .padding(Theme.card)
        .frame(maxWidth: .infinity, alignment: .leading)
        .kitchenSurface()
    }

    @ViewBuilder private var content: some View {
        switch state {
        case .idle, .loading:
            meters(UsageReport(sevenDay: .init(utilization: 50, resetsAt: nil)).meters())
                .redacted(reason: .placeholder)
        case .ok(let report, _), .stale(let report, _, _, _):
            meters(report.meters())
            if let note = state.footnote(now: now) {
                Text(note).font(.caption).metadataStyle().monospacedDigit()
            }
        case .problem(let problem):
            HStack(alignment: .firstTextBaseline) {
                Label(problem.message(now: now), systemImage: icon(problem))
                    .font(.callout)
                Spacer(minLength: Theme.row)
                if problem.offersRetry {
                    Button("Try again", action: retry).buttonStyle(.glass).controlSize(.small)
                }
            }
        }
    }

    private func meters(_ all: [UsageMeter]) -> some View {
        let main = all.filter { $0.kind != .model }
        let models = all.filter { $0.kind == .model }
        return VStack(alignment: .leading, spacing: Theme.row) {
            HStack(alignment: .top, spacing: Theme.margin) {
                ForEach(main) { UsageRing(meter: $0, now: now) }
                Spacer(minLength: 0)
            }
            ForEach(models) { UsageBar(meter: $0) }
        }
    }

    private func icon(_ problem: UsageProblem) -> String {
        switch problem {
        case .keychainDenied, .keychainTimedOut, .unreadable: "key.slash"
        case .notSignedIn, .needsLogin: "person.crop.circle.badge.exclamationmark"
        case .rateLimited, .unavailable: "icloud.slash"
        }
    }
}

struct UsageRing: View {
    let meter: UsageMeter
    let now: Date
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let fraction = min(1, max(0, (meter.percent ?? 0) / 100))
        let color = Theme.color(meter.severity)
        HStack(spacing: Theme.row) {
            ZStack {
                Circle().stroke(.quaternary, lineWidth: 6)
                Circle()
                    .trim(from: 0, to: fraction)
                    .stroke(color, style: StrokeStyle(lineWidth: 6, lineCap: .round))
                    .rotationEffect(.degrees(-90))
                    .animation(reduceMotion ? nil : .easeOut(duration: 0.4), value: fraction)
                Text(meter.percent.map(Formatting.percent) ?? "–")
                    .font(.caption2.weight(.semibold))
                    .monospacedDigit()
            }
            .frame(width: 44, height: 44)
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 3) {
                    Text(meter.label).font(.callout.weight(.medium))
                    if meter.severity == .critical {
                        Image(systemName: "exclamationmark.circle.fill").foregroundStyle(Theme.attention)
                            .font(.caption)
                    }
                }
                Text(detail).font(.caption).metadataStyle().monospacedDigit()
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibility)
    }

    private var detail: String {
        if meter.percent == nil, meter.kind == .fiveHour { return "no open window" }
        guard let at = meter.resetsAt else { return " " }
        return "resets in \(Formatting.duration(until: at, now: now))"
    }

    private var accessibility: String {
        guard let percent = meter.percent else {
            return meter.kind == .fiveHour ? "\(meter.label), no open window" : "\(meter.label), unknown"
        }
        var text = "\(meter.label), \(Int(percent.rounded())) percent used"
        if let at = meter.resetsAt { text += ", resets in \(Formatting.spokenDuration(until: at, now: now))" }
        return text
    }
}

struct UsageBar: View {
    let meter: UsageMeter

    var body: some View {
        let fraction = min(1, max(0, (meter.percent ?? 0) / 100))
        HStack(spacing: Theme.row) {
            HStack(spacing: 3) {
                Text(meter.label).font(.caption)
                if meter.severity == .critical {
                    Image(systemName: "exclamationmark.circle.fill").foregroundStyle(Theme.attention).font(.caption2)
                }
            }
            .frame(width: 76, alignment: .leading)
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(.quaternary)
                    Capsule().fill(Theme.color(meter.severity)).frame(width: geo.size.width * fraction)
                }
            }
            .frame(height: 5)
            Text(meter.percent.map(Formatting.percent) ?? "–")
                .font(.caption).monospacedDigit()
                .frame(width: 38, alignment: .trailing)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(meter.label), \(meter.percent.map { "\(Int($0.rounded())) percent used" } ?? "unknown")")
    }
}
