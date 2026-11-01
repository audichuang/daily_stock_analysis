import Foundation

/// Web tool paths opened from native screens (ToolWebView). Built with URLComponents
/// so names such as「台積電」or values containing & / = are percent-encoded.
public enum ToolLinks {
    public enum AlertDirection: String, Sendable {
        case above
        case below
    }

    // Query values must not leave &, =, + or # raw: they would split or rewrite the query.
    private static let valueAllowed: CharacterSet = {
        var set = CharacterSet.urlQueryAllowed
        set.remove(charactersIn: "&=+#?/")
        return set
    }()

    private static func path(_ base: String, _ items: [(String, String?)]) -> String {
        var components = URLComponents()
        components.path = base
        let encoded = items.compactMap { name, value -> URLQueryItem? in
            guard let value = value?.trimmingCharacters(in: .whitespacesAndNewlines), !value.isEmpty else { return nil }
            return URLQueryItem(name: name, value: value.addingPercentEncoding(withAllowedCharacters: valueAllowed))
        }
        components.percentEncodedQueryItems = encoded.isEmpty ? nil : encoded
        return components.string ?? base
    }

    /// `/chat?stock=&name=&recordId=`; empty values are omitted.
    public static func chatPath(code: String, name: String? = nil, recordID: Int? = nil) -> String {
        path("/chat", [("stock", code), ("name", name), ("recordId", recordID.map(String.init))])
    }

    /// `/alerts?new=1&target=&type=price_cross&direction=&price=`; the price is omitted
    /// unless it is a finite positive number.
    public static func alertPath(code: String, direction: AlertDirection, price: Double?) -> String {
        var priceText: String?
        if let price, price.isFinite, price > 0 {
            priceText = price.formatted(.number.locale(Locale(identifier: "en_US_POSIX")).grouping(.never).precision(.fractionLength(0...4)))
        }
        return path("/alerts", [
            ("new", "1"),
            ("target", code),
            ("type", "price_cross"),
            ("direction", direction.rawValue),
            ("price", priceText),
        ])
    }

    /// `/portfolio?entry=`
    public static func portfolioPath(entry: String) -> String {
        path("/portfolio", [("entry", entry)])
    }
}
