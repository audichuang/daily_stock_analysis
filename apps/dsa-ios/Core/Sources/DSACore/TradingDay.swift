import Foundation

/// 交易日是日期標籤，以 UTC 表示，與報價的實際時間戳分開處理。
public enum TradingDay {
    public static let timeZone = TimeZone(secondsFromGMT: 0)!

    public static var calendar: Calendar {
        var result = Calendar(identifier: .gregorian)
        result.timeZone = timeZone
        return result
    }

    public static func parse(_ value: String) -> Date? {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = timeZone
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.date(from: String(value.prefix(10)))
    }

    public static func start(months: Int, before latest: Date) -> Date? {
        calendar.date(byAdding: .month, value: -months, to: latest)
    }

    /// 以影線的日期為中心，實體佔一日的 65%，避免連續時間軸把比例寬度壓成細線。
    public static func candleBody(around date: Date) -> ClosedRange<Date> {
        let halfWidth: TimeInterval = 86_400 * 0.65 / 2
        return date.addingTimeInterval(-halfWidth)...date.addingTimeInterval(halfWidth)
    }

    public static func readoutStyle(locale: Locale = .current) -> Date.FormatStyle {
        Date.FormatStyle(locale: locale, calendar: calendar, timeZone: timeZone).year().month().day()
    }

    public static func axisStyle(locale: Locale = .current) -> Date.FormatStyle {
        Date.FormatStyle(locale: locale, calendar: calendar, timeZone: timeZone).month(.defaultDigits).day()
    }
}
