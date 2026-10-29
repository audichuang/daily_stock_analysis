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
