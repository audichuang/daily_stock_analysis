import Foundation
import SwiftUI
import DSACore

@MainActor
final class AppStore: ObservableObject {
    @Published var connected = false
    @Published var connecting = false
    @Published var needsPassword = false
    @Published var connectionError: String?
    @Published var serverAddress: String
    @Published var watchlist: [String] = []
    @Published var quotes: [QuoteItem] = []
    @Published var indices: [MarketIndex] = []
    @Published var reports: [HistoryItem] = []
    @Published var marketReviews: [HistoryItem] = []
    @Published var refreshing = false
    @Published var errors: [String: String] = [:]
    @Published var refreshedAt: Date?
    @Published var selectedMarket = "tw"
    @Published var selectedTab = 0
    @Published var stockIndex: [StockIndexItem] = []
    @Published var colorConvention: MarketColorConvention {
        didSet { UserDefaults.standard.set(colorConvention.rawValue, forKey: "marketColors") }
    }
    private(set) var client: DSAClient?
    private(set) var session: URLSession?
    private(set) var baseURL: URL?
    private var generation = UUID()
    private let configurationFactory: () -> URLSessionConfiguration

    init(configurationFactory: @escaping () -> URLSessionConfiguration = { .ephemeral }) {
        self.configurationFactory = configurationFactory
        colorConvention = MarketColorConvention(rawValue: UserDefaults.standard.string(forKey: "marketColors") ?? "") ?? .taiwan
        let preferences = UserDefaults.standard
        let savedAddress = preferences.string(forKey: "serverAddress")
        let currentDefault = Bundle.main.object(forInfoDictionaryKey: "DSAServerURL") as? String ?? ""
        serverAddress = ServerAddressSelection.initial(
            saved: savedAddress, currentDefault: currentDefault,
            previousDefault: Bundle.main.object(forInfoDictionaryKey: "DSAPreviousServerURL") as? String,
            lastSeenDefault: preferences.string(forKey: "lastDefaultServerURL")
        )
        // 同一預設入口只移轉一次；之後使用者明確改回舊網址仍須尊重。
        if !currentDefault.isEmpty {
            if let savedAddress, serverAddress != savedAddress {
                preferences.set(serverAddress, forKey: "serverAddress")
            }
            preferences.set(currentDefault, forKey: "lastDefaultServerURL")
        }
        #if DEBUG
        if let fixtureURL = ProcessInfo.processInfo.environment["DSA_TEST_SERVER"] {
            serverAddress = fixtureURL
        }
        #endif
    }

    func connect(password: String? = nil) async {
        guard !connecting else { return }
        connecting = true
        connectionError = nil
        defer { connecting = false }
        do {
            guard let url = URL(string: serverAddress.trimmingCharacters(in: .whitespacesAndNewlines)) else {
                throw LocalError("請輸入完整的 HTTPS 服務網址。")
            }
            if baseURL != url || client == nil {
                let config = configurationFactory()
                config.timeoutIntervalForRequest = 60
                config.timeoutIntervalForResource = 180
                config.requestCachePolicy = .reloadIgnoringLocalCacheData
                let candidateSession = URLSession(configuration: config)
                let candidateClient: DSAClient
                do { candidateClient = try DSAClient(baseURL: url, session: candidateSession) }
                catch { candidateSession.invalidateAndCancel(); throw error }
                session?.invalidateAndCancel()
                generation = UUID()
                clearData()
                session = candidateSession
                client = candidateClient
                baseURL = url
                SessionVault.restore(into: candidateSession.configuration.httpCookieStorage, for: url)
            }
            guard let client else { return }
            if let password { try await client.login(password: password) }
            let status = try await client.authStatus()
            needsPassword = status.authEnabled && status.passwordSet && !status.loggedIn
            if status.authEnabled && !status.passwordSet {
                throw LocalError("請先在網頁完成管理員密碼設定，再連接 App。")
            }
            if needsPassword { return }
            connected = true
            UserDefaults.standard.set(url.absoluteString, forKey: "serverAddress")
            do { try SessionVault.save(session?.configuration.httpCookieStorage, for: url) }
            catch { errors["session"] = error.localizedDescription }
            await refresh()
        } catch {
            connectionError = error.localizedDescription
        }
    }

    /// `.refreshable` 的 task 由 SwiftUI 擁有：refresh 途中 store 先發布的結果會讓它被取消，
    /// 還在等的報價請求就以「已取消」失敗。改由 store 自己的 Task 執行，呼叫端只等它完成。
    func refresh() async {
        await Task { await performRefresh() }.value
    }

    private func performRefresh() async {
        guard let client, connected, !refreshing else { return }
        refreshing = true
        let currentGeneration = generation
        async let watch: Void = loadWatchlist(client, generation: currentGeneration)
        async let market: Void = loadIndices(client, generation: currentGeneration)
        async let history: Void = loadReports(client, generation: currentGeneration)
        _ = await (watch, market, history)
        guard generation == currentGeneration else { return }
        refreshing = false
        refreshedAt = Date()
    }

