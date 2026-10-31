import Foundation
import Security
import DSACore

enum AccessVault {
    private static var service: String { (Bundle.main.bundleIdentifier ?? "DSAMarket") + ".cloudflare-access" }

    static func load(for url: URL) throws -> AccessCredentials? {
        var query = key(for: url)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = result as? Data else { throw VaultError() }
        do { return try JSONDecoder().decode(AccessCredentials.self, from: data) }
        catch { throw VaultError() }
    }

    static func save(_ credentials: AccessCredentials, for url: URL) throws {
        let values: [String: Any] = [
            kSecValueData as String: try JSONEncoder().encode(credentials),
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        ]
        let query = key(for: url)
        let status = SecItemUpdate(query as CFDictionary, values as CFDictionary)
        if status == errSecItemNotFound {
            let item = query.merging(values) { _, new in new }
            guard SecItemAdd(item as CFDictionary, nil) == errSecSuccess else { throw VaultError() }
        } else if status != errSecSuccess { throw VaultError() }
    }

    static func remove(for url: URL) throws {
        let status = SecItemDelete(key(for: url) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw VaultError() }
    }

    private static func key(for url: URL) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: ServiceOrigin.key(url)]
    }

    private struct VaultError: LocalizedError {
        var errorDescription: String? { "無法讀寫 Cloudflare Access 安全憑證，請解鎖裝置後重試。" }
    }
}
