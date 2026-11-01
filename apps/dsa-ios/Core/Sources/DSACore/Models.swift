import Foundation

public struct AuthStatus: Codable, Sendable {
    public let authEnabled: Bool
    public let loggedIn: Bool
    public let passwordSet: Bool
    public let passwordChangeable: Bool?
    public let setupState: String?
}

public struct StockQuote: Codable, Sendable, Identifiable {
    public var id: String { stockCode }
    public let stockCode: String
    public let stockName: String?
    public let currentPrice: Double
    public let change: Double?
    public let changePercent: Double?
    public let open: Double?
    public let high: Double?
    public let low: Double?
    public let prevClose: Double?
    public let volume: Double?
    public let amount: Double?
    public let volumeRatio: Double?
    public let averagePrice: Double?
    public let limitUp: Double?
    public let limitDown: Double?
    public let bestBid: Double?
    public let bestAsk: Double?
    public let bestBidVolume: Int?
    public let bestAskVolume: Int?
    public let updateTime: String?
    public let source: String?
    /// 穩定的來源代碼（shioaji／yfinance）；舊後端沒有。
    public let sourceCode: String?
    public let asOf: String?
    public let isStale: Bool?
}

public struct QuoteItem: Codable, Sendable, Identifiable {
    public var id: String { stockCode }
    public let stockCode: String
    public let quote: StockQuote?
    public let error: String?
}

public struct MarketIndex: Codable, Sendable, Identifiable {
    public var id: String { code }
    public let code: String
    public let name: String
    public let current: Double?
    public let change: Double?
    public let changePct: Double?
    public let source: String?
    public let sourceCode: String?
    public let asOf: String?
}

/// `GET /stocks/indices` 的完整回應；市場狀態在頂層，舊後端沒有這兩欄。
public struct MarketIndicesSnapshot: Codable, Sendable {
    public let items: [MarketIndex]
    public let marketPhase: String?
    public let marketOpen: Bool?
}

public struct KLineBar: Codable, Sendable, Identifiable {
    public var id: String { date }
    public let date: String
    public let open: Double
    public let high: Double
    public let low: Double
    public let close: Double
    public let volume: Double?
    public let amount: Double?
    public let changePercent: Double?
    /// 日 K 來源還沒收錄、由即時報價補上的當日暫定 K；舊後端不送此欄。
    public let provisional: Bool?
}

public struct StockProfile: Codable, Sendable {
    public let requestedCode: String
    public let canonicalCode: String
    public let market: String
    public let asOf: String
    public let quote: QuoteBlock
    public let history: HistoryBlock
    public let research: ResearchBlock
    public let evidenceQuality: EvidenceQuality
    // I09／I10：B17c 追加區塊，沒持有、美股或舊後端都是 nil。
    public let position: StockProfilePosition?
    public let chips: StockProfileChips?
    public let news: [StockProfileNewsItem]?
    public let portfolio: StockProfilePortfolioBlock?

    /// true＝持有、false＝確定沒持有、nil＝查不到或舊後端；持股重播失敗時 position 也是 nil，不能當成空手。
    public var holdingKnown: Bool? {
        if position != nil { return true }
        guard let portfolio, portfolio.status != "unavailable" else { return nil }
        return portfolio.data?.held
    }
}

public struct QuoteBlock: Codable, Sendable {
    public let status: String
    public let data: StockQuote?
    public let limitations: [String]
}

public struct HistoryBlock: Codable, Sendable {
    public let status: String
    public let period: String
    public let data: [KLineBar]
    public let limitations: [String]
}

public struct ResearchBlock: Codable, Sendable {
    public let status: String
    public let data: ResearchData
    public let limitations: [String]
}

public struct ResearchData: Codable, Sendable {
    public let latestReport: HistoryItem?
    public let recentReports: [HistoryItem]
    public let structuredReport: ResearchArtifact?
    public let eventOutlook: EventOutlook?
}

public struct EvidenceQuality: Codable, Sendable {
    public let status: String
    public let blocks: [String: String]
    public let limitations: [String]
}

