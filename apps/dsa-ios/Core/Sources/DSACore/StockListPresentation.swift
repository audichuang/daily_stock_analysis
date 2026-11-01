import Foundation

/// 代號的顯示規則；路由與 API 一律用完整代號，只有畫面去後綴。
public enum StockCodeDisplay {
    // .TWO 要排在 .TW 前面，否則 6488.TWO 比對不到正確長度。
    private static let suffixes = [".TWO", ".TW", ".US", "-US"]

    public static func isTaiwan(_ code: String) -> Bool {
        let upper = code.uppercased()
        return upper.hasSuffix(".TW") || upper.hasSuffix(".TWO")
    }

    /// BRK.B 的 .B 是股別不是市場後綴，保留。
    public static func display(_ code: String) -> String {
        let upper = code.uppercased()
        for suffix in suffixes where upper.hasSuffix(suffix) {
            return String(code.dropLast(suffix.count))
        }
        return code
    }
}

/// 列的第一、二行：台股大家記名稱，美股大家記 ticker。
public struct StockRowTitles: Equatable, Sendable {
    public let primary: String
    public let secondary: String?

    public init(code: String, name: String?) {
        let display = StockCodeDisplay.display(code)
        let cleanName = name?.trimmingCharacters(in: .whitespacesAndNewlines)
        let usableName = cleanName?.isEmpty == false ? cleanName : nil
        if StockCodeDisplay.isTaiwan(code) {
            primary = usableName ?? display
            secondary = usableName == nil ? nil : display
        } else {
            primary = display
            secondary = usableName
        }
    }
}

public enum LimitProximity: Equatable, Sendable {
    case nearUp, nearDown

    /// 距漲跌停 1% 內算「近」。只讀後端給的漲跌停價；Shioaji 降級或美股沒有這兩欄時回 nil，不用漲跌幅猜。
    public static let threshold = 0.01

    public static func of(price: Double?, limitUp: Double?, limitDown: Double?) -> LimitProximity? {
        guard let price, price.isFinite, price > 0 else { return nil }
        if let limitUp, limitUp.isFinite, limitUp > 0, price >= limitUp * (1 - threshold) { return .nearUp }
        if let limitDown, limitDown.isFinite, limitDown > 0, price <= limitDown * (1 + threshold) { return .nearDown }
        return nil
    }
}

/// 列上的報價警告，只留真正的例外。與 PresentationText.quoteWarning 分開：持股列要標每一種延遲，清單列不用。
public enum StockRowWarning {
    /// - 沒有報價：一定警告。
    /// - 台股走 yfinance：Shioaji 降級的訊號；後端此時一律標 is_stale，所以要先判，顯示延遲而不是過期。
    /// - 其他 is_stale：行情超過時效（上一場收盤後的非盤中，後端已排除）。
    /// - 美股走 yfinance 是常態，不警告。
    public static func text(hasQuote: Bool, isStale: Bool?, sourceCode: String?, source: String?, code: String) -> String? {
        guard hasQuote else { return "尚無報價" }
        if StockCodeDisplay.isTaiwan(code), normalizedSource(sourceCode: sourceCode, source: source) == "yfinance" {
            return "可能延遲"
        }
        return isStale == true ? "價格過期" : nil
    }

    /// 舊後端沒有 source_code：比照後端 normalize_source_code 收斂 source 字串。
    static func normalizedSource(sourceCode: String?, source: String?) -> String? {
        if let sourceCode, !sourceCode.isEmpty { return sourceCode.lowercased() }
        guard let source else { return nil }
        let head = source.split(separator: "(", maxSplits: 1, omittingEmptySubsequences: false).first.map(String.init) ?? source
        let code = head.trimmingCharacters(in: .whitespaces).lowercased()
        return code == "fallback" ? "yfinance" : (code.isEmpty ? nil : code)
    }
}

/// AI 判斷的日期只在過舊時才顯示。
public enum ReportAge {
    /// 超過 5 天才算舊：涵蓋週末加一天連假，避免週一早上整排都標日期。
    public static let staleAfterDays = 5

