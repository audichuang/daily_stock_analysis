import SwiftUI

/// 「看懂 K 線」說明。顏色與文字都跟著使用者選的漲跌色慣例走，切成綠漲紅跌時不能還寫紅漲。
struct KLineGuideView: View {
    let convention: MarketColorConvention
    @Environment(\.dismiss) private var dismiss

    private var upColor: Color { Theme.changeColor(1, convention: convention) }
    private var downColor: Color { Theme.changeColor(-1, convention: convention) }
    private var upName: String { convention == .taiwan ? "紅" : "綠" }
    private var downName: String { convention == .taiwan ? "綠" : "紅" }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    DSACard {
                        VStack(alignment: .leading, spacing: 14) {
                            SectionHeading("一根 K 棒", subtitle: "記錄一段時間的四個價格")
                            HStack(alignment: .center, spacing: 28) {
                                sampleCandle(color: upColor, title: "收 > 開（上漲）", bodyTop: 30, bodyBottom: 80)
                                sampleCandle(color: downColor, title: "收 < 開（下跌）", bodyTop: 40, bodyBottom: 95)
                            }
                            .frame(maxWidth: .infinity)
                            bullet("粗的實體", "開盤價到收盤價。\(upName)色代表收盤比開盤高，\(downName)色代表收盤比開盤低。")
                            bullet("上方細線（上影線）", "這段時間的最高價。上影線很長，代表曾經漲上去但被賣壓壓回。")
                            bullet("下方細線（下影線）", "這段時間的最低價。下影線很長，代表跌下去後有買盤接回。")
                            bullet("一條橫線（十字線）", "開盤等於收盤，多空拉鋸、方向未定。")
                        }
                    }
                    DSACard {
                        VStack(alignment: .leading, spacing: 12) {
                            SectionHeading("日 K、週 K、月 K", subtitle: "一根代表多長的時間")
                            bullet("日 K", "一根是一個交易日，適合看最近幾個月的短線變化。")
                            bullet("週 K", "一根是一週：開盤取當週第一個交易日、收盤取最後一個交易日，高低取整週極值，成交量相加。適合看一到三年。")
                            bullet("月 K", "一根是一個月，適合看好幾年的大方向。")
                            Text("切換 1Y 以上的區間時會自動換成週 K 或月 K，避免幾百根日 K 擠在一起看不清；仍可自己切回日 K。")
                                .font(.caption).foregroundStyle(Theme.secondary)
                        }
                    }
                    DSACard {
                        VStack(alignment: .leading, spacing: 12) {
                            SectionHeading("均線（MA）", subtitle: "最近 N 根 K 棒收盤價的平均")
                            bullet("日 K：MA5／MA20／MA60", "約一週、一個月、一季的平均成本，常叫週線、月線、季線。")
                            bullet("週 K：MA5／MA13／MA26", "約一個月、一季、半年。")
                            bullet("月 K：MA3／MA6／MA12", "一季、半年、一年。")
                            bullet("怎麼用", "股價站在均線上方、均線往上彎，代表這段期間買進的人大多賺錢，走勢偏多；跌破並且均線往下彎則偏弱。短均線由下往上穿過長均線常叫黃金交叉，反過來叫死亡交叉。")
                            Text("點圖下方的 MA 標籤可以個別隱藏或顯示。")
                                .font(.caption).foregroundStyle(Theme.secondary)
                        }
                    }
                    DSACard {
                        VStack(alignment: .leading, spacing: 12) {
                            SectionHeading("成交量", subtitle: "圖表下方的柱子")
                            bullet("高度", "這根 K 棒期間成交的股數，顏色跟上方 K 棒一樣。")
                            bullet("怎麼看", "上漲時量放大，代表追價的人多、比較可信；上漲但量縮，力道可能不足。下跌時爆量，代表很多人在賣。")
                        }
                    }
                    Text("K 線與均線只是描述過去的價格，不是買賣訊號；要搭配基本面與 AI 研究的論點一起看。")
                        .font(.caption)
                        .foregroundStyle(Theme.warning)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(16)
            }
            .background(Theme.background.ignoresSafeArea())
            .navigationTitle("看懂 K 線")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("完成") { dismiss() }
                        .accessibilityIdentifier("chart.guide.done")
                }
            }
        }
        .accessibilityIdentifier("chart.guide.sheet")
    }

    private func bullet(_ title: String, _ text: String) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
            Text(text).font(.subheadline).foregroundStyle(Theme.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    /// 示意 K 棒：120pt 高的畫布，影線貫穿上下，實體在 bodyTop～bodyBottom。
    private func sampleCandle(color: Color, title: String, bodyTop: CGFloat, bodyBottom: CGFloat) -> some View {
        VStack(spacing: 8) {
            ZStack(alignment: .top) {
                Rectangle().fill(color).frame(width: 2, height: 120)
                Rectangle().fill(color).frame(width: 26, height: bodyBottom - bodyTop).offset(y: bodyTop)
            }
            .frame(width: 60, height: 120)
            .overlay(alignment: .topLeading) {
                Text("最高").font(.caption2).foregroundStyle(Theme.secondary).offset(x: 38, y: -4)
            }
            .overlay(alignment: .bottomLeading) {
                Text("最低").font(.caption2).foregroundStyle(Theme.secondary).offset(x: 38, y: 4)
            }
            Text(title).font(.caption.weight(.medium)).foregroundStyle(color)
        }
        .accessibilityElement(children: .combine)
    }
}