public struct ResearchArtifact: Codable, Sendable, Identifiable {
    public var id: String { artifactId }
    public let schemaVersion: String
    public let artifactId: String
    public let sourceReportId: Int?
    public let sourceQueryId: String?
    public let createdAt: String?
    public let subject: ResearchSubject
    public let thesis: ResearchThesis
    public let evidence: [ResearchEvidence]
    public let invalidationConditions: [InvalidationCondition]
    public let nextActions: [ResearchNextAction]
    public let dataQuality: ResearchQuality
    public let eventGap: ResearchEventGap?
    /// 鍵會被 convertFromSnakeCase 轉成駝峰（sec_finra → secFinra），查表前要走 ReportGaps。
    public let sourceStatus: [String: String]?
}

public struct ResearchSubject: Codable, Sendable {
    public let stockCode: String
    public let stockName: String?
    public let market: String?
}

public struct ResearchThesis: Codable, Sendable {
    public let direction: String
    public let summary: String
    public let confidence: Double?
    public let score: Int?
    public let horizon: String?
    public let action: String?
    public let actionLabel: String?
    public let reasons: [String]
    public let risks: [String]
    // B03：決策欄位，舊報告為 nil。
    public let oneSentence: String?
    public let timeSensitivity: String?
    public let positionAdvice: ReportPositionAdvice?
    public let confidenceLevel: String?
    public let confidenceReason: String?
    public let guardrailApplied: Bool?
    public let guardrailReason: String?
    public let strongestBullishSignal: String?
    public let strongestBearishSignal: String?
    public let watchConditions: [String]?
    public let entryConditions: [String]?
    public let exitTriggers: [String]?
    public let pendingEvents: [String]?
    public let nextCheckTime: String?
}

public struct ResearchEvidence: Codable, Sendable, Identifiable {
    public let id: String
    public let sourceType: String
    public let title: String
    public let summary: String?
    public let source: String?
    public let freshness: String
    public let qualityLevel: String
    public let asOf: String?
    public let url: String?
    // B03：畫面分組與時間語意，舊報告為 nil。
    public let group: String?
    public let observedAt: String?
    public let fetchedAt: String?
    public let windowDays: Int?
    public let complete: Bool?
    public let countsTowardScore: Bool?
    public let excerpt: String?
}

public struct InvalidationCondition: Codable, Sendable, Identifiable {
    public let id: String
    public let category: String
    public let description: String
    public let trigger: String?
    public let severity: String
    public let metric: String?
    public let threshold: String?
    public let dueAt: String?
    public let direction: String?
    /// triggered 只由分析當下的事實設定；其餘為 pending 或 review。
    public let status: String?
}

public struct ResearchNextAction: Codable, Sendable {
    public let action: String
    public let label: String
    public let reason: String?
    public let dueAt: String?
}

public struct ResearchQuality: Codable, Sendable {
    public let level: String
    public let overallScore: Int?
    public let sourceCount: Int
    public let staleCount: Int
    public let missingBlocks: [String]
    public let limitations: [String]
}

public struct HistoryPage: Codable, Sendable {
    public let total: Int
    public let page: Int
    public let limit: Int
    public let items: [HistoryItem]
}

public struct HistoryItem: Codable, Sendable, Identifiable {
    public let id: Int?
    public let queryId: String
    public let stockCode: String
    public let stockName: String?
    public let reportType: String?
    public let region: String?
    public let trendPrediction: String?
    public let analysisSummary: String?
    public let sentimentScore: Int?
    public let operationAdvice: String?
    public let action: String?
    public let actionLabel: String?
    public let currentPrice: Double?
    public let changePct: Double?
    public let modelUsed: String?
    public let createdAt: String?
    public let assetType: String?
    /// 一句話結論（B06）；大盤複盤與舊報告為 nil。
    public let oneSentence: String?
}

public struct AnalysisReport: Codable, Sendable {
    public let meta: ReportMeta
    public let summary: ReportSummary
    public let strategy: ReportStrategy?
    public let structuredReport: ResearchArtifact?
    public let eventOutlook: EventOutlook?
    /// 大盤複盤的結構化內容，位於 `details.context_snapshot.market_review_payload`；個股報告與舊後端為 nil。
    public let marketReviewPayload: MarketReviewPayload?

