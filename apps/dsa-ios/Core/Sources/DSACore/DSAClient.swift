import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

public enum DSAError: Error, LocalizedError, Sendable {
    case invalidServerURL
    case invalidResponse
    case http(status: Int, code: String?, message: String)
    case decoding(String)
    case cloudflareAccess

    public var errorDescription: String? {
        switch self {
        case .invalidServerURL: return "請輸入有效的 HTTPS 伺服器網址。"
        case .invalidResponse: return "伺服器未傳回有效的 HTTP 回應。"
        case .cloudflareAccess: return "Cloudflare Access 驗證失敗，請檢查 Client ID／Secret"
        case let .http(_, _, message): return message
        case .decoding: return "伺服器資料格式與 App 不相容，請更新 App 或伺服器。"
        }
    }

    public var requiresLogin: Bool {
        if case .http(status: 401, _, _) = self { return true }
        return false
    }

    public var isNotFound: Bool {
        if case .http(status: 404, _, _) = self { return true }
        return false
    }
}

/// Session 由 App 注入；cookie 的隔離與 Keychain 持久化由 App 管理。
public struct DSAClient: Sendable {
    public let baseURL: URL
    private let session: URLSession
    private let access: CloudflareAccess?

    public init(baseURL: URL, session: URLSession, access: CloudflareAccess? = nil) throws {
        try Self.validateServerURL(baseURL)
        self.baseURL = baseURL
        self.session = session
        self.access = access
    }

