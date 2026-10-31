import Foundation

/// 可捲動 K 線圖的視窗算術：整張圖的時間範圍、預設視窗與雙指縮放。
/// 抽成純函式是因為邊界組合（1M 切月 K、縮放下限）用模擬器很難逐一點到。
public struct ChartViewport: Equatable, Sendable {
    public var start: Date
    public var length: TimeInterval

    public init(start: Date, length: TimeInterval) {
        self.start = start
        self.length = length
    }

    public var end: Date { start.addingTimeInterval(length) }

    /// 最少顯示的 K 棒數：再窄就只剩一兩根，看不出走勢。
    public static let minimumBars: Double = 12

    /// 整張圖的範圍：左緣是第一根實體的左邊，右側只留 0.6 根的空白。
    /// 留白若用固定天數，月 K 會比 1M 視窗還寬，把所有 K 棒擠出畫面（Codex 審查重現過）。
    public static func domain(firstAnchor: Date, lastAnchor: Date, spanDays: Double) -> ClosedRange<Date> {
        let bar = 86_400 * spanDays
        return firstAnchor.addingTimeInterval(-bar * 0.65 / 2)...lastAnchor.addingTimeInterval(bar * 0.6)
    }

    /// 預設視窗貼齊最右邊；寬度至少 `minimumBars` 根、最多整張圖。
    public static func initial(domain: ClosedRange<Date>, preferred: TimeInterval, spanDays: Double) -> ChartViewport {
        let total = domain.upperBound.timeIntervalSince(domain.lowerBound)
        let minimum = min(86_400 * spanDays * minimumBars, total)
        let length = min(max(preferred, minimum), total)
        return ChartViewport(start: domain.upperBound.addingTimeInterval(-length), length: length)
    }

    /// 雙指縮放：右緣固定。下限不超過手勢開始時的寬度，張開手指永遠不會讓視窗變寬。
    public static func pinched(from base: ChartViewport, magnification: Double, domain: ClosedRange<Date>, spanDays: Double) -> ChartViewport {
        guard magnification > 0 else { return base }
        let total = domain.upperBound.timeIntervalSince(domain.lowerBound)
        let minimum = min(86_400 * spanDays * minimumBars, base.length)
        let length = min(max(base.length / magnification, minimum), total)
        let start = max(domain.lowerBound, base.end.addingTimeInterval(-length))
        return ChartViewport(start: start, length: length)
    }
}