    private enum CodingKeys: String, CodingKey {
        case meta, summary, strategy, structuredReport, eventOutlook, details
    }

    private enum NestedKeys: String, CodingKey {
        case contextSnapshot, marketReviewPayload
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        meta = try container.decode(ReportMeta.self, forKey: .meta)
        summary = try container.decode(ReportSummary.self, forKey: .summary)
        strategy = try container.decodeIfPresent(ReportStrategy.self, forKey: .strategy)
        structuredReport = try container.decodeIfPresent(ResearchArtifact.self, forKey: .structuredReport)
        eventOutlook = try container.decodeIfPresent(EventOutlook.self, forKey: .eventOutlook)
        // context_snapshot is untyped on the backend (may be a plain string); a bad shape must not fail the whole report.
        let details = try? container.nestedContainer(keyedBy: NestedKeys.self, forKey: .details)
        let snapshot = try? details?.nestedContainer(keyedBy: NestedKeys.self, forKey: .contextSnapshot)
        marketReviewPayload = try? snapshot?.decodeIfPresent(MarketReviewPayload.self, forKey: .marketReviewPayload)
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(meta, forKey: .meta)
        try container.encode(summary, forKey: .summary)
        try container.encodeIfPresent(strategy, forKey: .strategy)
        try container.encodeIfPresent(structuredReport, forKey: .structuredReport)
        try container.encodeIfPresent(eventOutlook, forKey: .eventOutlook)
        if let marketReviewPayload {
            var details = container.nestedContainer(keyedBy: NestedKeys.self, forKey: .details)
            var snapshot = details.nestedContainer(keyedBy: NestedKeys.self, forKey: .contextSnapshot)
            try snapshot.encode(marketReviewPayload, forKey: .marketReviewPayload)
        }
    }
}

/// 只鏡像今日頁盤勢卡要用的欄位：market_light 與 next_day_plan；多市場複盤放在 markets[region]。
public struct MarketReviewPayload: Codable, Sendable, Equatable {
    public let marketLight: MarketReviewLight?
    public let nextDayPlan: MarketReviewNextDayPlan?
    public let markets: [String: MarketReviewPayload]?

    public init(marketLight: MarketReviewLight? = nil, nextDayPlan: MarketReviewNextDayPlan? = nil, markets: [String: MarketReviewPayload]? = nil) {
        self.marketLight = marketLight
        self.nextDayPlan = nextDayPlan
        self.markets = markets
    }

    /// 合併複盤（region = "tw,us"）時取該市場的子 payload；單一市場直接用自己。
    public func resolved(for region: String) -> MarketReviewPayload {
        markets?[region] ?? self
    }
}

public struct MarketReviewLight: Codable, Sendable, Equatable {
    public let status: String?
    public let label: String?
    public let guidance: String?

    public init(status: String?, label: String? = nil, guidance: String? = nil) {
        self.status = status
        self.label = label
        self.guidance = guidance
    }
}

public struct MarketReviewKeyLevel: Codable, Sendable, Equatable {
    public let label: String
    public let price: Double
}

public struct MarketReviewNextDayPlan: Codable, Sendable, Equatable {
    public let stance: String?
    public let summary: String?
    public let keyLevels: [MarketReviewKeyLevel]?

    public init(stance: String?, summary: String? = nil, keyLevels: [MarketReviewKeyLevel]? = nil) {
        self.stance = stance
        self.summary = summary
        self.keyLevels = keyLevels
    }
}

/// 今日頁盤勢卡的三行文字；沒有 payload 時退回列表摘要。
public struct MarketReviewCardText: Equatable, Sendable {
    public enum Light: String, Sendable { case green, yellow, red }
    public enum Stance: String, Sendable { case offensive, balanced, defensive }

    public let light: Light?
    public let stance: Stance?
    public let date: String?
    public let line: String
    public let keyLevels: String?

    public var lightText: String? {
        switch light {
        case .green: return "綠燈"
        case .yellow: return "黃燈"
        case .red: return "紅燈"
        case nil: return nil
        }
    }

