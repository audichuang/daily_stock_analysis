import Foundation

public extension HistoryItem {
    var isMarketReview: Bool { reportType == "market_review" }

    /// 列表的結論：優先用結構化的一句話，舊紀錄才退回摘要。
    var conclusion: String? {
        for candidate in [oneSentence, analysisSummary] {
            if let text = candidate?.trimmingCharacters(in: .whitespacesAndNewlines), !text.isEmpty { return text }
        }
        return nil
    }
}

/// 研究庫的一列：同日同檔只佔一列，較早的版本收在 `earlier`（新到舊）。
public struct ResearchLibraryEntry: Identifiable, Sendable {
    public let id: String
    public let primary: HistoryItem
    public let earlier: [HistoryItem]

    /// 當日最早一份到最新一份的差異；動作與評分都沒變就是 nil。
    public var changeSummary: String? {
        guard let first = earlier.last else { return nil }
        var parts: [String] = []
        let from = DecisionAction.displayText(action: first.action, label: first.actionLabel)
        let to = DecisionAction.displayText(action: primary.action, label: primary.actionLabel)
        if let from, let to, from != to { parts.append("\(from) → \(to)") }
        if let before = first.sentimentScore, let after = primary.sentimentScore, before != after {
            parts.append("評分 \(before) → \(after)")
        }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }
}

public struct ResearchLibraryDay: Identifiable, Sendable {
    public var id: String { key }
    /// `yyyy-MM-dd`；缺日期的紀錄是 `unknown`。
    public let key: String
    public let title: String
    public let entries: [ResearchLibraryEntry]
}

public enum ResearchLibrary {
    private static let unknownDay = "unknown"
    private static let weekdays = ["日", "一", "二", "三", "四", "五", "六"]

    /// items 須已由新到舊排序；分組與整併都保留這個順序。
    public static func days(_ items: [HistoryItem], now: Date = Date(), timeZone: TimeZone = .current) -> [ResearchLibraryDay] {
        var order: [String] = []
        var byDay: [String: [HistoryItem]] = [:]
        for item in items {
            let key = dayKey(item.createdAt) ?? unknownDay
            if byDay[key] == nil { order.append(key) }
            byDay[key, default: []].append(item)
        }
        return order.map { key in
            ResearchLibraryDay(key: key, title: title(for: key, now: now, timeZone: timeZone), entries: entries(byDay[key] ?? [], day: key))
        }
    }

    /// 後端時間帶伺服器時區的 offset；直接取字串的日期，日期跟著報告當地走，也不受小數秒位數影響。
    static func dayKey(_ createdAt: String?) -> String? {
        guard let createdAt, createdAt.count >= 10 else { return nil }
        let key = String(createdAt.prefix(10))
        return parts(of: key) == nil ? nil : key
    }

    private static func entries(_ items: [HistoryItem], day: String) -> [ResearchLibraryEntry] {
        var order: [String] = []
        var groups: [String: [HistoryItem]] = [:]
        for item in items {
            // 大盤複盤依市場分開，沒有股票代號可比；缺報告編號的列打不開，不併進別列。
            let group: String
            if item.isMarketReview {
                group = "review:\(item.region ?? item.stockCode)"
            } else if item.id == nil {
                group = "orphan:\(item.queryId):\(item.stockCode)"
            } else {
                group = "stock:\(item.stockCode)"
            }
            if groups[group] == nil { order.append(group) }
            groups[group, default: []].append(item)
        }
        return order.compactMap { group in
            guard let members = groups[group], let primary = members.first else { return nil }
            return ResearchLibraryEntry(id: "\(day)|\(group)", primary: primary, earlier: Array(members.dropFirst()))
        }
    }

    private static func parts(of key: String) -> (year: Int, month: Int, day: Int)? {
        let pieces = key.split(separator: "-", omittingEmptySubsequences: false)
        guard pieces.count == 3, pieces[0].count == 4, pieces[1].count == 2, pieces[2].count == 2,
              let year = Int(pieces[0]), let month = Int(pieces[1]), let day = Int(pieces[2]),
              (1...12).contains(month), (1...31).contains(day) else { return nil }
        return (year, month, day)
    }

    static func title(for key: String, now: Date, timeZone: TimeZone) -> String {
        guard let value = parts(of: key) else { return "日期未提供" }
        var local = Calendar(identifier: .gregorian)
        local.timeZone = timeZone
        let today = local.dateComponents([.year, .month, .day], from: now)
        var utc = Calendar(identifier: .gregorian)
        utc.timeZone = TimeZone(identifier: "UTC") ?? .current
        guard let date = utc.date(from: DateComponents(year: value.year, month: value.month, day: value.day)),
              let todayDate = utc.date(from: DateComponents(year: today.year, month: today.month, day: today.day)) else {
            return key
        }
        let offset = utc.dateComponents([.day], from: date, to: todayDate).day
        if offset == 0 { return "今天" }
        if offset == 1 { return "昨天" }
        let weekday = weekdays[(utc.component(.weekday, from: date) - 1) % 7]
        let monthDay = String(format: "%02d/%02d", value.month, value.day)
        return value.year == today.year ? "\(monthDay)（週\(weekday)）" : "\(value.year)/\(monthDay)（週\(weekday)）"
    }
}
