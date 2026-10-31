import Foundation

/// 後端的結構化動作枚舉；顯示文字與語意色依 docs/glossary-zh-tw.md，Web 對應 utils/decisionAction.ts。
public enum DecisionAction: String, CaseIterable, Sendable {
    case buy, add, hold, watch, avoid, reduce, sell, alert

    public var displayLabel: String {
        switch self {
        case .buy: return "買進"
        case .add: return "加碼"
        case .hold: return "續抱"
        case .watch: return "觀望"
        case .avoid: return "迴避"
        case .reduce: return "減碼"
        case .sell: return "賣出"
        case .alert: return "警報"
        }
    }

    // 各時期存檔的動作標籤。只比對整個標籤，不掃子字串，「不建議買進」不能被當成買進。
    private static let labelAliases: [String: DecisionAction] = [
        "買進": .buy, "買入": .buy, "买入": .buy,
        "加碼": .add, "加倉": .add, "加仓": .add,
        "續抱": .hold, "持有": .hold,
        "觀望": .watch, "观望": .watch,
        "迴避": .avoid, "回避": .avoid,
        "減碼": .reduce, "減倉": .reduce, "减仓": .reduce,
        "賣出": .sell, "卖出": .sell,
        "警報": .alert, "預警": .alert, "预警": .alert
    ]

    /// 枚舉優先；舊報告沒有枚舉時才看標籤是否為已知動作詞。
    public static func resolve(action: String?, label: String?) -> DecisionAction? {
        if let action, let value = DecisionAction(rawValue: action.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()) {
            return value
        }
        guard let label else { return nil }
        return labelAliases[label.trimmingCharacters(in: .whitespacesAndNewlines)]
    }

    /// 畫面要顯示的動作文字：已知動作走詞彙表，自由文字保留原文，全空回 nil。
    public static func displayText(action: String?, label: String?, advice: String? = nil) -> String? {
        if let resolved = resolve(action: action, label: label) { return resolved.displayLabel }
        for candidate in [label, advice] {
            guard let text = candidate?.trimmingCharacters(in: .whitespacesAndNewlines), !text.isEmpty else { continue }
            return labelAliases[text]?.displayLabel ?? text
        }
        return nil
    }
}

/// 數字顯示的共用規則：千分位、U+2212 負號，沒有讀數顯示 —。與 Web utils/format.ts 同一套。
public enum DisplayNumber {
    public static let minusSign = "\u{2212}"
    public static let noValue = "—"

    private static let locale = Locale(identifier: "zh_TW")

    private static func grouped(_ value: Double, minDigits: Int, maxDigits: Int) -> String {
        let text = abs(value).formatted(.number.locale(locale).precision(.fractionLength(minDigits...maxDigits)))
        // 四捨五入後變 0 不帶負號，避免「−0.00」。
        let roundsToZero = !text.contains(where: { ("1"..."9").contains($0) })
        return value < 0 && !roundsToZero ? minusSign + text : text
    }

    public static func number(_ value: Double?, digits: Int = 2) -> String {
        guard let value, value.isFinite else { return noValue }
        return grouped(value, minDigits: 0, maxDigits: digits)
    }

    /// value 已是百分比數值（1.5 代表 1.5%）；正值帶 +。
    public static func percent(_ value: Double?, digits: Int = 2) -> String {
        guard let value, value.isFinite else { return noValue }
        let text = grouped(value, minDigits: digits, maxDigits: digits)
        let isPositive = value > 0 && text.contains(where: { ("1"..."9").contains($0) })
        return (isPositive ? "+" : "") + text + "%"
    }

    // max 是上限：報價的有效小數一律保留到四位，不依價位捨入（00631L 443.15、滬市 ETF 1.231）。
    // min 只決定補幾個 0：台股高價股不補，其他市場一元以下固定四位。
    private static func priceDigits(_ value: Double, currency: String?) -> (min: Int, max: Int) {
        let magnitude = abs(value)
        if currency == "TWD" {
            if magnitude >= 1000 { return (0, 4) }
            if magnitude >= 100 { return (1, 4) }
            return (2, 4)
        }
        return (magnitude > 0 && magnitude < 1 ? 4 : 2, 4)
    }

    public static func price(_ value: Double?, currency: String? = nil) -> String {
        guard let value, value.isFinite else { return noValue }
        let digits = priceDigits(value, currency: currency)
        return grouped(value, minDigits: digits.min, maxDigits: digits.max)
    }

    /// 不帶小數的金額，給總資產這類大數字用；幣別碼放前面。
    public static func moneyWhole(_ value: Double?, currency: String? = nil) -> String {
        guard let value, value.isFinite else { return noValue }
        let text = grouped(value, minDigits: 0, maxDigits: 0)
        guard let currency, !currency.isEmpty else { return text }
        return "\(currency) \(text)"
    }
}