    public var stanceText: String? {
        switch stance {
        case .offensive: return "進攻"
        case .balanced: return "平衡"
        case .defensive: return "防守"
        case nil: return nil
        }
    }

    public static let placeholder = "今日複盤已產生，點開查看"

    public static func make(payload: MarketReviewPayload?, title: String?, summary: String?, oneSentence: String?, createdAt: String?) -> MarketReviewCardText {
        let light = payload?.marketLight?.status.flatMap { Light(rawValue: $0.lowercased()) }
        let stance = payload?.nextDayPlan?.stance.flatMap { Stance(rawValue: $0.lowercased()) }
        let structured = [payload?.marketLight?.guidance, payload?.nextDayPlan?.summary]
            .compactMap { $0?.trimmingCharacters(in: .whitespacesAndNewlines) }
            .first { !$0.isEmpty }
        let levels = (payload?.nextDayPlan?.keyLevels ?? []).map(\.price).filter(\.isFinite)
        let levelText = levels.isEmpty ? nil : "關鍵價 " + levels.map(formatLevel).joined(separator: " / ")
        return MarketReviewCardText(light: light, stance: stance, date: shortDate(createdAt),
                                    line: structured ?? fallbackLine(title: title, summary: summary, oneSentence: oneSentence),
                                    keyLevels: levelText)
    }

    /// 摘要只是標題、或太短且沒有標點（像「台股大盤複盤」）時，不當作一句話。
    static func fallbackLine(title: String?, summary: String?, oneSentence: String?) -> String {
        let text = summary?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let heading = title?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let hasPunctuation = text.unicodeScalars.contains { CharacterSet.punctuationCharacters.contains($0) }
        let usable = !text.isEmpty && text != heading && !(text.count < 12 && !hasPunctuation)
        if usable { return text }
        let sentence = oneSentence?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return sentence.isEmpty ? placeholder : sentence
    }

    /// "2026-10-30T18:00:00" → "10/30"; keeps the backend's own date, no timezone conversion.
    static func shortDate(_ value: String?) -> String? {
        guard let value, value.count >= 10 else { return nil }
        let parts = value.prefix(10).split(whereSeparator: { $0 == "-" || $0 == "/" })
        guard parts.count == 3, let month = Int(parts[1]), let day = Int(parts[2]) else { return nil }
        return "\(month)/\(day)"
    }

    private static func formatLevel(_ price: Double) -> String {
        price.formatted(.number.locale(Locale(identifier: "zh_TW")).precision(.fractionLength(0...2)))
    }
}

public struct EventConsensus: Codable, Sendable {
    public let eps: Double?
    public let revenue: Double?
    public let analysts: Int?
    public let epsCurrency: String?
    public let revenueCurrency: String?
}

public struct EventScenario: Codable, Sendable {
    public let `case`: String
    public let expectedReaction: String?
    public let actionIfHolding: String?
    public let actionIfFlat: String?
}

/// 事件展望；列舉欄位用字串，舊 App 遇到新值才不會整份報告解碼失敗。
public struct EventOutlook: Codable, Sendable {
    public let event: String?
    public let eventType: String?
    public let eventDate: String?
    public let consensus: EventConsensus?
    public let trackRecord: String?
    public let revisionTrend: String?
    public let expectation: String?
    public let confidence: String?
    public let reasoning: String?
    public let scenarios: [EventScenario]?
    public let newsImpact: String?
    public let verifyAfter: String?

    /// 最重要的判斷放最前面；未知值當資料不足，不猜。
    public var expectationLabel: String {
        switch expectation {
        case "beat": return "判斷：超預期"
        case "inline": return "判斷：符合預期"
        case "miss": return "判斷：不及預期"
        default: return "資料不足，不判斷"
        }
    }

    public var confidenceLabel: String? {
        switch confidence {
        case "high": return "把握度高"
        case "medium": return "把握度中"
        case "low": return "把握度低"
        default: return nil
        }
    }

    public static func caseLabel(_ value: String) -> String {
        switch value {
        case "beat": return "如果超預期"
        case "inline": return "如果符合"
        case "miss": return "如果不及"
        default: return value
        }
    }

