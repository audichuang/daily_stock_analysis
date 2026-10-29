import Foundation

enum WebNavigationPolicy {
    enum Action: Equatable { case allow, download, external, cancel }

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
