import Foundation

enum MarketDataPresentation {
    static let referenceTimeExplanation = "此欄可能是行情來源時間或資料取得時間，不能單靠此時間判斷是否即時。"

    /// 同日官方盤口以 -- 表示的空檔，Shioaji 會回價量皆 0；只在盤口語境處理。
    static func orderBookPrice(_ price: Double?, volume: Int?) -> String {
        if price == 0 && volume == 0 { return "無報價" }
        return DisplayFormat.number(price)
    }
}
