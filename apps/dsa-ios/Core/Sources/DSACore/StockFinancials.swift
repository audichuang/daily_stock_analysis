import Foundation

/// 手動鏡像 api/v1/schemas/stocks.py 的 StockFinancialsResponse。金額都是 1 元財報幣別。
public struct StockFinancials: Decodable, Sendable {
    public let stockCode: String
    public let market: String?
    public let status: String
    public let statusReason: String?
    public let template: String?
    public let currency: String?
    public let tradingCurrency: String?
    public let source: FinancialSource?
    public let periods: [FinancialPeriod]
    public let metrics: [FinancialMetric]
    public let notApplicable: [FinancialNotApplicable]
    public let monthlyRevenue: [MonthlyRevenuePoint]
    public let ttmRevenueYoyPct: Double?
    public let limitations: [String]
    public let isStale: Bool
    public let commentary: FinancialCommentary
}

public struct FinancialSource: Decodable, Sendable {
    public let label: String
    public let sourceUnit: String
}

public struct FinancialPeriod: Decodable, Sendable {
    public let key: String
    public let label: String
    public let periodEnd: String
    public let announceDate: String?
    public let announceDateKind: String
}

public struct FinancialMetric: Decodable, Sendable, Identifiable {
    public let key: String
    public let label: String
    public let kind: String
    public let unit: String
    public let definition: String
    public let points: [FinancialMetricPoint]

    public var id: String { key }

    public var isRatio: Bool { kind == "ratio" }

    public func value(_ point: FinancialMetricPoint?, currency: String?) -> String {
        FinancialFormat.metric(point?.value, kind: kind, unit: unit, currency: currency)
    }

    public func yoy(_ point: FinancialMetricPoint?) -> String {
        FinancialFormat.change(isRatio ? point?.yoyPp : point?.yoyPct, points: isRatio)
    }

    public func qoq(_ point: FinancialMetricPoint?) -> String {
        FinancialFormat.change(isRatio ? point?.qoqPp : point?.qoqPct, points: isRatio)
    }
}

public struct FinancialMetricPoint: Decodable, Sendable {
    public let period: String
    public let value: Double?
    public let yoyPct: Double?
    public let qoqPct: Double?
    public let yoyPp: Double?
    public let qoqPp: Double?
    public let derived: Bool
}

public struct FinancialNotApplicable: Decodable, Sendable {
    public let key: String
    public let label: String
    public let reason: String
}

public struct MonthlyRevenuePoint: Decodable, Sendable {
    public let month: String
    public let revenue: Double?
    public let yoyPct: Double?
    public let momPct: Double?
}

public struct FinancialHighlight: Decodable, Sendable {
    public let metricKey: String
    public let period: String
    public let importance: String
    public let whatHappened: String
    public let whyItMatters: String
    public let howToRead: String
}

public struct FinancialCommentary: Decodable, Sendable {
    public let status: String
    public let headline: String?
    public let highlights: [FinancialHighlight]
    public let message: String?

    public init(status: String, headline: String? = nil, highlights: [FinancialHighlight] = [], message: String? = nil) {
        self.status = status
        self.headline = headline
        self.highlights = highlights
        self.message = message
    }

    /// 只回傳指向這個欄位的標記；快取讀回或舊版 App 遇到新欄位時，對不到的不顯示。
    public func highlights(for metricKey: String) -> [FinancialHighlight] {
        highlights.filter { $0.metricKey == metricKey }
    }
}

public enum FinancialFormat {
    private static let minus = "−"

    private static func word(_ currency: String?) -> String {
        switch currency {
        case "TWD": return "元"
        case "USD": return "美元"
        case let other?: return " \(other)"
        case nil: return ""
        }
    }

    /// 沒有讀數顯示 —，不顯示 0。
    public static func amount(_ value: Double?, currency: String?) -> String {
        guard let value, value.isFinite else { return "—" }
        let sign = value < 0 ? minus : ""
        let magnitude = abs(value)
        let unit = word(currency)
        if magnitude >= 1e12 { return "\(sign)\(String(format: "%.2f", magnitude / 1e12)) 兆\(unit)" }
        if magnitude >= 1e8 { return "\(sign)\(grouped(magnitude / 1e8, digits: 1)) 億\(unit)" }
        if magnitude >= 1e4 { return "\(sign)\(grouped(magnitude / 1e4, digits: 0)) 萬\(unit)" }
        return "\(sign)\(grouped(magnitude, digits: 0)) \(unit)".trimmingCharacters(in: .whitespaces)
    }

    public static func metric(_ value: Double?, kind: String, unit: String, currency: String?) -> String {
        guard let value, value.isFinite else { return "—" }
        let sign = value < 0 ? minus : ""
        switch kind {
        case "ratio":
            return "\(sign)\(String(format: "%.1f", abs(value)))%"
        case "per_share":
            // TWD/ADR 這類口徑不能省略：ADR 的 EPS 和原股不同基準。
            let parts = unit.split(separator: "/")
            let per = parts.count > 1 && parts[1] != "股" ? "／\(parts[1])" : ""
            return "\(sign)\(String(format: "%.2f", abs(value))) \(word(currency).trimmingCharacters(in: .whitespaces))\(per)"
        default:
            return amount(value, currency: currency)
        }
    }

    public static func change(_ value: Double?, points: Bool = false) -> String {
        guard let value, value.isFinite else { return "—" }
        let sign = value > 0 ? "+" : value < 0 ? minus : ""
        return "\(sign)\(String(format: "%.1f", abs(value)))\(points ? " 個百分點" : "%")"
    }

    private static func grouped(_ value: Double, digits: Int) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.usesGroupingSeparator = true
        formatter.groupingSeparator = ","
        formatter.minimumFractionDigits = digits
        formatter.maximumFractionDigits = digits
        return formatter.string(from: NSNumber(value: value)) ?? String(format: "%.\(digits)f", value)
    }
}
