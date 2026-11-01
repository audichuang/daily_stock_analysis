import Foundation

enum WebNavigationPolicy {
    enum Action: Equatable { case allow, download, external, cancel }

    static func preservesAccessError(_ error: Error, blockedAccessRedirect: Bool) -> Bool {
        let failure = error as NSError
        // iOS 沒有匯出這個舊 WebKit 常數；102 是取消 policy 後實測收到的頁框中斷。
        return blockedAccessRedirect && failure.domain == "WebKitErrorDomain" && failure.code == 102
    }

    /// 工具頁一律帶 embed=ios，Web 端據此收掉自己的標頭、側欄與底部分頁。
    static func embeddedToolURL(path: String, baseURL: URL) -> URL? {
        guard let url = URL(string: path, relativeTo: baseURL)?.absoluteURL,
              var components = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return nil }
        var items = components.queryItems ?? []
        if !items.contains(where: { $0.name == "embed" }) { items.append(URLQueryItem(name: "embed", value: "ios")) }
        components.queryItems = items
        return components.url
    }

    /// `.download` 決策後主頁框的載入可能以 102 中斷；那不是載入失敗，整頁錯誤會把進行中的下載一起收掉。
    static func isDownloadInterruption(_ error: Error, downloadStarting: Bool) -> Bool {
        let failure = error as NSError
        return downloadStarting && failure.domain == "WebKitErrorDomain" && failure.code == 102
    }

    static func pageLoadMessage(for error: Error) -> String {
        (error as NSError).domain == NSURLErrorDomain
            ? "無法連線到分析服務，請確認網路後重試。"
            : "工具頁載入失敗，請重試。"
    }

    static func sourceOrigin(protocolValue: String, host: String, port: Int) -> URL? {
        guard ["http", "https"].contains(protocolValue.lowercased()), !host.isEmpty else { return nil }
        var source = URLComponents()
        source.scheme = protocolValue
        source.host = host
        // WKSecurityOrigin 將缺省／協定預設 port 表成 0；保留 nil 才能與 HTTPS 443 同源。
        if port != 0 { source.port = port }
        return source.url
    }

    static func sameOrigin(_ lhs: URL, _ rhs: URL) -> Bool {
        guard ["http", "https"].contains(lhs.scheme?.lowercased() ?? ""),
              lhs.user == nil, lhs.password == nil, rhs.user == nil, rhs.password == nil else { return false }
        return lhs.scheme?.lowercased() == rhs.scheme?.lowercased()
            && lhs.host?.lowercased() == rhs.host?.lowercased()
            && effectivePort(lhs) == effectivePort(rhs)
    }

    static func trustedDownload(_ url: URL, baseURL: URL) -> Bool {
        if sameOrigin(url, baseURL) { return true }
        guard url.scheme?.lowercased() == "blob",
              let creatorURL = URL(string: String(url.absoluteString.dropFirst(5))) else { return false }
        return sameOrigin(creatorURL, baseURL)
    }

    static func action(url: URL, baseURL: URL, sourceOrigin: URL?, shouldDownload: Bool, userLink: Bool) -> Action {
        if url.scheme?.lowercased() == "blob" {
            guard shouldDownload, trustedDownload(url, baseURL: baseURL),
                  let sourceOrigin, sameOrigin(sourceOrigin, baseURL) else { return .cancel }
            return .download
        }
        if sameOrigin(url, baseURL) { return shouldDownload ? .download : .allow }
        if userLink && ["http", "https"].contains(url.scheme?.lowercased() ?? "") { return .external }
        return .cancel
    }

    static func safeFilename(_ suggested: String) -> String {
        let last = suggested.replacingOccurrences(of: "\\", with: "/").split(separator: "/").last.map(String.init) ?? ""
        let forbidden = CharacterSet.controlCharacters.union(CharacterSet(charactersIn: ":/\\"))
        let cleaned = String(last.unicodeScalars.filter { !forbidden.contains($0) }.map(Character.init))
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "."))
        // 每個 Unicode scalar 至多 4 bytes；60 字元不會超過常見 255-byte 檔名限制。
        let bounded = String(String.UnicodeScalarView(cleaned.unicodeScalars.prefix(60)))
        return bounded.isEmpty ? "export" : bounded
    }

    private static func effectivePort(_ url: URL) -> Int {
        url.port ?? (url.scheme?.lowercased() == "https" ? 443 : 80)
    }
}
