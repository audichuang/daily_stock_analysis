import SwiftUI

/// 「看懂 K 線」的段落；圖表各處的問號帶段落開啟，直接落在對應內容。
enum KLineGuideSection: String, CaseIterable, Identifiable {
    case candle, period, movingAverage, volume, oscillator, markers

    var id: String { rawValue }

    var title: String {
        switch self {
        case .candle: "K 棒"
        case .period: "週期"
        case .movingAverage: "均線"
        case .volume: "成交量"
        case .oscillator: "副圖"
        case .markers: "標記"
        }
    }
}

/// 「看懂 K 線」說明。顏色與文字都跟著使用者選的漲跌色慣例走，切成綠漲紅跌時不能還寫紅漲。
struct KLineGuideView: View {
    let convention: MarketColorConvention
    let initialSection: KLineGuideSection
    @State private var activeSection: KLineGuideSection
    @Environment(\.dismiss) private var dismiss

    init(convention: MarketColorConvention, initialSection: KLineGuideSection = .candle) {
        self.convention = convention
        self.initialSection = initialSection
        _activeSection = State(initialValue: initialSection)
    }

    private var upColor: Color { Theme.changeColor(1, convention: convention) }
    private var downColor: Color { Theme.changeColor(-1, convention: convention) }
    private var upName: String { convention == .taiwan ? "紅" : "綠" }
    private var downName: String { convention == .taiwan ? "綠" : "紅" }

