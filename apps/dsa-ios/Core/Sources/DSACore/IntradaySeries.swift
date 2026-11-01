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
    /// 該點成交量（股）；日線與舊版後端沒有
    public let volume: Double?
    /// 當日累計均價；僅分時
    public let avgPrice: Double?

    public init(t: String, price: Double, volume: Double? = nil, avgPrice: Double? = nil) {
        self.t = t
        self.price = price
        self.volume = volume
        self.avgPrice = avgPrice
    }
}

/// 分時圖用的點與交易時段。
public struct IntradaySeries: Sendable {
    public struct Point: Hashable, Sendable, Identifiable {
        public let time: Date
        public let price: Double
        public let volume: Double?
        public let avgPrice: Double?
        public var id: Date { time }
    }

    public struct VolumeBar: Hashable, Sendable, Identifiable {
        public let time: Date
        public let volume: Double
        /// 與前一點的價差，決定量柱顏色；第一點是 0。
        public let change: Double
        public var id: Date { time }
    }

    /// 分時價格軸。`centered` 時昨收在正中央；大跳空時退回只看當日範圍，昨收改標在邊緣。
    public struct PriceScale: Equatable, Sendable {
        public let domain: ClosedRange<Double>
        public let ticks: [Double]
        public let centered: Bool
    }

    /// 昨收距當日價格區間超過這個比例才算大跳空。
    static let largeGapRatio = 0.03
    /// 以昨收為中軸時，當日走勢佔不到這個高度比例就算被壓扁。
    static let minimumPlotShare = 0.25

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
            return Point(time: time, price: point.price,
                         volume: point.volume.flatMap { $0.isFinite && $0 >= 0 ? $0 : nil },
                         avgPrice: point.avgPrice.flatMap { $0.isFinite && $0 > 0 ? $0 : nil })
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

    /// 資料截至：這批分時最後一點的時間。
    public var asOf: Date? { points.last?.time }

    /// X 軸標籤：開盤、時段中點、收盤，與 x 軸兩端對齊。
    public var axisTicks: [Date] {
        [session.lowerBound,
         session.lowerBound.addingTimeInterval(session.upperBound.timeIntervalSince(session.lowerBound) / 2),
         session.upperBound]
    }

    public var volumeBars: [VolumeBar] {
        var previous: Double?
        var bars: [VolumeBar] = []
        for point in points {
            if let volume = point.volume {
                bars.append(VolumeBar(time: point.time, volume: volume, change: previous.map { point.price - $0 } ?? 0))
            }
            previous = point.price
        }
        return bars
    }

    /// 有昨收時以昨收為中軸、上下對稱；只有「跳空夠大且會把走勢壓扁」才退回當日範圍（INTC 10/30 跌 28%）。
    public func priceScale(previousClose: Double?) -> PriceScale {
        let prices = points.map(\.price)
        let lower = prices.min() ?? 0
        let upper = prices.max() ?? 1
        let margin = max((upper - lower) * 0.12, abs(upper) * 0.002, 0.01)
        let plain = (lower - margin)...(upper + margin)
        let step = (plain.upperBound - plain.lowerBound) / 5
        let plainScale = PriceScale(domain: plain, ticks: (1...4).map { plain.lowerBound + step * Double($0) }, centered: false)
        guard let previousClose, previousClose > 0, previousClose.isFinite else { return plainScale }
        let bound = max(max(abs(upper - previousClose), abs(lower - previousClose)) * 1.1, previousClose * 0.002)
        let gap = previousClose > upper ? previousClose - upper : previousClose < lower ? lower - previousClose : 0
        if gap / previousClose >= Self.largeGapRatio, (upper - lower) / (2 * bound) < Self.minimumPlotShare {
            return plainScale
        }
        return PriceScale(
            domain: (previousClose - bound)...(previousClose + bound),
            ticks: [previousClose - bound * 0.75, previousClose - bound * 0.375, previousClose, previousClose + bound * 0.375, previousClose + bound * 0.75],
            centered: true
        )
    }

    /// 分時那一天的昨收：近一月日線裡、日期早於 `sessionDay` 的最後一根收盤。
    /// 用日期對齊而不是拿個股頁載入時的報價昨收——頁面開過夜後那個昨收屬於前一天，漲跌方向會算反。
    public func previousClose(from daily: [TrendPoint]) -> Double? {
        daily
            .filter { String($0.t.prefix(10)) < sessionDay && $0.price.isFinite && $0.price > 0 }
            .max { $0.t.prefix(10) < $1.t.prefix(10) }?
            .price
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