    /// 營收以「億」顯示，貼近使用者口語（1090 億）。
    public var consensusSummary: String? {
        guard let consensus else { return nil }
        var parts: [String] = []
        let unit: (String?) -> String = { $0.map { " \($0)" } ?? "" }
        if let eps = consensus.eps { parts.append("EPS \(String(format: "%.2f", eps))\(unit(consensus.epsCurrency))") }
        if let revenue = consensus.revenue { parts.append("營收 \(String(format: "%.0f", revenue / 100_000_000)) 億\(unit(consensus.revenueCurrency))") }
        if let analysts = consensus.analysts { parts.append("\(analysts) 位分析師") }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }
}

public struct ReportMeta: Codable, Sendable {
    public let id: Int?
    public let queryId: String
    public let stockCode: String
    public let stockName: String?
    public let reportType: String?
    public let reportLanguage: String?
    public let createdAt: String?
    public let currentPrice: Double?
    public let changePct: Double?
    public let modelUsed: String?
    public let assetType: String?
    // B02：查不到都是 nil。
    public let priceDate: String?
    public let priceFetchedAt: String?
    public let currency: String?
    public let changeAmount: Double?
    public let previousReport: ReportPreviousSummary?
    /// nil 代表無法判定，不得當成未持有。
    public let held: Bool?
}

public struct ReportSummary: Codable, Sendable {
    public let analysisSummary: String?
    public let operationAdvice: String?
    public let action: String?
    public let actionLabel: String?
    public let trendPrediction: String?
    public let sentimentScore: Int?
    public let sentimentLabel: String?
    // B02：決策欄位，舊報告為 nil。觀察條件讀 phaseWatchConditions。
    public let oneSentence: String?
    public let timeSensitivity: String?
    public let positionAdvice: ReportPositionAdvice?
    public let confidenceLevel: String?
    public let confidenceReason: String?
    public let guardrailApplied: Bool?
    public let guardrailReason: String?
    public let strongestBullishSignal: String?
    public let strongestBearishSignal: String?
    public let phaseWatchConditions: [String]?
    public let entryConditions: [String]?
    public let exitTriggers: [String]?
    public let pendingEvents: [String]?
    public let nextCheckTime: String?
}

public struct ReportStrategy: Codable, Sendable {
    public let idealBuy: String?
    public let secondaryBuy: String?
    public let stopLoss: String?
    public let takeProfit: String?
    /// 模型給的結構化價位；只有 sniperPricesSource 為 structured 才可當數字用。
    public let sniperPrices: SniperPrices?
    /// structured 或 legacy；legacy 與舊後端一律顯示上面四個原文欄位。
    public let sniperPricesSource: String?
}

public struct AcceptedTask: Codable, Sendable {
    public let taskId: String
    public let traceId: String?
    public let status: String
    public let message: String?
    public let analysisPhase: String?
}

public struct AnalysisTask: Codable, Sendable {
    public let taskId: String
    public let status: String
    public let progress: Int?
    public let result: AnalysisResult?
    public let marketReviewReport: String?
    public let error: String?
    public let stockName: String?
}

public struct AnalysisResult: Codable, Sendable {
    public let queryId: String
    public let stockCode: String
    public let stockName: String?
    public let report: AnalysisReport?
    public let createdAt: String
}

public struct PortfolioSnapshot: Codable, Sendable {
    public let asOf: String
    public let costMethod: String
    public let currency: String
    public let accountCount: Int
    public let totalCash: Double
    public let totalMarketValue: Double
    public let totalEquity: Double
    public let realizedPnl: Double
    public let unrealizedPnl: Double
    public let fxStale: Bool
    public let fxMissing: Bool?
    public let dataQuality: String
    public let limitations: [String]
    public let accounts: [PortfolioAccount]
    // 以下皆為追加欄位；頂層 total_* 仍是 CNY 彙總，帶 display_currency 才有 consolidated_*。
    public let dayPnl: Double?
    public let funds: PortfolioFundsBlock?
    public let displayCurrency: String?
    public let consolidatedEquityBase: Double?
    public let consolidatedMarketValueBase: Double?
    public let consolidatedCashBase: Double?
    public let consolidatedUnrealizedPnlBase: Double?
    public let consolidatedRealizedPnlBase: Double?
    public let consolidatedDayPnlBase: Double?
    public let consolidatedFundValueBase: Double?
    public let consolidatedFundDayPnlBase: Double?
    public let consolidatedFxStale: Bool?
    public let consolidatedFxMissing: Bool?
}

