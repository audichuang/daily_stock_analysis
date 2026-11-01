import Foundation

/// 個股頁的內容分頁。美股沒有籌碼，沒報告就沒有新聞可看，缺資料的分頁直接不出現。
public enum StockDetailTab: String, CaseIterable, Identifiable, Sendable {
    case ai, chips, financials, news

    public var id: String { rawValue }

    public var title: String {
        switch self {
        case .ai: return "AI"
        case .chips: return "籌碼"
        case .financials: return "財務"
        case .news: return "新聞"
        }
    }

    public static func available(market: String, hasChips: Bool, hasReport: Bool) -> [StockDetailTab] {
        allCases.filter { tab in
            switch tab {
            case .ai: return true
            case .chips: return hasChips
            case .financials: return ["tw", "us"].contains(market.lowercased())
            case .news: return hasReport
            }
        }
    }
}

/// 個股頁首的上下檔切換；清單裡沒有這檔就不提供。
public enum StockNeighbors {
    public static func of(_ code: String, in list: [String]) -> (previous: String?, next: String?) {
        guard let index = list.firstIndex(of: code) else { return (nil, nil) }
        return (index > 0 ? list[index - 1] : nil, index + 1 < list.count ? list[index + 1] : nil)
    }
}

public enum StockSessionLabel {
    /// 未知值不顯示，不猜開收盤。
    public static func text(_ phase: String?) -> String? {
        switch phase {
        case "premarket": return "未開盤"
        case "intraday": return "盤中"
        case "lunch_break": return "午休"
        case "closing_auction": return "收盤競價"
        case "postmarket": return "已收盤"
        case "non_trading": return "休市"
        default: return nil
        }
    }
}

public extension DisplayNumber {
    /// 成交量、成交值這類大數字：萬、億為單位，放得進四欄的窄格。
    static func compact(_ value: Double?) -> String {
        guard let value, value.isFinite else { return noValue }
        let magnitude = abs(value)
        if magnitude >= 100_000_000 { return number(value / 100_000_000) + " 億" }
        if magnitude >= 10_000 { return number(value / 10_000) + " 萬" }
        return number(value, digits: 0)
    }
}

/// 報告價位。只有 sniper_prices_source 為 structured 才有數字；legacy 與舊後端保留原文，不解析句子。
public struct PriceLevel: Identifiable, Equatable, Sendable {
    public enum Kind: String, CaseIterable, Sendable {
        case stopLoss, secondaryBuy, idealBuy, takeProfit

        public var title: String {
            switch self {
            case .stopLoss: return "停損"
            case .secondaryBuy: return "次要進場"
            case .idealBuy: return "理想進場"
            case .takeProfit: return "停利"
            }
        }
    }

    public var id: String { kind.rawValue }
    public let kind: Kind
    public let value: Double?
    public let text: String?

    public static func levels(from strategy: ReportStrategy) -> [PriceLevel] {
        let sniper = strategy.sniperPricesSource == "structured" ? strategy.sniperPrices : nil
        return Kind.allCases.map { kind in
            let source = fields(kind, strategy: strategy, sniper: sniper)
            var usable: Double?
            if let number = source.value, number.isFinite, number > 0 { usable = number }
            let trimmed = source.text?.trimmingCharacters(in: .whitespacesAndNewlines)
            return PriceLevel(kind: kind, value: usable, text: trimmed?.isEmpty == false ? trimmed : nil)
        }
    }

    private static func fields(_ kind: Kind, strategy: ReportStrategy, sniper: SniperPrices?) -> (value: Double?, text: String?) {
        switch kind {
        case .stopLoss: return (sniper?.stopLoss, strategy.stopLoss)
        case .secondaryBuy: return (sniper?.secondaryBuy, strategy.secondaryBuy)
        case .idealBuy: return (sniper?.idealBuy, strategy.idealBuy)
        case .takeProfit: return (sniper?.takeProfit, strategy.takeProfit)
        }
    }
}

/// 價位尺的範圍。至少要兩個不同價位才有比例可言。
public struct PriceRuler: Equatable, Sendable {
    public let lower: Double
    public let upper: Double

    public init?(values: [Double?]) {
        let known = values.compactMap { $0 }.filter { $0.isFinite && $0 > 0 }
        guard let lower = known.min(), let upper = known.max(), upper > lower else { return nil }
        self.lower = lower
        self.upper = upper
    }

    public func fraction(_ value: Double) -> Double {
        min(1, max(0, (value - lower) / (upper - lower)))
    }
}

public enum ReportMath {
    /// from 到 to 的變動百分比；基準缺或非正值回 nil，不顯示假的 0%。
    public static func changePercent(from: Double?, to: Double?) -> Double? {
        guard let from, let to, from.isFinite, to.isFinite, from > 0 else { return nil }
        return (to - from) / from * 100
    }
}

public enum ReportText {
    /// 大盤複盤標題跟著報告自己的名稱（台股／美股），沒有名稱才用不分市場的通稱。
    public static func marketReviewTitle(stockName: String?) -> String {
        firstNonEmpty(stockName) ?? "大盤複盤"
    }

