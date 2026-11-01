import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

/// 連線畫面要把錯誤貼在哪個欄位旁邊。
public enum ConnectionField: Sendable, Equatable {
    case address, password, access, general
}

/// 依錯誤類型與後端 `error` 代碼決定位置與繁中文案，不比對訊息文字。
public struct ConnectionIssue: Sendable, Equatable {
    public let field: ConnectionField
    public let message: String

    public init(field: ConnectionField, message: String) {
        self.field = field
        self.message = message
    }

    public static func from(_ error: Error) -> ConnectionIssue {
        if let error = error as? DSAError { return classify(error) }
        if let error = error as? URLError { return classify(error) }
        return ConnectionIssue(field: .general, message: error.localizedDescription)
    }

    private static func classify(_ error: DSAError) -> ConnectionIssue {
        let description = error.errorDescription ?? "連線失敗。"
        switch error {
        case .invalidServerURL: return ConnectionIssue(field: .address, message: description)
        case .cloudflareAccess: return ConnectionIssue(field: .access, message: description)
        case .invalidResponse, .decoding: return ConnectionIssue(field: .general, message: description)
        case let .http(status, code, message):
            switch code {
            case "invalid_password": return ConnectionIssue(field: .password, message: "密碼不正確，請再試一次。")
            case "password_required": return ConnectionIssue(field: .password, message: "請輸入管理員密碼。")
            case "rate_limited": return ConnectionIssue(field: .password, message: "嘗試次數過多，請稍後再試。")
            case "unauthorized": return ConnectionIssue(field: .password, message: "登入已過期，請重新登入。")
            case "auth_disabled": return ConnectionIssue(field: .general, message: "這個服務沒有啟用密碼登入。")
            default: break
            }
            if status == 401 { return ConnectionIssue(field: .password, message: "登入已過期，請重新登入。") }
            if status == 429 { return ConnectionIssue(field: .password, message: "嘗試次數過多，請稍後再試。") }
            return ConnectionIssue(field: .general, message: message)
        }
    }

    private static func classify(_ error: URLError) -> ConnectionIssue {
        switch error.code {
        case .notConnectedToInternet, .networkConnectionLost, .dataNotAllowed:
            return ConnectionIssue(field: .general, message: "目前沒有網路連線，請確認網路後再試。")
        case .timedOut:
            return ConnectionIssue(field: .general, message: "連線逾時，服務可能正在啟動或網路不穩。")
        case .cannotFindHost, .dnsLookupFailed, .cannotConnectToHost, .unsupportedURL, .badURL:
            return ConnectionIssue(field: .address, message: "連不到這個服務，請確認網址是否正確。")
        case .secureConnectionFailed, .serverCertificateUntrusted, .serverCertificateHasBadDate,
             .serverCertificateHasUnknownRoot, .serverCertificateNotYetValid:
            return ConnectionIssue(field: .address, message: "無法驗證服務的安全憑證，請確認網址是否正確。")
        default:
            return ConnectionIssue(field: .general, message: error.localizedDescription)
        }
    }
}

public enum ServerAddress {
    /// 去頭尾空白與結尾斜線，沒寫 scheme 補 https；信任邊界仍由 `DSAClient.validateServerURL` 把關。
    public static func normalized(_ raw: String) -> URL? {
        var text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !text.contains(where: { $0.isWhitespace }) else { return nil }
        if !text.contains("://") { text = "https://" + text }
        while text.hasSuffix("/") { text.removeLast() }
        guard let url = URL(string: text), url.host?.isEmpty == false else { return nil }
        return url
    }
}