public struct PortfolioAccount: Codable, Sendable, Identifiable {
    public var id: Int { accountId }
    public let accountId: Int
    public let accountName: String
    public let market: String
    public let baseCurrency: String
    public let totalCash: Double
    public let totalMarketValue: Double
    public let totalEquity: Double
    public let realizedPnl: Double
    public let unrealizedPnl: Double
    public let fxStale: Bool?
    public let fxMissing: Bool?
    public let dataQuality: String
    public let limitations: [String]
    public let positions: [PortfolioPosition]
    /// 今日損益（帳戶幣別，追加欄位）；有一檔算不出就是 null。
    public let dayPnl: Double?
}

public struct PortfolioPosition: Codable, Sendable, Identifiable {
    public var id: String { market + ":" + symbol }
    public let symbol: String
    public let name: String?
    public let market: String
    public let currency: String
    public let quantity: Double
    public let avgCost: Double
    public let totalCost: Double
    public let lastPrice: Double
    public let marketValueBase: Double
    public let unrealizedPnlBase: Double
    public let unrealizedPnlPct: Double?
    public let valuationCurrency: String?
    public let priceSource: String
    public let priceProvider: String?
    public let priceDate: String?
    public let priceStale: Bool
    public let priceAvailable: Bool
    public let dataQuality: String
    public let limitations: [String]
    // 追加欄位；查無前一場收盤時為 null。
    public let quoteAt: String?
    public let prevClose: Double?
    public let dayChangePct: Double?
    public let dayPnlBase: Double?
}

/// `GET /portfolio/risk`；後端這兩個區塊是自由字典，全部可空，缺欄位不能讓整份解碼失敗。
public struct PortfolioRiskReport: Codable, Sendable {
    public let currency: String?
    public let concentration: PortfolioConcentration?
    public let sectorConcentration: PortfolioSectorConcentration?
    public let displayCurrency: String?
}

public struct PortfolioConcentration: Codable, Sendable {
    public let topWeightPct: Double?
    public let alert: Bool?
    public let topPositions: [PortfolioRiskPosition]?
}

public struct PortfolioRiskPosition: Codable, Sendable {
    public let symbol: String
    public let weightPct: Double?
    public let isAlert: Bool?
}

public struct PortfolioSectorConcentration: Codable, Sendable {
    public let topWeightPct: Double?
    public let alert: Bool?
    public let topSectors: [PortfolioRiskSector]?
}

public struct PortfolioRiskSector: Codable, Sendable {
    public let sector: String
    public let weightPct: Double?
    public let symbolCount: Int?
    public let isAlert: Bool?
}

public struct StockIndexItem: Codable, Sendable, Identifiable {
    public var id: String { canonicalCode }
    public let canonicalCode: String
    public let displayCode: String
    public let nameZh: String
    public let aliases: [String]
    public let market: String
    public let assetType: String
    public let active: Bool
    public let popularity: Double?

    private enum CodingKeys: String, CodingKey {
        case canonicalCode, displayCode, nameZh, aliases, market, assetType, active, popularity
    }

    public init(from decoder: Decoder) throws {
        if var tuple = try? decoder.unkeyedContainer() {
            canonicalCode = try tuple.decode(String.self)
            displayCode = try tuple.decode(String.self)
            nameZh = try tuple.decode(String.self)
            _ = try tuple.decodeIfPresent(String.self)
            _ = try tuple.decodeIfPresent(String.self)
            aliases = try tuple.decode([String].self)
            market = try tuple.decode(String.self)
            assetType = try tuple.decode(String.self)
            active = try tuple.decode(Bool.self)
            popularity = tuple.isAtEnd ? nil : try tuple.decodeIfPresent(Double.self)
        } else {
            let object = try decoder.container(keyedBy: CodingKeys.self)
            canonicalCode = try object.decode(String.self, forKey: .canonicalCode)
            displayCode = try object.decode(String.self, forKey: .displayCode)
            nameZh = try object.decode(String.self, forKey: .nameZh)
            aliases = try object.decodeIfPresent([String].self, forKey: .aliases) ?? []
            market = try object.decode(String.self, forKey: .market)
            assetType = try object.decode(String.self, forKey: .assetType)
            active = try object.decode(Bool.self, forKey: .active)
            popularity = try object.decodeIfPresent(Double.self, forKey: .popularity)
        }
    }
}


