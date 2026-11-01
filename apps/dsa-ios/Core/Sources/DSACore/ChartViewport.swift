import Foundation

/// 可捲動 K 線圖的視窗算術：X 軸是 K 棒序號（0 起算），週末與假日不佔位。
/// 抽成純函式是因為邊界組合（1 個月切月 K、縮放下限）用模擬器很難逐一點到。
public struct ChartViewport: Equatable, Sendable {
    /// 可見區間左緣與寬度，單位都是「根」。
    public var start: Double
    public var length: Double

    public init(start: Double, length: Double) {
        self.start = start
        self.length = length
    }

    public var end: Double { start + length }

    /// 最少顯示的 K 棒數：再窄就只剩一兩根，看不出走勢。
    public static let minimumBars: Double = 12
    /// 第一根實體左緣的留白（實體寬 0.65 根的一半）。
    public static let leadingPadding: Double = 0.325
    /// 最後一根右側的留白：放得下一點空白，又不會把 K 棒擠出畫面。
    public static let trailingPadding: Double = 0.6

    /// 剛好容納 `bars` 根 K 棒的視窗寬度。
    static func span(bars: Double) -> Double {
        max(bars - 1, 0) + leadingPadding + trailingPadding
    }

    /// 整張圖的範圍。
    public static func domain(barCount: Int) -> ClosedRange<Double> {
        -leadingPadding...(Double(max(barCount, 1) - 1) + trailingPadding)
    }

    /// 最近 `months` 個月實際有幾根 K 棒。依日期數而不是寫死每月根數，停牌或資料短的股票才不會多算。
    /// `dates` 須由舊到新排序。
    public static func preferredBars(dates: [Date], months: Int) -> Double {
        guard let last = dates.last, let start = TradingDay.start(months: months, before: last) else { return 0 }
        return Double(dates.filter { $0 >= start }.count)
    }

    /// 預設視窗貼齊最右邊；至少 `minimumBars` 根、最多整張圖。
    public static func initial(domain: ClosedRange<Double>, preferredBars: Double) -> ChartViewport {
        let total = domain.upperBound - domain.lowerBound
        let minimum = min(span(bars: minimumBars), total)
        let length = min(max(span(bars: preferredBars), minimum), total)
        return ChartViewport(start: domain.upperBound - length, length: length)
    }

    /// 雙指縮放：右緣固定。下限不超過手勢開始時的寬度，張開手指永遠不會讓視窗變寬。
    public static func pinched(from base: ChartViewport, magnification: Double, domain: ClosedRange<Double>) -> ChartViewport {
        guard magnification > 0 else { return base }
        let total = domain.upperBound - domain.lowerBound
        let minimum = min(span(bars: minimumBars), base.length)
        let length = min(max(base.length / magnification, minimum), total)
        return ChartViewport(start: max(domain.lowerBound, base.end - length), length: length)
    }

    /// 中心點落在視窗內的 K 棒序號；捲動時每格都會呼叫，只做算術。
    public func visibleIndices(barCount: Int) -> Range<Int> {
        guard barCount > 0, length.isFinite, start.isFinite else { return 0..<0 }
        let lower = min(max(Int(start.rounded(.up)), 0), barCount)
        let upper = min(max(Int(end.rounded(.down)) + 1, 0), barCount)
        return lower..<max(lower, upper)
    }

    /// 選取位置換成最近的 K 棒序號。
    public static func selectedIndex(_ value: Double?, barCount: Int) -> Int? {
        guard let value, value.isFinite, barCount > 0 else { return nil }
        return min(max(Int(value.rounded()), 0), barCount - 1)
    }

    /// 軸標序號：取固定倍數，捲動時同一根 K 棒的標籤不會跳動。
    public static func axisTicks(barCount: Int, visibleLength: Double, desired: Int = 4) -> [Double] {
        guard barCount > 0, desired > 0, visibleLength.isFinite else { return [] }
        let step = max(Int((visibleLength / Double(desired)).rounded(.up)), 1)
        return stride(from: 0, to: barCount, by: step).map { Double($0) }
    }

    /// 副圖 Y 軸（MACD）：依實際高低決定、一定含零軸，不再強制上下對稱。
    public static func oscillatorDomain(values: [Double]) -> ClosedRange<Double> {
        let lower = min(values.min() ?? 0, 0)
        let upper = max(values.max() ?? 0, 0)
        let margin = max((upper - lower) * 0.1, 0.0001)
        return (lower - margin)...(upper + margin)
    }
}
