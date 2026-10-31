import Foundation

/// 月曆格子採 UTC 公曆，只處理日期，不因手機時區而平移一天。
public enum EventCalendarDate {
    public static var calendar: Calendar {
        var value = Calendar(identifier: .gregorian)
        value.timeZone = TimeZone(secondsFromGMT: 0)!
        return value
    }

    public static func key(_ date: Date, timezone: String = "UTC") -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.timeZone = TimeZone(identifier: timezone)
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: date)
    }

    public static func parse(_ key: String) -> Date? {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.calendar = calendar
        formatter.timeZone = calendar.timeZone
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.isLenient = false
        return formatter.date(from: key)
    }

    /// 使用者所在地的「今天」：決定月曆預設開哪一天；事件本身仍以來源市場日期顯示。
    public static func deviceToday(now: Date = Date(), timeZone: TimeZone = .current) -> String {
        key(now, timezone: timeZone.identifier)
    }

    public static func monthStart(_ date: Date) -> Date {
        calendar.date(from: calendar.dateComponents([.year, .month], from: date))!
    }

    public static func monthEnd(_ date: Date) -> Date {
        calendar.date(byAdding: DateComponents(month: 1, day: -1), to: monthStart(date))!
    }

    public static func cells(_ month: Date) -> [String?] {
        let first = monthStart(month)
        let leading = calendar.component(.weekday, from: first) - 1
        let count = calendar.range(of: .day, in: .month, for: first)!.count
        return Array(repeating: nil, count: leading) + (0..<count).map {
            key(calendar.date(byAdding: .day, value: $0, to: first)!)
        }
    }
}
