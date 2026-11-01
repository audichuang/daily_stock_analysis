import Foundation

/// 一根 K 棒。日 K 的 `periodStart` 等於 `date`；週 K、月 K 的 `date` 是該期最後一個交易日，
/// `periodStart` 是第一個交易日，讀數區才能標出整段區間。
public struct ChartCandle: Identifiable, Hashable, Sendable {
    public let date: Date
    public let periodStart: Date
    public let open: Double
    public let high: Double
    public let low: Double
    public let close: Double
    public let volume: Double?
    /// 由即時報價補上的暫定 K；併成週 K、月 K 時只要含暫定日就整根視為暫定。
    public let isProvisional: Bool

    public var id: Date { date }

    /// 圖上的 x 位置：日 K 是當天，週 K、月 K 是區間首末交易日的中點，
    /// 實體才不會以月底為中心跨進下個月。
    public var anchor: Date {
        periodStart.addingTimeInterval(date.timeIntervalSince(periodStart) / 2)
    }

    public init(date: Date, periodStart: Date? = nil, open: Double, high: Double, low: Double, close: Double, volume: Double?, isProvisional: Bool = false) {
        self.date = date
        self.periodStart = periodStart ?? date
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
        self.isProvisional = isProvisional
    }
}

public enum CandlePeriod: String, CaseIterable, Identifiable, Sendable {
    case day, week, month

    public var id: String { rawValue }

    public var label: String {
        switch self {
        case .day: "日 K"
        case .week: "週 K"
        case .month: "月 K"
        }
    }

    /// K 棒之間的日曆日間距，決定實體寬度。
    public var spanDays: Double {
        switch self {
        case .day: 1
        case .week: 7
        case .month: 30
        }
    }

    /// 台股慣用均線：日 K 為週／月／季線，週 K 約一季／半年，月 K 為季／半年／年。
    public var movingAverageWindows: [Int] {
        switch self {
        case .day: [5, 20, 60]
        case .week: [5, 13, 26]
        case .month: [3, 6, 12]
        }
    }
}

public struct MovingAveragePoint: Hashable, Sendable {
    public let window: Int
    public let date: Date
    /// 與所屬 K 棒同一個 x 位置（見 `ChartCandle.anchor`）。
    public let anchor: Date
    public let value: Double
}

public enum CandleSeries {
    /// 依交易日曆把日 K 併成週 K（週一起算）或月 K：開＝首根開、收＝末根收、高低取極值、量相加。
    public static func aggregate(_ daily: [ChartCandle], period: CandlePeriod) -> [ChartCandle] {
        let sorted = daily.sorted { $0.date < $1.date }
        guard period != .day else { return sorted }
        var calendar = TradingDay.calendar
        calendar.firstWeekday = 2
        calendar.minimumDaysInFirstWeek = 4
        func key(_ date: Date) -> [Int] {
            switch period {
            case .day: []
            case .week: [calendar.component(.yearForWeekOfYear, from: date), calendar.component(.weekOfYear, from: date)]
            case .month: [calendar.component(.year, from: date), calendar.component(.month, from: date)]
            }
        }
        var result: [ChartCandle] = []
        var bucket: [ChartCandle] = []
        var bucketKey: [Int] = []
        func flush() {
            guard let first = bucket.first, let last = bucket.last else { return }
            let volumes = bucket.compactMap(\.volume)
            result.append(ChartCandle(
                date: last.date,
                periodStart: first.periodStart,
                open: first.open,
                high: bucket.map(\.high).max() ?? last.high,
                low: bucket.map(\.low).min() ?? last.low,
                close: last.close,
                volume: volumes.isEmpty ? nil : volumes.reduce(0, +),
                isProvisional: bucket.contains(where: \.isProvisional)
            ))
        }
        for candle in sorted {
            let candleKey = key(candle.date)
            if candleKey != bucketKey {
                flush()
                bucket = []
                bucketKey = candleKey
            }
            bucket.append(candle)
        }
        flush()
        return result
    }

    /// 收盤價簡單移動平均；不足一個窗口的 K 棒不給值，避免開頭出現假均線。
    public static func movingAverage(_ candles: [ChartCandle], window: Int) -> [MovingAveragePoint] {
        guard window > 0, candles.count >= window else { return [] }
        var sum = candles.prefix(window - 1).reduce(0) { $0 + $1.close }
        var points: [MovingAveragePoint] = []
        points.reserveCapacity(candles.count - window + 1)
        for index in (window - 1)..<candles.count {
            sum += candles[index].close
            points.append(MovingAveragePoint(window: window, date: candles[index].date, anchor: candles[index].anchor, value: sum / Double(window)))
            sum -= candles[index - window + 1].close
        }
        return points
    }

    /// 最新一根相對昨收的漲跌（用日 K 算，週 K、月 K 的最新價標籤也是相對昨收）。不足兩根回 nil。
    public static func latestChange(_ daily: [ChartCandle]) -> Double? {
        let sorted = daily.sorted { $0.date < $1.date }
        guard sorted.count >= 2 else { return nil }
        return sorted[sorted.count - 1].close - sorted[sorted.count - 2].close
    }

    /// 拖曳選取：取 x 位置（anchor）最近的 K 棒。用區間末日找會在月初選到上一個月。
    public static func nearest(to selected: Date, in candles: [ChartCandle]) -> ChartCandle? {
        candles.min { abs($0.anchor.timeIntervalSince(selected)) < abs($1.anchor.timeIntervalSince(selected)) }
    }
}

/// 成交量顯示：資料一律是股，台股畫面換算成張（1 張＝1,000 股），其他市場仍是股。
public enum VolumeDisplay {
    public static func unit(market: String) -> String {
        market == "tw" ? "張" : "股"
    }

    public static func value(_ shares: Double, market: String) -> Double {
        market == "tw" ? shares / 1_000 : shares
    }

    /// 軸標用：不帶單位。一萬以上用「萬」「億」縮寫。
    public static func axisText(_ shares: Double, market: String) -> String {
        let display = value(shares, market: market)
        let locale = Locale(identifier: "zh_TW")
        if display >= 10_000 {
            return display.formatted(.number.notation(.compactName).precision(.fractionLength(0...1)).locale(locale))
        }
        return display.formatted(.number.precision(.fractionLength(0...1)).locale(locale))
    }

    public static func text(_ shares: Double, market: String) -> String {
        "\(axisText(shares, market: market)) \(unit(market: market))"
    }
}