    public static func staleLabel(createdAt: String?, now: Date = Date(), timeZone: TimeZone = .current) -> String? {
        guard let createdAt, let reported = TradingDay.parse(createdAt) else { return nil }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = timeZone
        formatter.dateFormat = "yyyy-MM-dd"
        guard let today = TradingDay.parse(formatter.string(from: now)),
              let days = TradingDay.calendar.dateComponents([.day], from: reported, to: today).day,
              days > staleAfterDays else { return nil }
        if days < 30 { return "\(days) 天前" }
        if days < 365 { return "\(days / 30) 個月前" }
        return "\(days / 365) 年前"
    }
}

/// 清單右欄可切換的欄位。
public enum StockRowMetric: String, CaseIterable, Identifiable, Sendable {
    case changePercent, amount, volumeRatio

    public var id: String { rawValue }

    public var title: String {
        switch self {
        case .changePercent: return "漲跌幅"
        case .amount: return "成交值"
        case .volumeRatio: return "量比"
        }
    }

    public var sortKey: StockSortKey {
        switch self {
        case .changePercent: return .changePercent
        case .amount: return .amount
        case .volumeRatio: return .volumeRatio
        }
    }
}

public enum StockListFormat {
    public static func signedNumber(_ value: Double?) -> String {
        let text = DisplayNumber.number(value)
        guard let value, value > 0, text.contains(where: { ("1"..."9").contains($0) }) else { return text }
        return "+" + text
    }

    /// 成交值用億、萬，欄寬放不下完整金額。沒有讀數顯示 —，0 仍是讀數。
    public static func amount(_ value: Double?) -> String {
        guard let value, value.isFinite else { return DisplayNumber.noValue }
        let magnitude = abs(value)
        if magnitude >= 100_000_000 { return DisplayNumber.number(value / 100_000_000) + " 億" }
        if magnitude >= 10_000 { return DisplayNumber.number(value / 10_000) + " 萬" }
        return DisplayNumber.number(value, digits: 0)
    }
}

public struct StockListEntry: Equatable, Sendable {
    public let code: String
    public let name: String?
    public let price: Double?
    public let changePercent: Double?
    public let amount: Double?
    public let volumeRatio: Double?

    public init(code: String, name: String? = nil, price: Double? = nil, changePercent: Double? = nil,
                amount: Double? = nil, volumeRatio: Double? = nil) {
        self.code = code
        self.name = name
        self.price = price
        self.changePercent = changePercent
        self.amount = amount
        self.volumeRatio = volumeRatio
    }
}

public enum StockSortKey: String, CaseIterable, Sendable {
    /// 伺服器上的自選順序。
    case custom
    case name, price, changePercent, amount, volumeRatio
    /// 今日頁「異動大」：看漲跌幅絕對值。
    case moveMagnitude
}

public struct StockSort: Hashable, Sendable {
    public var key: StockSortKey
    public var ascending: Bool

    public static let custom = StockSort(key: .custom, ascending: false)
    public static let biggestMove = StockSort(key: .moveMagnitude, ascending: false)

    public init(key: StockSortKey, ascending: Bool) {
        self.key = key
        self.ascending = ascending
    }

    /// 存進 UserDefaults 的字串；認不得就回 nil，呼叫端退回預設。
    public init?(storage: String) {
        let parts = storage.split(separator: ":").map(String.init)
        guard parts.count == 2, let key = StockSortKey(rawValue: parts[0]), ["asc", "desc"].contains(parts[1]) else { return nil }
        self.init(key: key, ascending: parts[1] == "asc")
    }

    public var storage: String { "\(key.rawValue):\(ascending ? "asc" : "desc")" }

    /// 點欄頭：第一下用該欄慣用方向（名稱遞增、數字遞減），第二下反向，第三下回自訂。
    public func tapped(_ tappedKey: StockSortKey) -> StockSort {
        let firstAscending = tappedKey == .name
        guard tappedKey == key else { return StockSort(key: tappedKey, ascending: firstAscending) }
        return ascending == firstAscending ? StockSort(key: key, ascending: !ascending) : .custom
    }

    /// 右欄換欄位時，若正依右欄排序就跟著換，不然畫面排序會對不上看到的數字。
    public func switching(to metric: StockRowMetric) -> StockSort {
        guard StockRowMetric.allCases.contains(where: { $0.sortKey == key }) else { return self }
        return StockSort(key: metric.sortKey, ascending: ascending)
    }

