import Foundation

/// Response of `GET /api/v1/decision-signals`; only the fields the Today holding-todo card needs.
public struct DecisionSignalListResponse: Decodable, Sendable {
    public let items: [DecisionSignalSummary]
    public let total: Int

    public init(items: [DecisionSignalSummary], total: Int) {
        self.items = items
        self.total = total
    }
}

/// Mirrors `DecisionSignalItem` in api/v1/schemas/decision_signals.py (subset).
/// `isHeld`, `stopTriggered`, `lastClose` are only filled when `group_latest=true`.
public struct DecisionSignalSummary: Decodable, Sendable, Equatable {
    public let stockCode: String
    public let stockName: String?
    public let action: String
    public let actionLabel: String?
    public let isHeld: Bool?
    public let stopLoss: Double?
    public let stopTriggered: Bool?
    public let lastClose: Double?
    /// nil（舊後端或測試）視為有效；非 active 的訊號不進待辦。
    public let status: String?

    public init(stockCode: String, stockName: String? = nil, action: String, actionLabel: String? = nil,
                isHeld: Bool? = nil, stopLoss: Double? = nil, stopTriggered: Bool? = nil, lastClose: Double? = nil,
                status: String? = nil) {
        self.stockCode = stockCode
        self.stockName = stockName
        self.action = action
        self.actionLabel = actionLabel
        self.isHeld = isHeld
        self.stopLoss = stopLoss
        self.stopTriggered = stopTriggered
        self.lastClose = lastClose
        self.status = status
    }

    /// Percent move from the last close down to the stop: −2.1 means the stop is 2.1% below the close.
    /// Nil without both prices.
    public var stopDistancePercent: Double? {
        guard let stopLoss, let lastClose, lastClose > 0, stopLoss.isFinite, lastClose.isFinite else { return nil }
        return (stopLoss - lastClose) / lastClose * 100
    }
}

public struct HoldingTodoItem: Equatable, Sendable, Identifiable {
    public enum Kind: Int, Comparable, Sendable {
        /// Ordered by urgency: the raw value is the sort rank.
        case stopTriggered = 0, nearStop = 1, reduceOrSell = 2

        public static func < (lhs: Kind, rhs: Kind) -> Bool { lhs.rawValue < rhs.rawValue }
    }

    public let signal: DecisionSignalSummary
    public let kind: Kind

    public var id: String { signal.stockCode }
    public var code: String { signal.stockCode }
    public var titles: StockRowTitles { StockRowTitles(code: signal.stockCode, name: signal.stockName) }

    /// Amber for anything at or within the near-stop band.
    public var isStopWarning: Bool { kind != .reduceOrSell }

    /// 「已跌破 72.0」「離停損 −2.1%」; nil when the signal has no usable stop reading.
    public var stopText: String? {
        if signal.stopTriggered == true {
            guard let stop = signal.stopLoss else { return "已跌破停損" }
            return "已跌破 \(DisplayNumber.number(stop, digits: 2))"
        }
        guard let distance = signal.stopDistancePercent else { return nil }
        return "離停損 \(DisplayNumber.percent(distance, digits: 1))"
    }
}

public struct HoldingTodoList: Equatable, Sendable {
    /// At most `HoldingTodo.visibleLimit` rows, most urgent first.
    public let items: [HoldingTodoItem]
    /// Number of todos before truncation.
    public let total: Int
    /// Held stocks with a signal (the response total), for the「全部 N 檔」link.
    public let signalTotal: Int

    public init(items: [HoldingTodoItem], total: Int, signalTotal: Int) {
        self.items = items
        self.total = total
        self.signalTotal = signalTotal
    }
}

public enum HoldingTodo {
    public static let visibleLimit = 3
    /// A close within this many percent above the stop counts as near-stop.
    public static let nearStopPercent = 3.0

    static func isWithinNearStop(_ signal: DecisionSignalSummary) -> Bool {
        guard let distance = signal.stopDistancePercent else { return false }
        return distance <= 0 && distance >= -nearStopPercent
    }

    public static func kind(of signal: DecisionSignalSummary) -> HoldingTodoItem.Kind? {
        if signal.stopTriggered == true { return .stopTriggered }
        if isWithinNearStop(signal) { return .nearStop }
        switch DecisionAction.resolve(action: signal.action, label: signal.actionLabel) {
        case .reduce?, .sell?: return .reduceOrSell
        default: return nil
        }
    }

    /// Stop triggered → near stop (closest first) → reduce / sell; server order breaks ties.
    public static func build(items: [DecisionSignalSummary], signalTotal: Int? = nil) -> HoldingTodoList {
        let ranked = items.enumerated().compactMap { offset, signal -> (Int, HoldingTodoItem)? in
            // The endpoint is called with holding_only; an explicit false still means not held.
            guard signal.isHeld != false, signal.status == nil || signal.status == "active",
                  let kind = kind(of: signal) else { return nil }
            return (offset, HoldingTodoItem(signal: signal, kind: kind))
        }
        let sorted = ranked.sorted { lhs, rhs in
            let (left, right) = (lhs.1, rhs.1)
            if left.kind != right.kind { return left.kind < right.kind }
            if left.kind == .nearStop,
               let a = left.signal.stopDistancePercent, let b = right.signal.stopDistancePercent, a != b {
                // Closer to zero (less room left) first.
                return a > b
            }
            return lhs.0 < rhs.0
        }.map(\.1)
        return HoldingTodoList(items: Array(sorted.prefix(visibleLimit)), total: sorted.count,
                               signalTotal: signalTotal ?? items.count)
    }
}