    var body: some View {
        NavigationStack {
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        candleSection.id(KLineGuideSection.candle)
                        periodSection.id(KLineGuideSection.period)
                        movingAverageSection.id(KLineGuideSection.movingAverage)
                        volumeSection.id(KLineGuideSection.volume)
                        oscillatorSection.id(KLineGuideSection.oscillator)
                        markersSection.id(KLineGuideSection.markers)
                        Text("K 線、指標與標記只是描述過去的價格，不是買賣訊號；要搭配基本面與 AI 研究的論點一起看。")
                            .font(.caption)
                            .foregroundStyle(Theme.warning)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(16)
                }
                .safeAreaInset(edge: .top, spacing: 0) {
                    sectionBar(proxy)
                }
                .task {
                    // 等 Sheet 第一次排版完才捲得到目標段落。
                    await Task.yield()
                    proxy.scrollTo(initialSection, anchor: .top)
                }
            }
            .background(Theme.background.ignoresSafeArea())
            .navigationTitle("看懂 K 線")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(Theme.background, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("完成") { dismiss() }
                        .accessibilityIdentifier("chart.guide.done")
                }
            }
        }
        // 只開到全高、背景完全不透明：下緣不再露出底層圖表的碎片。
        .presentationDetents([.large])
        .presentationBackground(Theme.background)
        .accessibilityIdentifier("chart.guide.sheet")
    }

    private func sectionBar(_ proxy: ScrollViewProxy) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                ForEach(KLineGuideSection.allCases) { section in
                    let selected = section == activeSection
                    Button {
                        activeSection = section
                        withAnimation { proxy.scrollTo(section, anchor: .top) }
                    } label: {
                        Text(section.title)
                            .font(.subheadline.weight(selected ? .bold : .medium))
                            .foregroundStyle(selected ? Theme.text : Theme.secondary)
                            .padding(.horizontal, 12)
                            .frame(minHeight: 36)
                            .background(selected ? Theme.elevated : Color.clear, in: Capsule())
                    }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(selected ? .isSelected : [])
                    .accessibilityIdentifier("chart.guide.tab.\(section.rawValue)")
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 6)
        }
        .background(Theme.background)
    }

    // MARK: - 段落

    private var candleSection: some View {
        DSACard {
            VStack(alignment: .leading, spacing: 14) {
                SectionHeading("一根 K 棒", subtitle: "記錄一段時間的四個價格")
                HStack(alignment: .top, spacing: 8) {
                    sampleCandle(color: upColor, title: "收 > 開（上漲）", bodyTop: 30, bodyBottom: 80, upperLabel: "收", lowerLabel: "開")
                    sampleCandle(color: downColor, title: "收 < 開（下跌）", bodyTop: 40, bodyBottom: 95, upperLabel: "開", lowerLabel: "收")
                    sampleCandle(color: Theme.secondary, title: "開＝收（十字線）", bodyTop: 60, bodyBottom: 62, upperLabel: "開＝收", lowerLabel: nil)
                }
                .frame(maxWidth: .infinity)
                bullet("粗的實體", "開盤價到收盤價。\(upName)色代表收盤比開盤高，\(downName)色代表收盤比開盤低。")
                bullet("上方細線（上影線）", "這段時間的最高價。上影線很長，代表曾經漲上去但被賣壓壓回。")
                bullet("下方細線（下影線）", "這段時間的最低價。下影線很長，代表跌下去後有買盤接回。")
                bullet("一條橫線（十字線）", "開盤等於收盤，多空拉鋸、方向未定。")
            }
        }
    }

    private var periodSection: some View {
        DSACard {
            VStack(alignment: .leading, spacing: 12) {
                SectionHeading("日 K、週 K、月 K", subtitle: "一根代表多長的時間")
                bullet("日 K", "一根是一個交易日，適合看最近幾個月的短線變化。")
                bullet("週 K", "一根是一週：開盤取當週第一個交易日、收盤取最後一個交易日，高低取整週極值，成交量相加。適合看一到三年。")
                bullet("月 K", "一根是一個月，適合看好幾年的大方向。")
                Text("週 K 預設顯示 1 年（1Y）、月 K 預設 5 年（5Y），避免幾百根 K 棒擠在一起看不清；區間仍可自己切換。")
                    .font(.caption).foregroundStyle(Theme.secondary)
                Text("週末與假日沒有交易，圖上不留空隙，相鄰兩根就是相鄰兩個交易時段。")
                    .font(.caption).foregroundStyle(Theme.secondary)
            }
        }
    }

    private var movingAverageSection: some View {
        DSACard {
            VStack(alignment: .leading, spacing: 12) {
                SectionHeading("均線（MA）", subtitle: "最近 N 根 K 棒收盤價的平均")
                HStack(spacing: 14) {
                    ForEach(Array(["短", "中", "長"].enumerated()), id: \.offset) { slot, name in
                        lineSwatch(name, color: MarketChart.lineColors[slot])
                    }
                    Spacer(minLength: 0)
                }
                bullet("日 K：MA5／MA20／MA60", "約一週、一個月、一季的平均成本，常叫週線、月線、季線。")
                bullet("週 K：MA5／MA13／MA26", "約一個月、一季、半年。")
                bullet("月 K：MA3／MA6／MA12", "一季、半年、一年。")
                bullet("怎麼用", "股價站在均線上方、均線往上彎，代表這段期間買進的人大多賺錢，走勢偏多；跌破並且均線往下彎則偏弱。短均線由下往上穿過長均線常叫黃金交叉，反過來叫死亡交叉。")
                bullet("EMA", "指數移動平均，越近的價格權重越大，轉彎比 MA 快，也比較容易被短期波動帶著走。")
                HStack(spacing: 8) {
                    RoundedRectangle(cornerRadius: 2)
                        .fill(Theme.information.opacity(0.18))
                        .frame(width: 28, height: 14)
                    Text("布林通道的範圍").font(.caption2).foregroundStyle(Theme.secondary)
                }
                bullet("布林通道", "中間線是 20 根均線；上下兩條是股價通常的波動範圍，約 95% 的時間落在其中。")
                Text("圖下方的「主圖」列可在 MA、EMA、布林之間切換；點讀數裡的指標名稱可以個別隱藏或顯示。")
                    .font(.caption).foregroundStyle(Theme.secondary)
            }
        }
    }

    private var volumeSection: some View {
        DSACard {
            VStack(alignment: .leading, spacing: 12) {
                SectionHeading("成交量", subtitle: "價格圖下方的柱子")
                HStack(alignment: .bottom, spacing: 3) {
                    ForEach(Array([(10, upColor), (16, upColor), (8, downColor), (24, upColor)].enumerated()), id: \.offset) { _, bar in
                        Rectangle().fill(bar.1.opacity(0.6)).frame(width: 7, height: CGFloat(bar.0))
                    }
                    Text("量柱，顏色跟該根 K 棒一樣").font(.caption2).foregroundStyle(Theme.secondary).padding(.leading, 6)
                }
                bullet("高度", "這根 K 棒期間的成交數量，顏色跟上方 K 棒一樣。台股以「張」顯示（1 張＝1,000 股），其他市場是股數。")
                bullet("怎麼看", "上漲時量放大，代表追價的人多、比較可信；上漲但量縮，力道可能不足。下跌時爆量，代表很多人在賣。")
            }
        }
    }

    private var oscillatorSection: some View {
        DSACard {
            VStack(alignment: .leading, spacing: 12) {
                SectionHeading("副圖指標", subtitle: "成交量下方那一格，從「副圖」列切換")
                HStack(spacing: 14) {
                    lineSwatch("DIF／K", color: Theme.warning)
                    lineSwatch("DEA／D", color: Theme.information)
                    Spacer(minLength: 0)
                }
                bullet("MACD(12,26,9)", "先看柱子：由負翻正代表上漲動能轉強。黃線 DIF 是短、長期均線的差距，藍線 DEA 是它的平均。")
                VStack(alignment: .leading, spacing: 3) {
                    Text("KD(9,3,3)").font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
                    Text("80 以上偏熱、20 以下偏冷").font(.subheadline.weight(.bold)).foregroundStyle(Theme.text)
                    Text("看收盤價落在最近 9 根高低區間的哪個位置；K 線由下往上穿過 D 線常被當成轉強訊號。強勢股可以長時間停在 80 以上，不等於馬上會跌。")
                        .font(.subheadline).foregroundStyle(Theme.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                bullet("RSI(14)", "最近 14 根漲幅佔總波動的比例。70 以上偏熱、30 以下偏冷。")
            }
        }
    }

    private var markersSection: some View {
        DSACard {
            VStack(alignment: .leading, spacing: 12) {
                SectionHeading("重點標記", subtitle: "由價量自動算出，只描述發生過什麼")
                bullet("高／低", "目前畫面範圍內的最高價與最低價。按「重點標記」可關閉。")
                bullet("52 週高／低", "寫在圖下方，最近一年的最高與最低價，常被當成壓力與支撐。資料不足一年時不顯示。")
                HStack(spacing: 8) {
                    Rectangle().fill(upColor.opacity(0.18)).frame(width: 28, height: 14)
                    Text("未補缺口").font(.caption2).foregroundStyle(Theme.secondary)
                    Image(systemName: "triangle.fill").font(.caption2).foregroundStyle(Theme.warning)
                    Text("黃金交叉").font(.caption2).foregroundStyle(Theme.secondary)
                    Image(systemName: "triangle.fill").font(.caption2).foregroundStyle(Theme.information)
                    Text("死亡交叉").font(.caption2).foregroundStyle(Theme.secondary)
                }
                bullet("未補缺口（色塊）", "預設不顯示，按「缺口交叉」才畫。跳空後還沒被股價回頭碰到的價格區間，最多標最近三個；之後股價回到這裡時常有支撐或賣壓。")
                bullet("三角形", "預設不顯示，按「缺口交叉」才畫。短均線與中均線交叉，只標畫面內最近三次，最新一次附文字。")
                bullet("右側價格標籤", "最新收盤價，放在價格軸上，顏色代表相對昨收的漲跌。")
                bullet("較亮的量柱", "成交量超過前 20 根平均兩倍（爆量）。")
            }
        }
    }

    // MARK: - 元件

    private func bullet(_ title: String, _ text: String) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
            Text(text).font(.subheadline).foregroundStyle(Theme.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    /// 與圖上同樣粗細與顏色的線段圖例。
    private func lineSwatch(_ title: String, color: Color) -> some View {
        HStack(spacing: 5) {
            Capsule().fill(color).frame(width: 18, height: 2)
            Text(title).font(.caption2).foregroundStyle(Theme.secondary)
        }
    }

    /// 示意 K 棒：120pt 高的畫布，影線貫穿上下，實體在 bodyTop～bodyBottom，右側標最高、開收與最低。
    private func sampleCandle(color: Color, title: String, bodyTop: CGFloat, bodyBottom: CGFloat, upperLabel: String, lowerLabel: String?) -> some View {
        let candleCenter: CGFloat = 18
        let labelCenter: CGFloat = 60
        return VStack(spacing: 8) {
            ZStack(alignment: .topLeading) {
                Rectangle().fill(color)
                    .frame(width: 2, height: 120)
                    .position(x: candleCenter, y: 60)
                Rectangle().fill(color)
                    .frame(width: 26, height: bodyBottom - bodyTop)
                    .position(x: candleCenter, y: (bodyTop + bodyBottom) / 2)
                guideLabel("最高", y: 0, x: labelCenter)
                guideLabel(upperLabel, y: bodyTop, x: labelCenter)
                if let lowerLabel {
                    guideLabel(lowerLabel, y: bodyBottom, x: labelCenter)
                }
                guideLabel("最低", y: 120, x: labelCenter)
            }
            .frame(width: 90, height: 120)
            .padding(.vertical, 8)
            Text(title)
                .font(.caption.weight(.medium))
                .foregroundStyle(color)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .frame(width: 90)
        }
        .accessibilityElement(children: .combine)
    }

    private func guideLabel(_ text: String, y: CGFloat, x: CGFloat) -> some View {
        Text(text)
            .font(.caption2)
            .foregroundStyle(Theme.secondary)
            .position(x: x, y: y)
    }
}