    /// 沒有讀數的一律排最後，不論升降；同值維持原順序。
    public func apply(to entries: [StockListEntry]) -> [StockListEntry] {
        guard key != .custom else { return entries }
        return entries.enumerated().sorted { lhs, rhs in
            let order = key == .name ? compareNames(lhs.element, rhs.element) : compareValues(lhs.element, rhs.element)
            return order ?? (lhs.offset < rhs.offset)
        }.map(\.element)
    }

    private func compareNames(_ lhs: StockListEntry, _ rhs: StockListEntry) -> Bool? {
        let result = (lhs.name ?? lhs.code).localizedStandardCompare(rhs.name ?? rhs.code)
        if result == .orderedSame { return nil }
        return ascending ? result == .orderedAscending : result == .orderedDescending
    }

    private func compareValues(_ lhs: StockListEntry, _ rhs: StockListEntry) -> Bool? {
        switch (value(lhs), value(rhs)) {
        case (nil, nil): return nil
        case (nil, _): return false
        case (_, nil): return true
        case let (left?, right?):
            if left == right { return nil }
            return ascending ? left < right : left > right
        }
    }

    private func value(_ entry: StockListEntry) -> Double? {
        let raw: Double?
        switch key {
        case .price: raw = entry.price
        case .changePercent: raw = entry.changePercent
        case .amount: raw = entry.amount
        case .volumeRatio: raw = entry.volumeRatio
        case .moveMagnitude: raw = entry.changePercent.map(abs)
        case .custom, .name: raw = nil
        }
        return raw?.isFinite == true ? raw : nil
    }
}

public extension DecisionAction {
    /// 要使用者動手的動作；續抱、觀望不算。
    var isActionable: Bool {
        switch self {
        case .buy, .add, .avoid, .reduce, .sell, .alert: return true
        case .hold, .watch: return false
        }
    }
}

/// Watchlist "AI 建議" filter: only buy / add / reduce / sell qualify; watch, hold, avoid and alert do not.
public enum AIAdviceFilter {
    public static func qualifies(_ action: DecisionAction?) -> Bool {
        switch action {
        case .buy, .add, .reduce, .sell: return true
        case .hold, .watch, .avoid, .alert, nil: return false
        }
    }

    public static func count(_ actions: [DecisionAction?]) -> Int {
        actions.filter(qualifies).count
    }

    /// Keeps the original order; returns `items` unchanged when `enabled` is false.
    public static func apply<Item>(_ items: [Item], enabled: Bool, action: (Item) -> DecisionAction?) -> [Item] {
        guard enabled else { return items }
        return items.filter { qualifies(action($0)) }
    }
}

/// 自選頁摘要列：漲跌家數、動作數、最新報價時間。
public struct StockListSummary: Equatable, Sendable {
    public let up: Int
    public let down: Int
    public let flat: Int
    public let actionCount: Int
    /// N in "AI 建議 N 檔"; see `AIAdviceFilter` for which actions count.
    public let adviceCount: Int
    public let latestQuoteAt: String?

    public init(entries: [StockListEntry], actions: [DecisionAction?], quoteTimes: [String?]) {
        let changes = entries.compactMap(\.changePercent).filter(\.isFinite)
        up = changes.filter { $0 > 0 }.count
        down = changes.filter { $0 < 0 }.count
        flat = changes.filter { $0 == 0 }.count
        actionCount = actions.compactMap { $0 }.filter(\.isActionable).count
        adviceCount = AIAdviceFilter.count(actions)
        latestQuoteAt = quoteTimes.compactMap { $0 }.max { lhs, rhs in
            // 時區不同的字串不能直接比，解析不了的排最前（最不新）。
            (Self.parse(lhs) ?? .distantPast) < (Self.parse(rhs) ?? .distantPast)
        }
    }

    /// Spoken form of "▲3 ▼2 ─1"; VoiceOver cannot read the symbols meaningfully.
    public var breadthAccessibilityLabel: String {
        "上漲 \(up) 檔，下跌 \(down) 檔，平盤 \(flat) 檔"
    }

