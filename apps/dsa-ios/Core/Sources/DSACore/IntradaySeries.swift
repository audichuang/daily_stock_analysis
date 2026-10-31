import Foundation

/// `/api/v1/stocks/{code}/trend` 的回應。
public struct StockTrend: Codable, Sendable {
    public let stockCode: String
    public let range: String
    public let source: String?
    public let points: [TrendPoint]
}

public struct TrendPoint: Codable, Sendable, Hashable {
    /// ISO8601，帶市場當地時區（例：`2026-10-30T09:30:00-04:00`）
    public let t: String
    public let price: Double
}

/// 分時圖用的點與交易時段。
public struct IntradaySeries: Sendable {
    public struct Point: Hashable, Sendable, Identifiable {
        public let time: Date
        public let price: Double
        public var id: Date { time }
    }

    public let points: [Point]
    /// 這批點所屬交易日的開盤到收盤（市場當地時間），x 軸固定用它，盤中才看得出還剩多少時間。
    public let session: ClosedRange<Date>
    /// 交易日（市場當地日期，`yyyy-MM-dd`）
    public let sessionDay: String

    /// 只保留與最後一點同一個市場日的點；解析不了的時間丟掉。沒有點或市場不認得時回 nil。
    public init?(points raw: [TrendPoint], market: String) {
        guard let zone = Self.timeZone(market), let hours = Self.hours(market) else { return nil }
        let parsed = raw.compactMap { point -> Point? in
            guard let time = Self.parse(point.t), point.price.isFinite else { return nil }
            return Point(time: time, price: point.price)
        }.sorted { $0.time < $1.time }
        guard let last = parsed.last else { return nil }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = zone
        let day = calendar.dateComponents([.year, .month, .day], from: last.time)
        func at(_ minutes: Int) -> Date? {
            var components = day
            components.hour = minutes / 60
            components.minute = minutes % 60
            return calendar.date(from: components)
        }
        guard let open = at(hours.open), let close = at(hours.close) else { return nil }
        points = parsed.filter { calendar.isDate($0.time, inSameDayAs: last.time) }
        session = open...max(close, last.time)
        sessionDay = String(format: "%04d-%02d-%02d", day.year ?? 0, day.month ?? 0, day.day ?? 0)
    }

    public static func parse(_ value: String) -> Date? {
        let plain = ISO8601DateFormatter()
        plain.formatOptions = [.withInternetDateTime]
        if let date = plain.date(from: value) { return date }
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return fractional.date(from: value)
    }

    public static func timeZone(_ market: String) -> TimeZone? {
        switch market {
        case "tw": TimeZone(identifier: "Asia/Taipei")
        case "us": TimeZone(identifier: "America/New_York")
        case "hk": TimeZone(identifier: "Asia/Hong_Kong")
        case "cn": TimeZone(identifier: "Asia/Shanghai")
        case "jp": TimeZone(identifier: "Asia/Tokyo")
        case "kr": TimeZone(identifier: "Asia/Seoul")
        default: nil
        }
    }

    /// 一般交易時段（分鐘，當地時間）；午休不另外挖空。
    static func hours(_ market: String) -> (open: Int, close: Int)? {
        switch market {
        case "tw": (9 * 60, 13 * 60 + 30)
        case "us": (9 * 60 + 30, 16 * 60)
        case "hk": (9 * 60 + 30, 16 * 60)
        case "cn": (9 * 60 + 30, 15 * 60)
        case "jp": (9 * 60, 15 * 60 + 30)
        case "kr": (9 * 60, 15 * 60 + 30)
        default: nil
        }
    }
}