public struct CalendarEvent: Codable, Sendable, Identifiable {
    public let id: String
    public let type: String
    public let code: String?
    public let name: String
    /// 來源市場的日期字串；不得先轉成裝置當地 timestamp。
    public let date: String
    public let status: String
    public let detail: String
    public let sourceUrl: String
    public let timezone: String
    public let dateKind: String
    public let updatedAt: String?

    public var isStatutoryDeadline: Bool { dateKind == "statutory_deadline" }
    public var isCompanyEvent: Bool { type == "earnings" || type == "investor_conference" }
    public var statusLabel: String { isStatutoryDeadline ? "法定期限" : status == "estimated" ? "推估" : "已確認" }
    /// 只有美股要註明日期以美東為準；台股就是使用者的當地日期，不標地點。
    public var timezoneLabel: String { timezone == "America/New_York" ? "美東" : "" }

    /// Date block labels from the source-market date: ("11/3", "週二").
    public var dayBlock: (day: String, weekday: String)? {
        guard let parsed = EventCalendarDate.parse(date) else { return nil }
        let parts = EventCalendarDate.calendar.dateComponents([.month, .day, .weekday], from: parsed)
        let names = ["日", "一", "二", "三", "四", "五", "六"]
        guard let month = parts.month, let day = parts.day, let weekday = parts.weekday else { return nil }
        return ("\(month)/\(day)", "週\(names[(weekday - 1) % 7])")
    }

    /// 「今天」「明天」「3 天後」；與 daysAway 相同，今天以事件自己的時區計算。
    public func relativeDayText(now: Date = Date()) -> String? {
        guard let day = EventCalendarDate.parse(date),
              let today = EventCalendarDate.parse(EventCalendarDate.key(now, timezone: timezone)) else { return nil }
        return DisplayFormatting.relativeDays(from: today, to: day, timeZone: EventCalendarDate.calendar.timeZone)
    }

    public func daysAway(now: Date = Date()) -> Int? {
        guard let day = EventCalendarDate.parse(date),
              let today = EventCalendarDate.parse(EventCalendarDate.key(now, timezone: timezone)) else { return nil }
        return EventCalendarDate.calendar.dateComponents([.day], from: today, to: day).day
    }

    public func isWithinSevenDays(now: Date = Date()) -> Bool {
        guard let days = daysAway(now: now) else { return false }
        return (0...7).contains(days)
    }
}

public extension Array where Element == CalendarEvent {
    /// 下一場公司事件；已過去的日期依事件自己的時區排除（台北上午時美東還是昨天）。
    func upcomingCompanyEvents(limit: Int, now: Date = Date()) -> [CalendarEvent] {
        Array(filter { $0.isCompanyEvent && $0.dateKind == "release" && ($0.daysAway(now: now) ?? -1) >= 0 }
            .sorted { $0.date < $1.date }.prefix(limit))
    }

    func nextCompanyEvent(now: Date = Date()) -> CalendarEvent? {
        filter { $0.isCompanyEvent && $0.dateKind == "release" && ($0.daysAway(now: now) ?? -1) >= 0 }
            .sorted { $0.date < $1.date }.first
    }
}

public struct UndatedCalendarStock: Codable, Sendable, Identifiable {
    public var id: String { code }
    public let code: String
    public let name: String
    public let detail: String
}

/// `GET /alerts/monitor/status`：監控實際狀態，舊服務沒有這個端點時由呼叫端當成無法取得。
public struct AlertMonitorStatus: Codable, Sendable {
    public let running: Bool
    public let reason: String?
    public let intervalSeconds: Int?
    public let lastRunAt: String?
    public let channels: [String]?
    public let enabledRules: Int?

