import DSACore
import SwiftUI

struct ToolsView: View {
    @EnvironmentObject private var store: AppStore
    @State private var loggingOut = false
    @State private var confirmingLogout = false
    @State private var showingGuide = false
    @AppStorage("tools.advancedExpanded") private var advancedExpanded = true

    var body: some View {
        PageScroll {
            LazyVGrid(columns: [GridItem(.flexible(), spacing: 12), GridItem(.flexible(), spacing: 12)], spacing: 12) {
                NavigationLink { ToolWebView(path: "/alerts", title: "警報") } label: {
                    shortcut("警報", value: alertValue, icon: "bell.badge")
                }
                .accessibilityIdentifier("tools.route.alerts")
                NavigationLink { ConnectionDetailView() } label: {
                    shortcut("連線", value: store.connected ? "已連線" : "未連線", icon: "network")
                }
                .accessibilityIdentifier("tools.connection")
            }
            .buttonStyle(.plain)

            VStack(alignment: .leading, spacing: 12) {
                SectionHeading("常用")
                DSACard {
                    VStack(spacing: 0) {
                        toolLinkRows([
                            ToolLink(path: "/chat", title: "AI 問股", icon: "bubble.left.and.text.bubble.right"),
                            ToolLink(path: "/screening", title: "選股", icon: "line.3.horizontal.decrease.circle"),
                            ToolLink(path: "/portfolio", title: "資產帳本", icon: "books.vertical"),
                            ToolLink(path: "/funds", title: "基金", icon: "chart.bar.doc.horizontal"),
                            ToolLink(path: "/settings", title: "設定", icon: "gearshape")
                        ])
                        Divider().overlay(Theme.border)
                        Button { showingGuide = true } label: {
                            ToolRow(title: "看懂 K 線", icon: "chart.xyaxis.line")
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("tools.klineGuide")
                    }
                }
            }

            VStack(alignment: .leading, spacing: 12) {
                Button { advancedExpanded.toggle() } label: {
                    HStack {
                        SectionHeading("分析與系統")
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
                        ToolLink(path: "/decision-signals", title: "AI 建議", icon: "waveform.path.ecg"),
                        ToolLink(path: "/backtest", title: "回測", icon: "clock.arrow.circlepath"),
                        ToolLink(path: "/data", title: "資料中心", icon: "externaldrive"),
                        ToolLink(path: "/usage", title: "AI 用量", icon: "chart.bar.xaxis")
                    ])
                }
            }

            VStack(alignment: .leading, spacing: 12) {
                SectionHeading("這部裝置")
                DSACard {
                    VStack(spacing: 0) {
                        LabeledContent {
                            Picker("漲跌顏色", selection: $store.colorConvention) {
                                ForEach(MarketColorConvention.allCases) { convention in
                                    Text(convention.title).tag(convention)
                                }
                            }
                            .pickerStyle(.menu)
                            .labelsHidden()
                            .tint(Theme.secondary)
                        } label: {
                            ToolRowLabel(title: "漲跌顏色", icon: "paintpalette")
                        }
                        .frame(minHeight: 44)
                        .accessibilityIdentifier("tools.colorConvention")
                        Divider().overlay(Theme.border)
                        HStack(spacing: 13) {
                            ToolRowLabel(title: "Daily Stock AI", icon: "info.circle")
                            Spacer(minLength: 4)
                            Text(version).font(.caption.monospacedDigit()).foregroundStyle(Theme.secondary)
                        }
                        .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                        .accessibilityElement(children: .combine)
                        Divider().overlay(Theme.border)
                        Button(role: .destructive) { confirmingLogout = true } label: {
                            ToolRowLabel(title: loggingOut ? "正在登出…" : "登出這部裝置",
                                         icon: "rectangle.portrait.and.arrow.right", tint: Theme.danger)
                                .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
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

    private func toolRows(_ items: [ToolLink]) -> some View {
        DSACard {
            VStack(spacing: 0) { toolLinkRows(items) }
        }
    }

    @ViewBuilder
    private func toolLinkRows(_ items: [ToolLink]) -> some View {
        ForEach(Array(items.enumerated()), id: \.element.path) { index, item in
            if index > 0 { Divider().overlay(Theme.border) }
            NavigationLink {
                ToolWebView(path: item.path, title: item.title)
            } label: {
                ToolRow(title: item.title, icon: item.icon)
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("tools.route.\(String(item.path.dropFirst()))")
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
    @State private var showingAccess = false
    @State private var accessConfigured = false

    var body: some View {
        PageScroll {
            group("服務網址") {
                HStack(spacing: 13) {
                    Image(systemName: "network")
                        .font(.system(size: 17, weight: .medium))
                        .foregroundStyle(Theme.accent)
                        .frame(width: 28)
                        .accessibilityHidden(true)
                    Text(store.serverAddress)
                        .font(.subheadline).foregroundStyle(Theme.text)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier("tools.serverAddress")
                }
                .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
            }
            group("狀態") {
                HStack(spacing: 13) {
                    ToolRowLabel(title: "連線狀態", icon: "dot.radiowaves.left.and.right")
                    Spacer(minLength: 4)
                    Text(store.connected ? "已連線" : "未連線")
                        .font(.subheadline)
                        .foregroundStyle(store.connected ? Theme.accent : Theme.secondary)
                }
                .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                .accessibilityElement(children: .combine)
            }
            VStack(alignment: .leading, spacing: 8) {
                group("Access") {
                    Button { showingAccess = true } label: {
                        ToolRow(title: "Cloudflare Access", icon: "key",
                                value: accessConfigured ? "已設定" : "未設定")
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("tools.access")
                }
                Text("換服務請先登出，再於連線畫面輸入新網址。")
                    .font(.caption).foregroundStyle(Theme.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, 4)
            }
        }
        .navigationTitle("連線")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.hidden, for: .tabBar)
        .onAppear { accessConfigured = store.hasAccessCredentials() }
        .sheet(isPresented: $showingAccess, onDismiss: {
            accessConfigured = store.hasAccessCredentials()
            // 存／移除憑證會清掉 client；沒按「套用並重新連線」就關閉時要補重連，否則畫面仍顯示已連線卻不再載入。
            if store.needsReconnect { Task { await store.submitConnection() } }
        }) {
            AccessCredentialsSheet()
                .environmentObject(store)
        }
    }

    private func group<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeading(title, level: .group)
            DSACard { content() }
        }
    }
}

/// Edits Access credentials without leaving MainTabView; only "套用並重新連線" reconnects.
private struct AccessCredentialsSheet: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    DSACard { AccessSettingsView() }
                    Button {
                        dismiss()
                        Task { await store.submitConnection() }
                    } label: {
                        HStack {
                            Text("套用並重新連線")
                            Spacer()
                            Image(systemName: "arrow.clockwise")
                        }
                    }
                    .buttonStyle(PressableButtonStyle())
                    .disabled(store.connecting)
                    .accessibilityIdentifier("access-apply")
                }
                .padding(16)
            }
            .background(Theme.background)
            .navigationTitle("Cloudflare Access")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("關閉") { dismiss() }
                        .accessibilityIdentifier("access-sheet-close")
                }
            }
        }
        // The shared view is a DisclosureGroup; inside the sheet it should open expanded.
        .onAppear { store.accessExpanded = true }
    }
}

/// Icon (28pt column) + title, shared by tool rows so every row aligns.
private struct ToolRowLabel: View {
    let title: String
    let icon: String
    var tint: Color? = nil

    var body: some View {
        HStack(spacing: 13) {
            Image(systemName: icon)
                .font(.system(size: 17, weight: .medium))
                .foregroundStyle(tint ?? Theme.accent)
                .frame(width: 28)
                .accessibilityHidden(true)
            Text(title).font(.subheadline).foregroundStyle(tint ?? Theme.text)
        }
    }
}

/// Standard navigation row: icon + title + optional trailing value + chevron.
private struct ToolRow: View {
    let title: String
    let icon: String
    var value: String? = nil

    var body: some View {
        HStack(spacing: 13) {
            ToolRowLabel(title: title, icon: icon)
            Spacer(minLength: 4)
            if let value {
                Text(value).font(.subheadline).foregroundStyle(Theme.secondary)
            }
            Image(systemName: "chevron.right").font(.caption.weight(.semibold)).foregroundStyle(Theme.secondary)
                .accessibilityHidden(true)
        }
        .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
        .contentShape(Rectangle())
    }
}

private struct ToolLink {
    let path: String
    let title: String
    let icon: String
}