    /// 依序取第一個非空字串；結論列的「一句話 → 摘要」都走這裡。
    public static func firstNonEmpty(_ candidates: String?...) -> String? {
        for candidate in candidates {
            if let text = candidate?.trimmingCharacters(in: .whitespacesAndNewlines), !text.isEmpty { return text }
        }
        return nil
    }
}

/// 證據依來源分組；順序與文字同 Web EvidenceSection，context（輸入資料區塊）放最後。
public struct EvidenceGroup: Identifiable, Sendable {
    public let key: String
    public let title: String
    public let items: [ResearchEvidence]
    public var id: String { key }

    private static let order = ["sec_filing", "ratings", "short_interest", "insider", "estimates", "ownership",
                                "capital_flow", "news", "fundamental", "market", "technical", "context", "other"]
    private static let titles = [
        "sec_filing": "SEC 公告", "ratings": "評等", "short_interest": "放空", "insider": "內部人交易",
        "estimates": "法人預估", "ownership": "持股結構", "capital_flow": "資金流", "news": "新聞",
        "fundamental": "基本面", "market": "市場結構", "technical": "技術面", "context": "輸入資料", "other": "其他"
    ]
    // 舊報告沒有 group，退回 source_type。
    private static let sourceTypeGroups = ["analysis_context": "context", "market_structure": "market"]

    public static func groups(_ evidence: [ResearchEvidence]) -> [EvidenceGroup] {
        var buckets: [String: [ResearchEvidence]] = [:]
        for item in evidence {
            let raw = item.group ?? sourceTypeGroups[item.sourceType] ?? item.sourceType
            buckets[titles[raw] == nil ? "other" : raw, default: []].append(item)
        }
        return order.compactMap { key in
            buckets[key].map { EvidenceGroup(key: key, title: titles[key] ?? key, items: $0) }
        }
    }
}

/// 這份報告缺什麼；語意同 Web utils/reportGaps.ts，全部讀結構化欄位。
public struct ReportGaps: Equatable, Sendable {
    public let items: [String]
    /// 資料品質等級為 limited／poor 時才提示結論可能不完整。
    public let incomplete: Bool

    // 解碼時 source_status 的鍵已被轉成駝峰，比對前統一成小寫無底線。
    private static let sourceLabels = ["secfinra": "SEC／FINRA", "insider": "內部人交易", "ratings": "評等",
                                       "estimates": "法人預估", "futu": "富途資金流"]
    // not_configured、not_supported 是本來就沒有，不算缺。
    private static let missingStatuses: Set<String> = ["no_data", "fetch_failed", "timeout"]

    public static func of(_ artifact: ResearchArtifact?) -> ReportGaps {
        guard let artifact else { return ReportGaps(items: [], incomplete: false) }
        let blocks = artifact.dataQuality.missingBlocks.map { key in
            artifact.evidence.first { $0.id == "context:\(key)" }?.title ?? key
        }
        let sources = (artifact.sourceStatus ?? [:])
            .filter { missingStatuses.contains($0.value) }
            .keys.sorted()
            .map { sourceLabels[$0.replacingOccurrences(of: "_", with: "").lowercased()] ?? $0 }
        let level = artifact.dataQuality.level
        return ReportGaps(items: blocks + sources, incomplete: level == "limited" || level == "poor")
    }
}

/// Display lines for one invalidation card: at most one condition line plus one detail line.
/// Trigger and threshold are dropped when they only repeat the description (models often fill all three alike).
public enum InvalidationDisplay {
    /// Known metric keys; unknown keys are never shown raw.
    public static let metricLabels = ["price": "價位", "volume": "成交量", "pe": "本益比", "rsi": "RSI"]

    public static func metricLabel(_ metric: String?) -> String? {
        guard let key = metric?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased(), !key.isEmpty else { return nil }
        return metricLabels[key]
    }

    public static func lines(description: String, trigger: String?, threshold: String?, metric: String?) -> (primary: String, detail: String?) {
        let desc = description.trimmingCharacters(in: .whitespacesAndNewlines)
        let rawTrigger = trigger?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let rawThreshold = threshold?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""

        // An empty description promotes the trigger to the condition line.
        let primary = desc.isEmpty ? rawTrigger : desc
        let keptTrigger = (rawTrigger.isEmpty || primary.contains(rawTrigger)) ? nil : rawTrigger
        let keptThreshold = (rawThreshold.isEmpty || primary.contains(rawThreshold) || (!rawTrigger.isEmpty && rawTrigger.contains(rawThreshold)))
            ? nil : rawThreshold

        var parts: [String] = []
        if let keptTrigger { parts.append("觸發：\(keptTrigger)") }
        if let keptThreshold {
            if let label = metricLabel(metric) { parts.append("\(label)：\(keptThreshold)") } else { parts.append(keptThreshold) }
        }
        return (primary, parts.isEmpty ? nil : parts.joined(separator: " · "))
    }
}
