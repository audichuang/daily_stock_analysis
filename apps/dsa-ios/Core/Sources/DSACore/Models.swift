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
    public let asOf: String?
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
}

public struct AnalysisReport: Codable, Sendable {
    public let meta: ReportMeta
    public let summary: ReportSummary
    public let strategy: ReportStrategy?
    public let structuredReport: ResearchArtifact?
    public let eventOutlook: EventOutlook?
}

public struct EventConsensus: Codable, Sendable {
    public let eps: Double?
    public let revenue: Double?
    public let analysts: Int?
    public let currency: String?
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
        let currency = consensus.currency.map { " \($0)" } ?? ""
        if let eps = consensus.eps { parts.append("EPS \(String(format: "%.2f", eps))\(currency)") }
        if let revenue = consensus.revenue { parts.append("營收 \(String(format: "%.0f", revenue / 100_000_000)) 億\(currency)") }
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
}

public struct ReportSummary: Codable, Sendable {
    public let analysisSummary: String?
    public let operationAdvice: String?
    public let action: String?
    public let actionLabel: String?
    public let trendPrediction: String?
    public let sentimentScore: Int?
    public let sentimentLabel: String?
}

public struct ReportStrategy: Codable, Sendable {
    public let idealBuy: String?
    public let secondaryBuy: String?
    public let stopLoss: String?
    public let takeProfit: String?
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
    public var timezoneLabel: String { timezone == "America/New_York" ? "美東 ET" : "台北" }

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

public struct EventCalendarResponse: Codable, Sendable {
    public let events: [CalendarEvent]
    public let undated: [UndatedCalendarStock]
    public let cacheUpdatedAt: String?
}
