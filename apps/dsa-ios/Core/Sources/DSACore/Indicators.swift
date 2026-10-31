import Foundation

/// 技術指標。輸入一律是已依週期聚合、按日期排序的 K 棒；輸出與輸入等長，算不出來的位置是 nil，
/// 圖表依索引對回 K 棒，不會因為開頭缺值而錯位。
public enum Indicators {
    /// 指數移動平均，以前 `period` 根的簡單平均起算。
    public static func ema(_ values: [Double], period: Int) -> [Double?] {
        guard period > 0, values.count >= period else { return Array(repeating: nil, count: values.count) }
        var result = [Double?](repeating: nil, count: values.count)
        let k = 2 / Double(period + 1)
        var current = values.prefix(period).reduce(0, +) / Double(period)
        result[period - 1] = current
        for index in period..<values.count {
            current = values[index] * k + current * (1 - k)
            result[index] = current
        }
        return result
    }

    public static func sma(_ values: [Double], period: Int) -> [Double?] {
        guard period > 0, values.count >= period else { return Array(repeating: nil, count: values.count) }
        var result = [Double?](repeating: nil, count: values.count)
        var sum = values.prefix(period - 1).reduce(0, +)
        for index in (period - 1)..<values.count {
            sum += values[index]
            result[index] = sum / Double(period)
            sum -= values[index - period + 1]
        }
        return result
    }

    public struct BollingerPoint: Hashable, Sendable {
        public let middle: Double
        public let upper: Double
        public let lower: Double
    }

    /// 布林通道：中軌 `period` 日均線，上下軌各加減 `width` 倍母體標準差。
    public static func bollinger(_ closes: [Double], period: Int = 20, width: Double = 2) -> [BollingerPoint?] {
        let middle = sma(closes, period: period)
        return middle.enumerated().map { index, mean in
            guard let mean else { return nil }
            let window = closes[(index - period + 1)...index]
            let variance = window.reduce(0) { $0 + ($1 - mean) * ($1 - mean) } / Double(period)
            let deviation = variance.squareRoot() * width
            return BollingerPoint(middle: mean, upper: mean + deviation, lower: mean - deviation)
        }
    }

    public struct MACDPoint: Hashable, Sendable {
        /// DIF（快線減慢線）
        public let dif: Double
        /// DEA（DIF 的訊號線）；前段不足時為 nil
        public let dea: Double?
        /// 柱狀體 = DIF − DEA（台股軟體常見的 ×2 不採用，與多數國際平台一致）
        public var histogram: Double? { dea.map { dif - $0 } }
    }

    public static func macd(_ closes: [Double], fast: Int = 12, slow: Int = 26, signal: Int = 9) -> [MACDPoint?] {
        let fastLine = ema(closes, period: fast)
        let slowLine = ema(closes, period: slow)
        let dif: [Double?] = zip(fastLine, slowLine).map { pair in
            guard let f = pair.0, let s = pair.1 else { return nil }
            return f - s
        }
        let firstDif = dif.firstIndex { $0 != nil } ?? dif.count
        let difValues = dif[firstDif...].compactMap { $0 }
        let deaTail = ema(difValues, period: signal)
        return dif.enumerated().map { index, value in
            guard let value else { return nil }
            return MACDPoint(dif: value, dea: deaTail[index - firstDif])
        }
    }

    public struct KDPoint: Hashable, Sendable {
        public let k: Double
        public let d: Double
    }

    /// 台股常用 KD(9,3,3)：RSV 取 `period` 根高低，K、D 以 1/3 平滑，起始值 50。
    public static func kd(_ candles: [ChartCandle], period: Int = 9) -> [KDPoint?] {
        guard period > 0, candles.count >= period else { return Array(repeating: nil, count: candles.count) }
        var result = [KDPoint?](repeating: nil, count: candles.count)
        var k = 50.0
        var d = 50.0
        for index in (period - 1)..<candles.count {
            let window = candles[(index - period + 1)...index]
            let high = window.map(\.high).max() ?? candles[index].high
            let low = window.map(\.low).min() ?? candles[index].low
            // 區間沒有高低差（停牌、一字盤）時 RSV 沒有定義，沿用前一根的 K。
            let rsv = high > low ? (candles[index].close - low) / (high - low) * 100 : k
            k = k * 2 / 3 + rsv / 3
            d = d * 2 / 3 + k / 3
            result[index] = KDPoint(k: k, d: d)
        }
        return result
    }

    /// Wilder RSI。
    public static func rsi(_ closes: [Double], period: Int = 14) -> [Double?] {
        guard period > 0, closes.count > period else { return Array(repeating: nil, count: closes.count) }
        var result = [Double?](repeating: nil, count: closes.count)
        var gain = 0.0
        var loss = 0.0
        for index in 1...period {
            let change = closes[index] - closes[index - 1]
            gain += max(change, 0)
            loss += max(-change, 0)
        }
        gain /= Double(period)
        loss /= Double(period)
        func value() -> Double { loss == 0 ? (gain == 0 ? 50 : 100) : 100 - 100 / (1 + gain / loss) }
        result[period] = value()
        if closes.count > period + 1 {
            for index in (period + 1)..<closes.count {
                let change = closes[index] - closes[index - 1]
                gain = (gain * Double(period - 1) + max(change, 0)) / Double(period)
                loss = (loss * Double(period - 1) + max(-change, 0)) / Double(period)
                result[index] = value()
            }
        }
        return result
    }
}
