import Foundation

/// 安裝既有版本後，選擇使用者自訂網址或新版預設入口。
public enum ServerAddressSelection {
    public static func initial(saved: String?, currentDefault: String, previousDefault: String?, lastSeenDefault: String? = nil) -> String {
        guard let saved else { return currentDefault }
        guard lastSeenDefault != currentDefault,
              let previousDefault,
              let savedIdentity = identity(saved),
              let previousIdentity = identity(previousDefault),
              identity(currentDefault) != nil,
              savedIdentity == previousIdentity else { return saved }
        return currentDefault
    }

    private static func identity(_ value: String) -> String? {
        guard var parts = URLComponents(string: value),
              parts.scheme?.lowercased() == "https", let host = parts.host, !host.isEmpty,
              parts.user == nil, parts.password == nil, parts.query == nil, parts.fragment == nil else { return nil }
        parts.scheme = "https"
        parts.host = host.lowercased()
        if parts.port == 443 { parts.port = nil }
        if parts.percentEncodedPath.isEmpty { parts.percentEncodedPath = "/" }
        return parts.url?.absoluteString
    }
}
