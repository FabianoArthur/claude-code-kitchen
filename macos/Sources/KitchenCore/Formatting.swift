import Foundation

/// Short, fixed English texts for the panel. Pure functions of their inputs.
public enum Formatting {
    /// "now", "5m", "3h 10m", "2d 4h" — rounds up to the minute, so "1m" until the reset passes.
    public static func duration(until date: Date, now: Date) -> String {
        let seconds = date.timeIntervalSince(now)
        guard seconds > 0 else { return "now" }
        let (d, h, m) = split(minutes: Int((seconds / 60).rounded(.up)))
        if d > 0 { return h > 0 ? "\(d)d \(h)h" : "\(d)d" }
        if h > 0 { return m > 0 ? "\(h)h \(m)m" : "\(h)h" }
        return "\(m)m"
    }

    /// VoiceOver form of `duration(until:now:)`: "3 hours 10 minutes".
    public static func spokenDuration(until date: Date, now: Date) -> String {
        let seconds = date.timeIntervalSince(now)
        guard seconds > 0 else { return "now" }
        return spoken(minutes: Int((seconds / 60).rounded(.up)))
    }

    /// VoiceOver form of an age (rounded down, like the script's `age_text`).
    public static func spokenAge(seconds: Double) -> String {
        let minutes = Int(max(0, seconds) / 60)
        return minutes == 0 ? "less than a minute" : spoken(minutes: minutes)
    }

    /// "just now", "3m ago", "2h ago", "3d ago".
    public static func ago(since date: Date, now: Date) -> String {
        let seconds = max(0, now.timeIntervalSince(date))
        if seconds < 60 { return "just now" }
        if seconds < 3600 { return "\(Int(seconds / 60))m ago" }
        if seconds < 86_400 { return "\(Int(seconds / 3600))h ago" }
        return "\(Int(seconds / 86_400))d ago"
    }

    /// "62%"; anything above zero but under 1 % reads "<1%" so a used meter never says 0.
    public static func percent(_ value: Double) -> String {
        if value > 0 && value < 1 { return "<1%" }
        return "\(Int(value.rounded()))%"
    }

    /// "14:02", 24-hour, in the given calendar's time zone.
    public static func clock(_ date: Date, calendar: Calendar = .current) -> String {
        let c = calendar.dateComponents([.hour, .minute], from: date)
        return String(format: "%02d:%02d", c.hour ?? 0, c.minute ?? 0)
    }

    private static func split(minutes: Int) -> (Int, Int, Int) {
        (minutes / 1440, (minutes % 1440) / 60, minutes % 60)
    }

    private static func spoken(minutes: Int) -> String {
        let (d, h, m) = split(minutes: minutes)
        func unit(_ n: Int, _ word: String) -> String { n == 1 ? "1 \(word)" : "\(n) \(word)s" }
        if d > 0 { return h > 0 ? "\(unit(d, "day")) \(unit(h, "hour"))" : unit(d, "day") }
        if h > 0 { return m > 0 ? "\(unit(h, "hour")) \(unit(m, "minute"))" : unit(h, "hour") }
        return unit(m, "minute")
    }
}
