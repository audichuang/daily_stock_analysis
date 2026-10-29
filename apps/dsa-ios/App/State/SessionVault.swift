import Foundation
import Security

enum SessionVault {
    private struct CookieRecord: Codable {
        let name: String
        let value: String
        let domain: String
        let path: String
        let secure: Bool
        let httpOnly: Bool
        let sameSite: String?
        let expires: Date?
    }

    private static var service: String { (Bundle.main.bundleIdentifier ?? "DSAMarket") + ".session" }

    static func save(_ storage: HTTPCookieStorage?, for url: URL) throws {
        let cookies = (storage?.cookies(for: url) ?? []).filter { $0.name == "dsa_session" }
        let records = cookies.map {
            CookieRecord(name: $0.name, value: $0.value, domain: $0.domain,
                         path: $0.path, secure: $0.isSecure, httpOnly: $0.isHTTPOnly,
                         sameSite: $0.properties?[HTTPCookiePropertyKey(rawValue: "SameSite")] as? String,
                         expires: $0.expiresDate)
        }
        let data = try JSONEncoder().encode(records)
        let query = key(for: url)
        let update = SecItemUpdate(query as CFDictionary, [kSecValueData: data] as CFDictionary)
        if update == errSecItemNotFound {
            var item = query
            item[kSecValueData as String] = data
            item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
            let result = SecItemAdd(item as CFDictionary, nil)
            guard result == errSecSuccess else { throw VaultError(status: result) }
        } else if update != errSecSuccess {
            throw VaultError(status: update)
        }
    }

    static func restore(into storage: HTTPCookieStorage?, for url: URL) {
        var query = key(for: url)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data,
              let records = try? JSONDecoder().decode([CookieRecord].self, from: data) else { return }
        for record in records {
            guard record.name == "dsa_session", record.expires.map({ $0 > Date() }) ?? true else { continue }
            var properties: [HTTPCookiePropertyKey: Any] = [
                .name: record.name, .value: record.value, .domain: record.domain,
                .path: record.path
            ]
            if record.secure { properties[.secure] = "TRUE" }
            if record.httpOnly { properties[HTTPCookiePropertyKey(rawValue: "HttpOnly")] = "TRUE" }
            if let sameSite = record.sameSite { properties[HTTPCookiePropertyKey(rawValue: "SameSite")] = sameSite }
            if let expires = record.expires { properties[.expires] = expires }
            if let cookie = HTTPCookie(properties: properties) { storage?.setCookie(cookie) }
        }
    }

    static func clear(for url: URL) {
        SecItemDelete(key(for: url) as CFDictionary)
    }

    private static func key(for url: URL) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: url.absoluteString]
    }

    private struct VaultError: LocalizedError {
        let status: OSStatus
        var errorDescription: String? { "登入成功，但無法安全保存登入狀態（\(status)）。下次開啟可能需要重新登入。" }
    }
}
