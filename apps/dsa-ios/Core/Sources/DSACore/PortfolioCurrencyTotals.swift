import Foundation

/// 每個帳戶原幣的合計；不使用後端固定幣別的跨帳戶換算數字。
public struct PortfolioCurrencyTotal: Identifiable, Equatable, Sendable {
    public var id: String { currency }
    public let currency: String
    public let accountCount: Int
    public let totalEquity: Double?
    public let totalCash: Double?
    public let totalMarketValue: Double?
    public let unrealizedPnl: Double?
    public let realizedPnl: Double?
    public let fxMissing: Bool
    public let fxStale: Bool
    public let limitations: [String]
}

public extension PortfolioSnapshot {
    var currencyTotals: [PortfolioCurrencyTotal] { accounts.currencyTotals }
}

public extension Array where Element == PortfolioAccount {
    var currencyTotals: [PortfolioCurrencyTotal] {
        Dictionary(grouping: self, by: \.baseCurrency)
            .map { currency, members in
                // 帳戶內缺匯率的金額已包含未換算值，不能和同幣其他帳戶繼續加總。
                let missing = members.contains { $0.fxMissing == true }
                return PortfolioCurrencyTotal(
                    currency: currency, accountCount: members.count,
                    totalEquity: missing ? nil : members.reduce(0) { $0 + $1.totalEquity },
                    totalCash: missing ? nil : members.reduce(0) { $0 + $1.totalCash },
                    totalMarketValue: missing ? nil : members.reduce(0) { $0 + $1.totalMarketValue },
                    unrealizedPnl: missing ? nil : members.reduce(0) { $0 + $1.unrealizedPnl },
                    realizedPnl: missing ? nil : members.reduce(0) { $0 + $1.realizedPnl },
                    fxMissing: missing, fxStale: members.contains { $0.fxStale == true },
                    limitations: Set(members.flatMap(\.limitations)).sorted()
                )
            }
            .sorted { lhs, rhs in
                let priority = ["TWD": 0, "USD": 1]
                return (priority[lhs.currency] ?? 2, lhs.currency)
                    < (priority[rhs.currency] ?? 2, rhs.currency)
            }
    }
}
