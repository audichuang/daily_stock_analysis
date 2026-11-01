import Foundation

/// 報告全文的區塊。只解析 Markdown 語法與模板固定的狀態符號，不從文字猜語意。
public enum MarkdownBlock: Equatable, Sendable {
    case heading(level: Int, text: String)
    case paragraph(String)
    case list([MarkdownListItem])
    case quote(String)
    case divider
    case table(headers: [String], rows: [[String]])
    case code(String)
}

public enum ChecklistStatus: Equatable, Sendable {
    case passed, warning, failed, pending
}

public struct MarkdownListItem: Equatable, Sendable {
    /// 「•」或「1.」；檢查清單項目由 status 決定圖示。
    public let marker: String
    public let level: Int
    public let text: String
    public let status: ChecklistStatus?

    public init(marker: String, level: Int, text: String, status: ChecklistStatus? = nil) {
        self.marker = marker
        self.level = level
        self.text = text
        self.status = status
    }
}

public struct MarkdownSection: Identifiable, Equatable, Sendable {
    public let id: Int
    /// 第一個標題之前的內容沒有標題。
    public let title: String?
    public let blocks: [MarkdownBlock]
}

public enum MarkdownParser {
    public static func parse(_ source: String) -> [MarkdownBlock] {
        let lines = source.replacingOccurrences(of: "\r\n", with: "\n").components(separatedBy: "\n")
        var blocks: [MarkdownBlock] = []
        var index = 0
        var paragraph: [String] = []

        func flush() {
            if !paragraph.isEmpty { blocks.append(.paragraph(paragraph.joined(separator: "\n"))) }
            paragraph = []
        }

        while index < lines.count {
            let line = lines[index]
            let trimmed = line.trimmingCharacters(in: .whitespaces)

            if trimmed.isEmpty { flush(); index += 1; continue }

            if trimmed.hasPrefix("```") || trimmed.hasPrefix("~~~") {
                flush()
                let fence = String(trimmed.prefix(3))
                var body: [String] = []
                index += 1
                while index < lines.count, !lines[index].trimmingCharacters(in: .whitespaces).hasPrefix(fence) {
                    body.append(lines[index])
                    index += 1
                }
                index += 1
                blocks.append(.code(body.joined(separator: "\n")))
                continue
            }
            if let heading = heading(trimmed) {
                flush()
                blocks.append(.heading(level: heading.level, text: heading.text))
                index += 1
                continue
            }
            if isDivider(trimmed) {
                flush()
                blocks.append(.divider)
                index += 1
                continue
            }
            if trimmed.contains("|"), index + 1 < lines.count, isTableSeparator(lines[index + 1]) {
                flush()
                let headers = cells(trimmed)
                var rows: [[String]] = []
                index += 2
                while index < lines.count {
                    let row = lines[index].trimmingCharacters(in: .whitespaces)
                    guard !row.isEmpty, row.contains("|") else { break }
                    rows.append(aligned(cells(row), to: headers.count))
                    index += 1
                }
                blocks.append(.table(headers: headers, rows: rows))
                continue
            }
            if trimmed.hasPrefix(">") {
                flush()
                var quote: [String] = []
                while index < lines.count {
                    let current = lines[index].trimmingCharacters(in: .whitespaces)
                    guard current.hasPrefix(">") else { break }
                    quote.append(String(current.dropFirst()).trimmingCharacters(in: .whitespaces))
                    index += 1
                }
                blocks.append(.quote(quote.joined(separator: "\n")))
                continue
            }
            if listItem(line) != nil {
                flush()
                var items: [MarkdownListItem] = []
                while index < lines.count, let item = listItem(lines[index]) {
                    items.append(item)
                    index += 1
                }
                blocks.append(.list(items))
                continue
            }
            // 模板會輸出沒有項目符號的「✅ 文字」，一樣當檢查清單。
            if let status = leadingStatus(trimmed) {
                flush()
                blocks.append(.list([MarkdownListItem(marker: "•", level: 0, text: status.text, status: status.status)]))
                index += 1
                continue
            }
            paragraph.append(trimmed)
            index += 1
        }
        flush()
        return blocks
    }

    /// 拆成可收合段落：取出現兩次以上的最高層標題當段落界線，
    /// 模板常見的「## 股票名」＋多個「###」就會以 ### 分段，股票名不佔一段。
    /// alreadyShown 是頁面上已顯示的文字（摘要、一句話），完全相同的段落略過；全文內重複的段落與整段也略過。
    public static func sections(_ source: String, alreadyShown: [String] = []) -> [MarkdownSection] {
        let blocks = parse(source)
        var counts: [Int: Int] = [:]
        for block in blocks {
            if case let .heading(level, _) = block { counts[level, default: 0] += 1 }
        }
        let boundary = counts.filter { $0.value >= 2 }.keys.min() ?? counts.keys.min()

        var seen = Set(alreadyShown.map(normalized))
        var collected: [(title: String?, blocks: [MarkdownBlock])] = []
        var title: String?
        var current: [MarkdownBlock] = []

        for block in blocks {
            switch block {
            case let .heading(level, text):
                if let boundary, level == boundary {
                    collected.append((title, current))
                    title = text
                    current = []
                } else if let boundary, level > boundary {
                    current.append(block)
                }
                // 比界線高的標題（報告大標）不佔位置，內容歸到下一段。
            case let .paragraph(text), let .quote(text):
                if seen.insert(normalized(text)).inserted { current.append(block) }
            default:
                current.append(block)
            }
        }
        collected.append((title, current))

        var seenSections = Set<String>()
        var sections: [MarkdownSection] = []
        for entry in collected where !entry.blocks.isEmpty {
            let signature = normalized(entry.title ?? "") + "\u{1F}" + String(describing: entry.blocks)
            guard seenSections.insert(signature).inserted else { continue }
            sections.append(MarkdownSection(id: sections.count, title: entry.title, blocks: entry.blocks))
        }
        return sections
    }