    public static func validateServerURL(_ baseURL: URL) throws {
        guard let components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false),
              let scheme = components.scheme?.lowercased(),
              let host = components.host, !host.isEmpty,
              components.user == nil, components.password == nil,
              components.query == nil, components.fragment == nil,
              Self.isAllowed(scheme: scheme, host: host) else {
            throw DSAError.invalidServerURL
        }
    }

    private static func isAllowed(scheme: String, host: String) -> Bool {
        if scheme == "https" { return true }
        #if DEBUG
        return scheme == "http" && ["localhost", "127.0.0.1", "[::1]", "::1"].contains(host.lowercased())
        #else
        return false
        #endif
    }

    public func authStatus() async throws -> AuthStatus {
        try await get(["auth", "status"])
    }

    public func login(password: String) async throws {
        let _: Acknowledgement = try await post(["auth", "login"], body: PasswordBody(password: password))
    }

    public func logout() async throws {
        var request = URLRequest(url: try makeURL(path: ["auth", "logout"]))
        request.httpMethod = "POST"
        _ = try await responseData(request)
    }

    public func watchlist() async throws -> [String] {
        let response: Watchlist = try await get(["stocks", "watchlist"])
        return response.stockCodes
    }

    public func addToWatchlist(_ code: String) async throws -> [String] {
        let response: Watchlist = try await post(["stocks", "watchlist", "add"], body: StockBody(stockCode: code))
        return response.stockCodes
    }

    public func removeFromWatchlist(_ code: String) async throws -> [String] {
        let response: Watchlist = try await post(["stocks", "watchlist", "remove"], body: StockBody(stockCode: code))
        return response.stockCodes
    }

    public func quotes(_ codes: [String]) async throws -> [QuoteItem] {
        if codes.isEmpty { return [] }
        var items: [QuoteItem] = []
        // 伺服器明訂單次最多 50 檔，分批保留每檔缺價與錯誤狀態。
        for offset in stride(from: 0, to: codes.count, by: 50) {
            let batch = codes[offset..<min(offset + 50, codes.count)]
            let response: Items<QuoteItem> = try await get(["stocks", "quotes"], query: [URLQueryItem(name: "codes", value: batch.joined(separator: ","))])
            items.append(contentsOf: response.items)
        }
        return items
    }

    public func indices(region: String = "tw") async throws -> [MarketIndex] {
        let response: Items<MarketIndex> = try await get(["stocks", "indices"], query: [URLQueryItem(name: "region", value: region)])
        return response.items
    }

    public func stockProfile(_ code: String, historyDays: Int = 90) async throws -> StockProfile {
        try await get(["stocks", code, "profile"], query: [URLQueryItem(name: "history_days", value: String(historyDays))])
    }

    /// 分時走勢（`range=day`）：台股走 Shioaji 分鐘線、其他市場走 yfinance 5 分鐘線；只有價沒有量。
    public func stockTrend(_ code: String, range: String = "day") async throws -> StockTrend {
        try await get(["stocks", code, "trend"], query: [URLQueryItem(name: "range", value: range)])
    }

    public func historyList(stockCode: String? = nil, reportType: String? = nil, page: Int = 1, limit: Int = 20) async throws -> HistoryPage {
        var query = [URLQueryItem(name: "page", value: String(page)), URLQueryItem(name: "limit", value: String(limit))]
        if let stockCode { query.append(URLQueryItem(name: "stock_code", value: stockCode)) }
        if let reportType { query.append(URLQueryItem(name: "report_type", value: reportType)) }
        return try await get(["history"], query: query)
    }

    public func report(_ id: Int) async throws -> AnalysisReport {
        try await get(["history", String(id)])
    }

    public func reportMarkdown(_ id: Int) async throws -> String {
        let response: Markdown = try await get(["history", String(id), "markdown"])
        return response.content
    }

    public func startAnalysis(_ code: String) async throws -> AcceptedTask {
        try await post(["analysis", "analyze"], body: AnalysisBody(stockCode: code))
    }

    public func taskStatus(_ id: String) async throws -> AnalysisTask {
        try await get(["analysis", "status", id])
    }

    public func stockIndex() async throws -> [StockIndexItem] {
        let url = try makeURL(path: ["stocks.index.json"], api: false)
        return try await perform(URLRequest(url: url))
    }

    public func portfolioSnapshot() async throws -> PortfolioSnapshot {
        try await get(["portfolio", "snapshot"], query: [URLQueryItem(name: "include_realtime", value: "true")])
    }

    private func get<T: Decodable>(_ path: [String], query: [URLQueryItem] = []) async throws -> T {
        let url = try makeURL(path: path, query: query)
        return try await perform(URLRequest(url: url))
    }

    private func post<T: Decodable, Body: Encodable>(_ path: [String], body: Body) async throws -> T {
        let url = try makeURL(path: path)
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        request.httpBody = try encoder.encode(body)
        return try await perform(request)
    }

    private func makeURL(path: [String], query: [URLQueryItem] = [], api: Bool = true) throws -> URL {
        guard var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) else { throw DSAError.invalidServerURL }
        let allowed = CharacterSet.urlPathAllowed.subtracting(CharacterSet(charactersIn: "/%?#"))
        let segments = (api ? ["api", "v1"] : []) + path
        let encoded = try segments.map { segment -> String in
            guard segment != ".", segment != "..", let value = segment.addingPercentEncoding(withAllowedCharacters: allowed) else {
                throw DSAError.invalidServerURL
            }
            return value
        }
        components.percentEncodedPath = components.percentEncodedPath.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
            .split(separator: "/").map(String.init).joined(separator: "/")
        components.percentEncodedPath = "/" + ([components.percentEncodedPath].filter { !$0.isEmpty } + encoded).joined(separator: "/")
        components.queryItems = query.isEmpty ? nil : query
        guard let url = components.url else { throw DSAError.invalidServerURL }
        return url
    }

    private func perform<T: Decodable>(_ original: URLRequest) async throws -> T {
        let data = try await responseData(original)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw DSAError.decoding(String(describing: error))
        }
    }

    private func responseData(_ original: URLRequest) async throws -> Data {
        var request = original
        request.timeoutInterval = 60
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.cachePolicy = .reloadIgnoringLocalCacheData
        // 阻止 307/308 把登入密碼或寫入內容轉送到不同伺服器。
        request = access?.authorizing(request) ?? request
        let delegate = OriginRedirectDelegate(origin: baseURL, access: access)
        let (data, response) = try await session.data(for: request, delegate: delegate)
        guard let http = response as? HTTPURLResponse else { throw DSAError.invalidResponse }
        if (300..<400).contains(http.statusCode),
           let location = http.value(forHTTPHeaderField: "Location"),
           let destination = URL(string: location, relativeTo: http.url),
           CloudflareAccess.isLoginURL(destination) {
            throw DSAError.cloudflareAccess
        }
        guard (200..<300).contains(http.statusCode) else {
            throw Self.apiError(data: data, status: http.statusCode)
        }
        return data
    }

    private static func apiError(data: Data, status: Int) -> DSAError {
        let payload = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        let detail = payload?["detail"] as? [String: Any] ?? payload
        let code = detail?["error"] as? String
        let message = detail?["message"] as? String
        let defaultMessage: String
        switch status {
        case 401: defaultMessage = "登入已過期，請重新登入。"
        case 403: defaultMessage = "沒有存取這項功能的權限。"
        case 409: defaultMessage = "已有相同任務執行中，請稍後查看報告。"
        case 429: defaultMessage = "請求過於頻繁，請稍後再試。"
        default: defaultMessage = "伺服器回應錯誤（HTTP \(status)）。"
        }
        return .http(status: status, code: code, message: message ?? defaultMessage)
    }
}

final class OriginRedirectDelegate: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    private let origin: URL
    private let access: CloudflareAccess?
    init(origin: URL, access: CloudflareAccess? = nil) { self.origin = origin; self.access = access }

    func redirectedRequest(_ request: URLRequest) -> URLRequest? {
        guard let destination = request.url, ServiceOrigin.same(destination, origin) else { return nil }
        return access?.authorizing(request) ?? request
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(redirectedRequest(request))
    }
}

private struct Items<Item: Decodable>: Decodable { let items: [Item] }
private struct Watchlist: Decodable { let stockCodes: [String] }
private struct Acknowledgement: Decodable { let ok: Bool }
private struct Markdown: Decodable { let content: String }
private struct PasswordBody: Encodable { let password: String }
private struct StockBody: Encodable { let stockCode: String }
private struct AnalysisBody: Encodable {
    let stockCode: String
    let asyncMode = true
    let reportType = "detailed"
    let analysisPhase = "auto"
    let reportLanguage = "zh-TW"
    let forceRefresh = false
    let notify = false
}
