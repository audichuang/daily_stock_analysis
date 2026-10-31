import SwiftUI

struct ToolsView: View {
    @EnvironmentObject private var store: AppStore
    @State private var loggingOut = false

    var body: some View {
        PageScroll {
            SectionHeading("把研究，做得更完整。", subtitle: "進階工具連接既有服務，沿用目前的共用帳號；操作與資料會同步到網頁。", eyebrow: "WORKSPACE")

            toolGroup("研究與判斷", items: [
                ToolLink(path: "/chat", title: "AI 問股", detail: "帶著你的問題，深入追問投資依據", icon: "bubble.left.and.text.bubble.right"),
                ToolLink(path: "/screening", title: "條件選股", detail: "從條件篩選到候選清單", icon: "line.3.horizontal.decrease.circle"),
                ToolLink(path: "/decision-signals", title: "決策訊號", detail: "追蹤分析後的訊號與結果", icon: "waveform.path.ecg"),
                ToolLink(path: "/", title: "分析工作台", detail: "開啟完整分析、自選與個股檔案", icon: "doc.text.magnifyingglass"),
                ToolLink(path: "/backtest", title: "歷史回測", detail: "核對歷史分析的事後表現", icon: "clock.arrow.circlepath")
            ])
            toolGroup("帳本與追蹤", items: [
                ToolLink(path: "/portfolio", title: "帳本管理", detail: "帳戶、入金、交易與匯率", icon: "books.vertical"),
                ToolLink(path: "/funds", title: "基金", detail: "基金資料、淨值與持倉", icon: "chart.bar.doc.horizontal"),
                ToolLink(path: "/alerts", title: "價位警報", detail: "管理關注標的的警報規則", icon: "bell.badge")
            ])
            toolGroup("資料與服務", items: [
                ToolLink(path: "/data", title: "資料中心", detail: "檢查資料來源與可用能力", icon: "externaldrive"),
                ToolLink(path: "/usage", title: "AI 用量", detail: "查看模型使用紀錄", icon: "chart.bar.xaxis"),
                ToolLink(path: "/settings", title: "服務設定", detail: "共用服務的分析、資料與通知設定", icon: "gearshape")
            ])

            SectionHeading("這部裝置", subtitle: "調整 App 顯示與連線。")
            DSACard {
                VStack(alignment: .leading, spacing: 18) {
                    Picker("漲跌顏色", selection: $store.colorConvention) {
                        ForEach(MarketColorConvention.allCases) { convention in
                            Text(convention.title).tag(convention)
                        }
                    }
                    .pickerStyle(.menu)
                    .foregroundStyle(Theme.text)
                    .accessibilityIdentifier("tools.colorConvention")
                    Divider().overlay(Theme.border)
                    VStack(alignment: .leading, spacing: 7) {
                        Label("目前服務", systemImage: "network")
                            .font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
                        Text(store.serverAddress)
                            .font(.caption).foregroundStyle(Theme.secondary)
                            .textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                            .accessibilityIdentifier("tools.serverAddress")
                        Text("更換服務時，先登出這部裝置，再於連線畫面輸入新的網址。")
                            .font(.caption2).foregroundStyle(Theme.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    VStack(alignment: .leading, spacing: 7) {
                        Label("外出連線", systemImage: "lock.shield")
                            .font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
                        Text("使用公開 HTTPS 網址時，可直接由行動網路連線。若使用私有網址，請確認網路可達；服務仍需原本的登入密碼。")
                            .font(.caption).foregroundStyle(Theme.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Divider().overlay(Theme.border)
                    Button("Cloudflare Access 憑證") { store.showConnectionSettings() }
                        .accessibilityIdentifier("tools.access")
                    HStack(alignment: .firstTextBaseline) {
                        Text("Daily Stock AI").font(.subheadline).foregroundStyle(Theme.text)
                        Spacer()
                        Text(version).font(.caption.monospacedDigit()).foregroundStyle(Theme.secondary)
                    }
                }
            }

            Button {
                loggingOut = true
                Task { await store.logout(); loggingOut = false }
            } label: {
                Label(loggingOut ? "正在登出…" : "登出這部裝置", systemImage: "rectangle.portrait.and.arrow.right")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(SecondaryButtonStyle())
            .disabled(loggingOut)
            .accessibilityIdentifier("tools.logout")
            Text("清除這部裝置的 DSA 登入狀態，保留 Cloudflare Access 憑證；伺服器上的帳本、報告與其他裝置不受影響。")
                .font(.caption2).foregroundStyle(Theme.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .navigationTitle("工具與設定")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func toolGroup(_ title: String, items: [ToolLink]) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeading(title)
            DSACard {
                VStack(spacing: 0) {
                    ForEach(Array(items.enumerated()), id: \.element.path) { index, item in
                        if index > 0 { Divider().overlay(Theme.border).padding(.vertical, 6) }
                        NavigationLink {
                            ToolWebView(path: item.path, title: item.title)
                        } label: {
                            HStack(alignment: .center, spacing: 13) {
                                Image(systemName: item.icon)
                                    .font(.system(size: 19, weight: .medium))
                                    .foregroundStyle(Theme.accent)
                                    .frame(width: 36, height: 40)
                                    .accessibilityHidden(true)
                                VStack(alignment: .leading, spacing: 5) {
                                    Text(item.title).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
                                    Text(item.detail).font(.caption).foregroundStyle(Theme.secondary)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                                Spacer(minLength: 4)
                                Image(systemName: "chevron.right").font(.caption.weight(.semibold)).foregroundStyle(Theme.secondary)
                                    .accessibilityHidden(true)
                            }
                            .frame(maxWidth: .infinity, minHeight: 62, alignment: .leading)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("tools.route.\(String(item.path.dropFirst()))")
                    }
                }
            }
        }
    }

    private var version: String {
        let marketing = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "—"
        let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "—"
        return "\(marketing) (\(build))"
    }
}

private struct ToolLink {
    let path: String
    let title: String
    let detail: String
    let icon: String
}