    private static func parse(_ value: String) -> Date? {
        let parser = ISO8601DateFormatter()
        parser.formatOptions = value.contains(".") ? [.withInternetDateTime, .withFractionalSeconds] : [.withInternetDateTime]
        return parser.date(from: value)
    }
}

/// 自選清單四種內容狀態互斥：錯誤與「沒有自選」不能同時出現。
public enum StockListContentState: Equatable, Sendable {
    case loading
    case failed(String)
    case empty
    case ready(StockListBanner?)

    /// - Parameters:
    ///   - codeCount: 這個市場的自選檔數（未套篩選）。
    ///   - hasLoaded: 至少完成過一輪更新；沒完成前空清單代表還在載入，不是沒有自選。
    public static func resolve(codeCount: Int, hasLoaded: Bool, listError: String?, quoteError: String?, missingQuotes: Int) -> StockListContentState {
        guard codeCount > 0 else {
            if let listError { return .failed(listError) }
            return hasLoaded ? .empty : .loading
        }
        if let listError { return .ready(.refreshFailed(listError)) }
        if let quoteError { return .ready(.quotesFailed(quoteError)) }
        return .ready(missingQuotes > 0 ? .partialQuotes(missingQuotes) : nil)
    }
}

public enum StockListBanner: Equatable, Sendable {
    /// 名單更新失敗，畫面是上次的資料。
    case refreshFailed(String)
    /// 名單是新的，報價整批失敗。
    case quotesFailed(String)
    /// 少數幾檔沒有報價。
    case partialQuotes(Int)

    public var title: String {
        switch self {
        case .refreshFailed: return "更新失敗，顯示上次的資料"
        case .quotesFailed: return "報價暫時無法取得"
        case let .partialQuotes(count): return "\(count) 檔沒有報價"
        }
    }

    public var canRetry: Bool {
        if case .partialQuotes = self { return false }
        return true
    }
}

public enum MarketPhaseLabel {
    /// 對應後端 MarketPhase；unknown 與沒見過的值不顯示，不猜。
    public static func text(_ phase: String?) -> String? {
        switch phase {
        case "premarket": return "盤前"
        case "intraday": return "盤中"
        case "lunch_break": return "午休"
        case "closing_auction": return "收盤競價"
        case "postmarket": return "盤後"
        case "non_trading": return "休市"
        default: return nil
        }
    }
}

/// 今日頁的資產摘要。
public struct TodayAssetSummary: Equatable, Sendable {
    public let currency: String
    public let equity: Double?
    /// 只有全帳戶換算成功才有；不同幣別的今日損益不能直接相加。
    public let dayPnl: Double?
    /// false 表示沒能換算成單一幣別，只顯示其中一個幣別的帳戶。
    public let consolidated: Bool
}

public extension PortfolioSnapshot {
    /// 優先用後端依 display_currency 換算的合計；換算不了就退回單一原幣分組，絕不把頂層 CNY 數字重標幣別。
    var todayAssetSummary: TodayAssetSummary? {
        guard hasAnyAssets, !fundOnlyValueUnknown else { return nil }
        if let displayCurrency, let equity = consolidatedEquityBase ?? (accounts.isEmpty ? 0 : nil), consolidatedFxMissing != true {
            // 與資產頁 `overview` 同口徑：基金加進總資產與今日損益，讀不到基金時只算帳本。
            return TodayAssetSummary(currency: displayCurrency, equity: equity + (consolidatedFundValueBase ?? 0),
                                     dayPnl: combinedDayPnl,
                                     consolidated: true)
        }
        guard let first = currencyTotals.first else { return nil }
        return TodayAssetSummary(currency: first.currency, equity: first.totalEquity, dayPnl: nil,
                                 consolidated: currencyTotals.count == 1)
    }

    /// 持股代號集合，鍵見 `StockHoldings.key`。
    var heldKeys: Set<String> {
        Set(accounts.flatMap(\.positions).filter { $0.quantity > 0 }.map { StockHoldings.key($0.symbol) })
    }
}

public enum StockHoldings {
    /// 帳本的 symbol 與自選代號不保證都帶市場後綴，去後綴比對；台股數字開頭、美股字母開頭，不會互撞。
    public static func key(_ code: String) -> String {
        StockCodeDisplay.display(code).uppercased()
    }
}