    public init(running: Bool, reason: String? = nil, intervalSeconds: Int? = nil, lastRunAt: String? = nil, channels: [String]? = nil, enabledRules: Int? = nil) {
        self.running = running
        self.reason = reason
        self.intervalSeconds = intervalSeconds
        self.lastRunAt = lastRunAt
        self.channels = channels
        self.enabledRules = enabledRules
    }

    public var summaryLabel: String {
        guard running else { return "監控未啟動" }
        return "監控中 · \(enabledRules ?? 0) 條規則"
    }
}

public struct EventCalendarResponse: Codable, Sendable {
    public let events: [CalendarEvent]
    public let undated: [UndatedCalendarStock]
    public let cacheUpdatedAt: String?
}

// MARK: - I09～I11 個股與報告追加型別

/// 只用來判斷有沒有基金持倉；淨值讀不到時 consolidated_fund_value_base 是 nil，持倉仍在。
public struct PortfolioFundsBlock: Codable, Sendable {
    public struct Item: Codable, Sendable {}

    public let items: [Item]?
}

public struct StockProfilePortfolioBlock: Codable, Sendable {
    public struct Relation: Codable, Sendable {
        public let held: Bool?
    }

    public let status: String
    public let data: Relation?
}

public struct StockProfilePosition: Codable, Sendable {
    public let quantity: Double
    public let avgCost: Double?
    public let currency: String?
    public let lastPrice: Double?
    public let marketValue: Double?
    public let unrealizedPnl: Double?
    public let unrealizedPnlPct: Double?
    public let weightPct: Double?
    public let accountCount: Int?
}

/// 法人單位是股、融資融券單位是張，兩者不可相比。
public struct StockProfileChips: Codable, Sendable {
    public let institutionalDate: String?
    public let foreignNet: Double?
    public let trustNet: Double?
    public let dealerNet: Double?
    public let totalNet: Double?
    public let marginDate: String?
    public let marginBalance: Double?
    public let marginChg5: Double?
    public let marginChg20: Double?
    public let shortBalance: Double?
    public let shortMarginRatio: Double?
}

public struct StockProfileNewsItem: Codable, Sendable {
    public let title: String?
    public let url: String?
    public let source: String?
    public let publishedDate: String?
}

public struct ReportPositionAdvice: Codable, Sendable {
    public let noPosition: String?
    public let hasPosition: String?

    public init(noPosition: String? = nil, hasPosition: String? = nil) {
        self.noPosition = noPosition
        self.hasPosition = hasPosition
    }
}

public struct ReportPreviousSummary: Codable, Sendable {
    public let id: Int?
    public let action: String?
    public let score: Int?
    public let createdAt: String?
    public let stopLoss: Double?
}

public struct SniperPrices: Codable, Sendable {
    public let idealBuy: Double?
    public let secondaryBuy: Double?
    public let stopLoss: Double?
    public let takeProfit: Double?

    public init(idealBuy: Double? = nil, secondaryBuy: Double? = nil, stopLoss: Double? = nil, takeProfit: Double? = nil) {
        self.idealBuy = idealBuy
        self.secondaryBuy = secondaryBuy
        self.stopLoss = stopLoss
        self.takeProfit = takeProfit
    }
}

public struct ResearchEventGap: Codable, Sendable {
    public let triggered: Bool?
    public let eventDate: String?
    public let changePct: Double?
    public let eventLow: Double?
    public let sessionsSinceEvent: Int?
    public let thresholdPct: Double?
    public let latestClose: Double?
    public let postEventMinClose: Double?
    public let eventLowBroken: Bool?
    public let newsEvidencePresent: Bool?
    public let blockedWithoutNews: Bool?
    public let reason: String?
}

/// `GET /stocks/indices` 順帶回的市場狀態；舊後端沒有這些欄位時都是 nil。
public struct MarketSessionStatus: Codable, Sendable {
    public let marketPhase: String?
    public let marketOpen: Bool?

    public init(marketPhase: String? = nil, marketOpen: Bool? = nil) {
        self.marketPhase = marketPhase
        self.marketOpen = marketOpen
    }
}
