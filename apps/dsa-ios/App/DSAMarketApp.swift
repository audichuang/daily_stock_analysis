import SwiftUI

@main
struct DSAMarketApp: App {
    @StateObject private var store = AppStore()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            Group {
                // 已連上就進主畫面，不等首輪資料載完；冷啟動只顯示連接中，不閃登入表單。
                if store.connected { MainTabView() }
                else if store.startingUp { StartupConnectingView() }
                else { ConnectionView() }
            }
            .environmentObject(store)
            .tint(Theme.accent)
            .preferredColorScheme(.dark)
            .task {
                if !store.serverAddress.isEmpty { await store.submitConnection() }
                store.startingUp = false
            }
            .onChange(of: scenePhase) { _, phase in
                if phase == .active, store.connected { Task { await store.refresh() } }
            }
        }
    }
}

struct MainTabView: View {
    @EnvironmentObject private var store: AppStore

    var body: some View {
        TabView(selection: $store.selectedTab) {
            NavigationStack { MarketHomeView() }
                .tabItem { Label("今日", systemImage: "square.grid.2x2") }.tag(0)
            NavigationStack { WatchlistView() }
                .tabItem { Label("自選", systemImage: "chart.line.uptrend.xyaxis") }.tag(1)
            NavigationStack { ResearchLibraryView() }
                .tabItem { Label("AI 研究", systemImage: "text.magnifyingglass") }.tag(2)
            NavigationStack { PortfolioView() }
                .tabItem { Label("資產", systemImage: "chart.pie") }.tag(3)
            NavigationStack { ToolsView() }
                .tabItem { Label("工具", systemImage: "slider.horizontal.3") }.tag(4)
        }
    }
}

struct PageScroll<Content: View>: View {
    @ViewBuilder let content: Content
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                content
                PageBottomAnchor()
            }
                .padding(16)
                .frame(maxWidth: 900, alignment: .leading)
                .frame(maxWidth: .infinity)
        }
        .dsaPageBottomInset()
        .background(Theme.background)
    }
}
