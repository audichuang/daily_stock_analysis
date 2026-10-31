import Foundation

public struct ReportNewsResponse: Decodable, Sendable {
    public let total: Int
    public let items: [ReportNewsItem]
}

public struct ReportNewsItem: Decodable, Sendable {
    public let title: String
    public let snippet: String
    public let url: String
    public let source: String?
    public let publishedDate: String?
    public let dimension: String?

    /// 分類只看搜尋面向；未知面向保留在參考資料，不猜測標題或網域。
    public var isNews: Bool {
        ["latest_news", "announcements", "risk_check"].contains(dimension ?? "")
    }

    public var externalURL: URL? {
        guard let value = URL(string: url), ["http", "https"].contains(value.scheme?.lowercased() ?? ""),
              value.host?.isEmpty == false, value.user == nil, value.password == nil else { return nil }
        return value
    }

    public var sourceLabel: String {
        let name = Self.plainText(source ?? "")
        return name.isEmpty ? (externalURL?.host ?? "來源未提供") : name
    }

    public var displayTitle: String {
        let cleaned = Self.plainText(title)
        let host = externalURL?.host?.lowercased() ?? ""
        if (host == "sec.gov" || host.hasSuffix(".sec.gov")),
           ["document", "", "ex-99.1"].contains(cleaned.lowercased()) {
            let path = externalURL?.path.lowercased() ?? ""
            if path.contains("8-k") || path.contains("8k") { return "SEC 8-K 公告" }
            if path.contains("10-q") || path.contains("10q") { return "SEC 10-Q 季報" }
            if path.contains("10-k") || path.contains("10k") { return "SEC 10-K 年報" }
            return "SEC 官方文件"
        }
        return cleaned.isEmpty ? "未提供標題" : cleaned
    }

    public var summary: String {
        // 已觀察到搜尋摘錄回傳 SEC 附件全文、Markdown 表格與 HTML 原始內容。
        let value = snippet.replacingOccurrences(of: #"(?s)```.*?(?:```|$)"#, with: "", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if value.range(of: #"^(EX-\d|<\?xml|<!DOCTYPE|<html|<DOCUMENT|<SEC-DOCUMENT)"#,
                       options: [.regularExpression, .caseInsensitive]) != nil { return "" }
        let prose = value.components(separatedBy: .newlines).filter { line in
            !line.contains("|") && !line.trimmingCharacters(in: .whitespaces).hasPrefix("```")
        }.joined(separator: " ")
        return Self.plainText(prose)
    }

    public var publicationDate: Date? {
        guard let publishedDate else { return nil }
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = iso.date(from: publishedDate) { return date }
        iso.formatOptions = [.withInternetDateTime]
        if let date = iso.date(from: publishedDate) { return date }
        let day = DateFormatter()
        day.locale = Locale(identifier: "en_US_POSIX")
        day.timeZone = TimeZone(secondsFromGMT: 0)
        day.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSSSSS"
        if let date = day.date(from: publishedDate) { return date }
        day.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        if let date = day.date(from: publishedDate) { return date }
        day.dateFormat = "yyyy-MM-dd"
        return day.date(from: publishedDate)
    }

    /// 只顯示來源的日曆日，不把日級資料轉成裝置時區的前一天，也不補造時間。
    public var dateLabel: String? {
        guard publicationDate != nil, let publishedDate else { return nil }
        return String(publishedDate.prefix(10))
    }

    public static func newestFirst(_ items: [Self]) -> [Self] {
        items.enumerated().sorted { lhs, rhs in
            let left = lhs.element.publicationDate ?? .distantPast
            let right = rhs.element.publicationDate ?? .distantPast
            return left == right ? lhs.offset < rhs.offset : left > right
        }.map(\.element)
    }

    private static func plainText(_ text: String) -> String {
        let stripped = text.replacingOccurrences(of: "【DeepSeek 搜尋日期未經原文核實；日級日期非精確發布時間】", with: "")
            .replacingOccurrences(of: #"<[^>]+>"#, with: " ", options: .regularExpression)
        let plain = (try? AttributedString(markdown: stripped)).map { String($0.characters) } ?? stripped
        return plain.replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
