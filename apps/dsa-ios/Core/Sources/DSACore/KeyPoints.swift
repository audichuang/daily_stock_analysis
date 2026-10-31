import Foundation

/// 圖上「值得注意」的位置：全部由價量規則算出，只描述發生過什麼，不給買賣建議。
public enum KeyPoints {
    public struct Cross: Hashable, Sendable {
        public let date: Date
        public let anchor: Date
        public let price: Double
        /// 短均線由下往上穿過長均線（黃金交叉）；false 是死亡交叉
        public let golden: Bool
    }

    public struct Gap: Hashable, Sendable {
        /// 跳空那根 K 棒
        public let date: Date
        public let anchor: Date
        public let lower: Double
        public let upper: Double
        public let up: Bool
    }

    public struct YearRange: Hashable, Sendable {
        public let high: Double
        public let highDate: Date
        public let low: Double
        public let lowDate: Date
    }

    public static func extremes(_ candles: [ChartCandle]) -> (high: ChartCandle, low: ChartCandle)? {
        guard let high = candles.max(by: { $0.high < $1.high }),
              let low = candles.min(by: { $0.low < $1.low }) else { return nil }
        return (high, low)
    }

    /// 最近 52 週（以最後一根的日期往回一年）的最高與最低；資料不足一年時回 nil，不把較短區間冒充成 52 週。
    public static func yearRange(_ daily: [ChartCandle]) -> YearRange? {
        guard let last = daily.last?.date, let first = daily.first?.date,
              let start = TradingDay.calendar.date(byAdding: .year, value: -1, to: last), first <= start else { return nil }
        let window = daily.filter { $0.date > start }
        guard let (high, low) = extremes(window) else { return nil }
        return YearRange(high: high.high, highDate: high.date, low: low.low, lowDate: low.date)
    }

    /// 兩條均線的交叉點；兩條線依日期對齊，只在兩邊都有值的日子比較。
    public static func crosses(fast: [MovingAveragePoint], slow: [MovingAveragePoint]) -> [Cross] {
        let slowByDate = Dictionary(slow.map { ($0.date, $0.value) }, uniquingKeysWith: { first, _ in first })
        var previous: Double?
        var result: [Cross] = []
        for point in fast {
            guard let slowValue = slowByDate[point.date] else { continue }
            let spread = point.value - slowValue
            if let previous, previous != 0, spread != 0, (previous < 0) != (spread < 0) {
                result.append(Cross(date: point.date, anchor: point.anchor, price: point.value, golden: spread > 0))
            }
            if spread != 0 { previous = spread }
        }
        return result
    }

    /// 成交量超過前 `window` 根平均的 `ratio` 倍。
    public static func volumeSpikes(_ candles: [ChartCandle], window: Int = 20, ratio: Double = 2) -> [ChartCandle] {
        guard window > 0, candles.count > window else { return [] }
        var result: [ChartCandle] = []
        for index in window..<candles.count {
            guard let volume = candles[index].volume else { continue }
            let history = candles[(index - window)..<index].compactMap(\.volume)
            guard history.count == window else { continue }
            let average = history.reduce(0, +) / Double(window)
            if average > 0, volume >= average * ratio { result.append(candles[index]) }
        }
        return result
    }

    /// 尚未被後續 K 棒回補的跳空缺口，最新的在後、最多 `limit` 個。
    /// 部分回補時缺口縮成還沒被碰到的那一段。
    public static func unfilledGaps(_ candles: [ChartCandle], limit: Int = 3) -> [Gap] {
        guard candles.count >= 2 else { return [] }
        var result: [Gap] = []
        for index in stride(from: candles.count - 1, through: 1, by: -1) {
            let previous = candles[index - 1]
            let current = candles[index]
            let later = candles[(index + 1)...]
            if current.low > previous.high {
                let upper = min(current.low, later.map(\.low).min() ?? current.low)
                if upper > previous.high {
                    result.append(Gap(date: current.date, anchor: current.anchor, lower: previous.high, upper: upper, up: true))
                }
            } else if current.high < previous.low {
                let lower = max(current.high, later.map(\.high).max() ?? current.high)
                if lower < previous.low {
                    result.append(Gap(date: current.date, anchor: current.anchor, lower: lower, upper: previous.low, up: false))
                }
            }
            if result.count == limit { break }
        }
        return result.reversed()
    }
}
