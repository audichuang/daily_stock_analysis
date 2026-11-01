import Foundation

/// Short date, money and price-precision helpers shared by the iOS screens.
public enum DisplayFormatting {
    private static let locale = Locale(identifier: "zh_TW")
    private static let weekdays = ["日", "一", "二", "三", "四", "五", "六"]

    private static func calendar(_ timeZone: TimeZone) -> Calendar {
        var value = Calendar(identifier: .gregorian)
        value.timeZone = timeZone
        return value
    }

    /// 「10/30（五）」
    public static func shortDate(_ date: Date, timeZone: TimeZone = .current) -> String {
        let parts = calendar(timeZone).dateComponents([.month, .day, .weekday], from: date)
        let month = parts.month ?? 0
        let day = parts.day ?? 0
        let weekday = weekdays[((parts.weekday ?? 1) - 1) % 7]
        return "\(month)/\(day)（\(weekday)）"
    }

    /// 「10/30 13:33」
    public static func shortStamp(_ date: Date, timeZone: TimeZone = .current) -> String {
        let parts = calendar(timeZone).dateComponents([.month, .day, .hour, .minute], from: date)
        return String(format: "%d/%d %02d:%02d", parts.month ?? 0, parts.day ?? 0, parts.hour ?? 0, parts.minute ?? 0)
    }

    /// Summary-sized money: TWD as whole NT$, USD as US$ with two decimals,
    /// other currencies keep their code with two decimals.
    public static func summaryMoney(_ value: Double?, currency: String?) -> String {
        guard let value, value.isFinite else { return DisplayNumber.noValue }
        let code = currency?.trimmingCharacters(in: .whitespaces).uppercased() ?? ""
        let (prefix, digits): (String, Int) = {
            switch code {
            case "TWD": return ("NT$", 0)
            case "USD": return ("US$", 2)
            case "": return ("", 2)
            default: return ("\(code) ", 2)
            }
        }()
        let text = abs(value).formatted(.number.locale(locale).precision(.fractionLength(digits)))
        // Do not print "−NT$0" when the value rounds to zero.
        let roundsToZero = !text.contains(where: { ("1"..."9").contains($0) })
        let sign = value < 0 && !roundsToZero ? DisplayNumber.minusSign : ""
        return sign + prefix + text
    }

    /// Decimal places by price band, following the TWSE tick-size ladder:
    /// below 50 ticks are 0.01/0.05, 50–500 are 0.1/0.5, 500 and above are whole units.
    /// For input steps, axis labels and alert prices only: quote display keeps using
    /// `DisplayNumber.price`, which never rounds significant digits (00631L 443.15).
    public static func priceDecimals(_ price: Double?) -> Int {
        guard let price, price.isFinite else { return 2 }
        let magnitude = abs(price)
        if magnitude >= 500 { return 0 }
        if magnitude >= 50 { return 1 }
        return 2
    }

    /// Calendar-day distance in words: 「今天」「明天」「昨天」「3 天後」「3 天前」.
    public static func relativeDays(from start: Date, to end: Date, timeZone: TimeZone = .current) -> String {
        let cal = calendar(timeZone)
        let days = cal.dateComponents([.day], from: cal.startOfDay(for: start), to: cal.startOfDay(for: end)).day ?? 0
        switch days {
        case 0: return "今天"
        case 1: return "明天"
        case -1: return "昨天"
        case let n where n > 1: return "\(n) 天後"
        default: return "\(-days) 天前"
        }
    }
}
