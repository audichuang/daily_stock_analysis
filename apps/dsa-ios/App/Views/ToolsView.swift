import DSACore
import SwiftUI

struct ToolsView: View {
    @EnvironmentObject private var store: AppStore
    @State private var loggingOut = false
    @State private var confirmingLogout = false
    @State private var showingGuide = false
    @State private var advancedExpanded = false

    var body: some View {
        PageScroll {
            LazyVGrid(columns: [GridItem(.flexible(), spacing: 12), GridItem(.flexible(), spacing: 12)], spacing: 12) {
                NavigationLink { ToolWebView(path: "/alerts", title: "價格警報") } label: {
                    shortcut("價格警報", value: alertValue, icon: "bell.badge")
                }
                .accessibilityIdentifier("tools.route.alerts")
                NavigationLink { ConnectionDetailView() } label: {
                    shortcut("連線", value: store.connected ? "已連線" : "未連線", icon: "network")
                }
                .accessibilityIdentifier("tools.connection")
            }
            .buttonStyle(.plain)

            toolGroup("常用", items: [
                ToolLink(path: "/chat", title: "AI 問股", icon: "bubble.left.and.text.bubble.right"),
                ToolLink(path: "/screening", title: "條件選股", icon: "line.3.horizontal.decrease.circle"),
                ToolLink(path: "/portfolio", title: "帳本管理", icon: "books.vertical"),
                ToolLink(path: "/settings", title: "服務設定", icon: "gearshape")
            ])

            VStack(alignment: .leading, spacing: 12) {
                Button { advancedExpanded.toggle() } label: {
                    HStack {
                        SectionHeading("進階")
                        Spacer(minLength: 4)
                        Image(systemName: advancedExpanded ? "chevron.up" : "chevron.down")
                            .font(.caption.weight(.semibold)).foregroundStyle(Theme.secondary)
                            .accessibilityHidden(true)
                    }
                    .frame(minHeight: 44)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityValue(advancedExpanded ? "已展開" : "已收合")
                .accessibilityIdentifier("tools.advanced")
                if advancedExpanded {
                    toolRows([
                        ToolLink(path: "/decision-signals", title: "決策訊號", icon: "waveform.path.ecg"),
                        ToolLink(path: "/backtest", title: "歷史回測", icon: "clock.arrow.circlepath"),
                        ToolLink(path: "/funds", title: "基金", icon: "chart.bar.doc.horizontal"),
                        ToolLink(path: "/data", title: "資料中心", icon: "externaldrive"),
                        ToolLink(path: "/usage", title: "AI 用量", icon: "chart.bar.xaxis")
                    ])
                }
            }

            VStack(alignment: .leading, spacing: 12) {
                SectionHeading("這部裝置")
                DSACard {
                    VStack(spacing: 0) {
                        Picker("漲跌顏色", selection: $store.colorConvention) {
                            ForEach(MarketColorConvention.allCases) { convention in
                                Text(convention.title).tag(convention)
                            }
                        }
                        .pickerStyle(.menu)
                        .foregroundStyle(Theme.text)
                        .frame(minHeight: 44)
                        .accessibilityIdentifier("tools.colorConvention")
                        Divider().overlay(Theme.border)
                        Button { showingGuide = true } label: {
                            row(title: "看懂 K 線", icon: "chart.xyaxis.line")
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("tools.klineGuide")
                        Divider().overlay(Theme.border)
                        HStack(alignment: .firstTextBaseline) {
                            Text("Daily Stock AI").font(.subheadline).foregroundStyle(Theme.text)
                            Spacer()
                            Text(version).font(.caption.monospacedDigit()).foregroundStyle(Theme.secondary)
                        }
                        .frame(minHeight: 44)
                        Divider().overlay(Theme.border)
                        Button(role: .destructive) { confirmingLogout = true } label: {
                            Label(loggingOut ? "正在登出…" : "登出這部裝置", systemImage: "rectangle.portrait.and.arrow.right")
                                .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(Theme.up)
                        .disabled(loggingOut)
                        .accessibilityIdentifier("tools.logout")
                    }
                }
            }
        }
        .navigationTitle("工具與設定")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear { store.refreshToolsStatus() }
        .sheet(isPresented: $showingGuide) { KLineGuideView(convention: store.colorConvention) }
        .confirmationDialog(
            "登出這部裝置？",
            isPresented: $confirmingLogout,
            titleVisibility: .visible
        ) {
            Button("確認登出", role: .destructive) {
                loggingOut = true
                Task { await store.logout(); loggingOut = false }
            }
            Button("取消", role: .cancel) {}
        } message: {
            Text("清除這部裝置的 DSA 登入狀態，保留 Cloudflare Access 憑證；伺服器上的帳本、報告與其他裝置不受影響。")
        }
    }

    private var alertValue: String {
        if store.alertMonitorFailed { return "無法取得" }
        return store.alertMonitor?.summaryLabel ?? "讀取中"
    }

    private func shortcut(_ title: String, value: String, icon: String) -> some View {
        DSACard {
            VStack(alignment: .leading, spacing: 8) {
                Image(systemName: icon)
                    .font(.system(size: 19, weight: .medium))
                    .foregroundStyle(Theme.accent)
                    .accessibilityHidden(true)
                Text(title).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
                Text(value).font(.caption).foregroundStyle(Theme.secondary).lineLimit(2)
            }
            .frame(maxWidth: .infinity, minHeight: 76, alignment: .leading)
            .contentShape(Rectangle())
        }
    }

    private func row(title: String, icon: String) -> some View {
        HStack(spacing: 13) {
            Image(systemName: icon)
                .font(.system(size: 17, weight: .medium))
                .foregroundStyle(Theme.accent)
                .frame(width: 28)
                .accessibilityHidden(true)
            Text(title).font(.subheadline).foregroundStyle(Theme.text)
            Spacer(minLength: 4)
            Image(systemName: "chevron.right").font(.caption.weight(.semibold)).foregroundStyle(Theme.secondary)
                .accessibilityHidden(true)
        }
        .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
        .contentShape(Rectangle())
    }

    private func toolGroup(_ title: String, items: [ToolLink]) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeading(title)
            toolRows(items)
        }
    }

    private func toolRows(_ items: [ToolLink]) -> some View {
        DSACard {
            VStack(spacing: 0) {
                ForEach(Array(items.enumerated()), id: \.element.path) { index, item in
                    if index > 0 { Divider().overlay(Theme.border) }
                    NavigationLink {
                        ToolWebView(path: item.path, title: item.title)
                    } label: {
                        row(title: item.title, icon: item.icon)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("tools.route.\(String(item.path.dropFirst()))")
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

private struct ConnectionDetailView: View {
    @EnvironmentObject private var store: AppStore

    var body: some View {
        PageScroll {
            DSACard {
                VStack(alignment: .leading, spacing: 18) {
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
                }
            }
        }
        .navigationTitle("連線")
        .navigationBarTitleDisplayMode(.inline)
    }
}

private struct ToolLink {
    let path: String
    let title: String
    let icon: String
}