    func changeMarket(_ market: String) async {
        selectedMarket = market
        guard let client, connected else { return }
        indices = []
        await loadIndices(client, generation: generation)
    }

    func loadIndex() async throws {
        guard stockIndex.isEmpty, let client else { return }
        stockIndex = try await client.stockIndex()
    }

    func toggleWatchlist(_ code: String) async throws {
        guard let client else { return }
        watchlist = try await (watchlist.contains(code) ? client.removeFromWatchlist(code) : client.addToWatchlist(code))
        await loadWatchlist(client, generation: generation)
    }

    func logout() async {
        if let baseURL { SessionVault.clear(for: baseURL) }
        session?.configuration.httpCookieStorage?.cookies?.forEach { session?.configuration.httpCookieStorage?.deleteCookie($0) }
        session?.invalidateAndCancel()
        generation = UUID()
        client = nil
        session = nil
        baseURL = nil
        connected = false
        needsPassword = false
        refreshing = false
        clearData()
    }

    func quote(for code: String) -> StockQuote? { quotes.first { $0.stockCode == code }?.quote }
    func latestReport(for code: String) -> HistoryItem? { reports.first { $0.stockCode == code } }
    func isInMarket(_ code: String) -> Bool {
        switch selectedMarket {
        case "tw": return code.range(of: #"^[0-9]{4,6}[A-Za-z]?\.[Tt][Ww](?:[Oo])?$"#, options: .regularExpression) != nil
        case "us": return code.range(of: #"^[A-Za-z]{1,5}(?:[.-](?:[Uu][Ss]|[A-Za-z]))?$"#, options: .regularExpression) != nil
        default: return false
        }
    }

    private func loadWatchlist(_ client: DSAClient, generation expected: UUID) async {
        do {
            let codes = try await client.watchlist()
            var results: [QuoteItem] = []
            for start in stride(from: 0, to: codes.count, by: 50) {
                results += try await client.quotes(Array(codes[start..<min(start + 50, codes.count)]))
            }
            guard generation == expected else { return }
            watchlist = codes
            quotes = results
            errors["watchlist"] = nil
        } catch { if generation == expected { errors["watchlist"] = error.localizedDescription } }
    }

    private func loadIndices(_ client: DSAClient, generation expected: UUID) async {
        let region = selectedMarket
        do {
            let values = try await client.indices(region: region)
            guard generation == expected, region == selectedMarket else { return }
            indices = values
            errors["indices"] = nil
        } catch { if generation == expected, region == selectedMarket { errors["indices"] = error.localizedDescription } }
    }

    private func loadReports(_ client: DSAClient, generation expected: UUID) async {
        do {
            async let stocks = client.historyList(limit: 50)
            async let market = client.historyList(reportType: "market_review", limit: 5)
            let (stockPage, marketPage) = try await (stocks, market)
            guard generation == expected else { return }
            reports = stockPage.items.filter { $0.reportType != "market_review" }
            marketReviews = marketPage.items
            errors["reports"] = nil
        } catch { if generation == expected { errors["reports"] = error.localizedDescription } }
    }

    private func clearData() {
        watchlist = []; quotes = []; indices = []; reports = []; marketReviews = []
        stockIndex = []; errors = [:]; refreshedAt = nil
    }
}

struct LocalError: LocalizedError {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}

enum DisplayFormat {
    static func number(_ value: Double?, digits: Int = 2) -> String {
        guard let value, value.isFinite else { return "—" }
        return value.formatted(.number.precision(.fractionLength(0...digits)))
    }
    static func percent(_ value: Double?) -> String {
        guard let value, value.isFinite else { return "—" }
        return (value > 0 ? "+" : "") + value.formatted(.number.precision(.fractionLength(2))) + "%"
    }
    static func source(_ value: String?) -> String {
        switch value?.lowercased() {
        case "shioaji": return "Shioaji"
        case "fallback": return "備援報價 · 可能延遲"
        case "official_close": return "官方收盤"
        case "yfinance": return "Yahoo Finance · 可能延遲"
        case "marketdb": return "歷史行情庫"
        case .some(let name): return name
        case nil: return "來源未提供"
        }
    }
    static func time(_ value: String?, timeZone: TimeZone = .current) -> String {
        guard let value, !value.isEmpty else { return "時間未提供" }
        let parser = ISO8601DateFormatter()
        parser.formatOptions = [.withInternetDateTime]
        if value.contains(".") { parser.formatOptions.insert(.withFractionalSeconds) }
        if let date = parser.date(from: value) {
            let formatter = DateFormatter()
            formatter.locale = Locale(identifier: "en_US_POSIX")
            formatter.timeZone = timeZone
            formatter.dateFormat = "yyyy/MM/dd HH:mm zzz"
            return formatter.string(from: date)
        }
        // 無時區的後端歷史字串保留原值，避免擅自換算成手機時區。
        return value.replacingOccurrences(of: "T", with: " ")
    }
    static func date(_ value: String) -> Date? {
        TradingDay.parse(value)
    }
}