    /// 行內語法轉成 AttributedString 並去掉斜體：繁中沒有斜體字形，只會變成歪斜的難讀字。
    public static func inline(_ text: String) -> AttributedString {
        let options = AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        guard var result = try? AttributedString(markdown: text, options: options) else { return AttributedString(text) }
        var italics: [(Range<AttributedString.Index>, InlinePresentationIntent)] = []
        for run in result.runs {
            if let intent = run.inlinePresentationIntent, intent.contains(.emphasized) {
                italics.append((run.range, intent))
            }
        }
        for (range, intent) in italics {
            result[range].inlinePresentationIntent = intent.subtracting(.emphasized)
        }
        return result
    }

    private static func normalized(_ text: String) -> String {
        text.components(separatedBy: .whitespacesAndNewlines).joined()
            .replacingOccurrences(of: "*", with: "")
    }

    private static func heading(_ line: String) -> (level: Int, text: String)? {
        let hashes = line.prefix { $0 == "#" }.count
        guard (1...6).contains(hashes), line.dropFirst(hashes).first == " " else { return nil }
        return (hashes, line.dropFirst(hashes + 1).trimmingCharacters(in: .whitespaces))
    }

    private static func isDivider(_ line: String) -> Bool {
        let compact = line.replacingOccurrences(of: " ", with: "")
        guard compact.count >= 3, let first = compact.first, "-*_".contains(first) else { return false }
        return compact.allSatisfy { $0 == first }
    }

    private static func isTableSeparator(_ line: String) -> Bool {
        let trimmed = line.trimmingCharacters(in: .whitespaces)
        guard trimmed.contains("-"), trimmed.contains("|") else { return false }
        return trimmed.allSatisfy { "|-: ".contains($0) }
    }

    /// 欄數對不齊時補空字串、多的併到最後一欄，畫面不掉資料。
    private static func aligned(_ values: [String], to count: Int) -> [String] {
        guard count > 0, values.count > count else {
            return values + Array(repeating: "", count: max(0, count - values.count))
        }
        return Array(values.prefix(count - 1)) + [values.dropFirst(count - 1).joined(separator: " | ")]
    }

    private static func cells(_ line: String) -> [String] {
        var body = Substring(line.trimmingCharacters(in: .whitespaces))
        if body.hasPrefix("|") { body = body.dropFirst() }
        if body.hasSuffix("|"), !body.hasSuffix("\\|") { body = body.dropLast() }
        var values: [String] = []
        var cell = ""
        var escaped = false
        for character in body {
            if escaped {
                cell.append(character == "|" ? "|" : "\\\(character)")
                escaped = false
            } else if character == "\\" {
                escaped = true
            } else if character == "|" {
                values.append(cell.trimmingCharacters(in: .whitespaces))
                cell = ""
            } else {
                cell.append(character)
            }
        }
        if escaped { cell.append("\\") }
        values.append(cell.trimmingCharacters(in: .whitespaces))
        return values
    }

    private static func listItem(_ line: String) -> MarkdownListItem? {
        let indent = line.prefix { $0 == " " || $0 == "\t" }.reduce(0) { $0 + ($1 == "\t" ? 4 : 1) }
        let body = line.drop { $0 == " " || $0 == "\t" }
        let level = indent / 2
        var marker = "•"
        var rest: String
        if let first = body.first, "-*+".contains(first), body.dropFirst().first == " " {
            rest = String(body.dropFirst(2))
        } else {
            let digits = body.prefix { $0.isASCII && $0.isNumber }
            guard !digits.isEmpty else { return nil }
            let after = body.dropFirst(digits.count)
            guard let dot = after.first, dot == "." || dot == ")", after.dropFirst().first == " " else { return nil }
            marker = "\(digits)."
            rest = String(after.dropFirst(2))
        }
        rest = rest.trimmingCharacters(in: .whitespaces)
        let lowered = rest.lowercased()
        if lowered.hasPrefix("[x] ") {
            return MarkdownListItem(marker: marker, level: level, text: String(rest.dropFirst(4)), status: .passed)
        }
        if lowered.hasPrefix("[ ] ") {
            return MarkdownListItem(marker: marker, level: level, text: String(rest.dropFirst(4)), status: .pending)
        }
        if let status = leadingStatus(rest) {
            return MarkdownListItem(marker: marker, level: level, text: status.text, status: status.status)
        }
        return MarkdownListItem(marker: marker, level: level, text: rest)
    }

    // 「⚠️」有無 U+FE0F 是不同字素，兩種都要認。
    private static let statusGlyphs: [(String, ChecklistStatus)] = [
        ("✅", .passed), ("☑️", .passed), ("⚠️", .warning), ("\u{26A0}", .warning), ("❌", .failed), ("⏳", .pending)
    ]

    private static func leadingStatus(_ text: String) -> (status: ChecklistStatus, text: String)? {
        guard let first = text.first else { return nil }
        for (glyph, status) in statusGlyphs where String(first) == glyph {
            let rest = text.dropFirst().trimmingCharacters(in: .whitespaces)
            // 只有符號，或後面緊接粗體標題（「✅ **檢查清單**」）不當清單項目，留給段落。
            if rest.isEmpty || rest.hasPrefix("**") { return nil }
            return (status, rest)
        }
        return nil
    }
}
