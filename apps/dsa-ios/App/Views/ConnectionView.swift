import SwiftUI

struct ConnectionView: View {
    @EnvironmentObject private var store: AppStore
    @State private var password = ""
    @State private var showAddress = false

    var body: some View {
        NavigationStack {
            PageScroll {
                VStack(alignment: .leading, spacing: 20) {
                    BrandMark().frame(width: 74, height: 74).padding(.top, 24)
                    Text("Daily\nStock AI")
                        .font(.system(.largeTitle, design: .rounded, weight: .bold))
                        .foregroundStyle(Theme.text)
                    Text("看見行情，\n也看懂背後的判斷。")
                        .font(.title2.weight(.medium)).foregroundStyle(Theme.secondary)
                    HStack(spacing: 8) {
                        StatusBadge("台股 + 美股", tone: .information)
                        StatusBadge("你的 AI 研究室", tone: .ai)
                    }
                }
                DSACard {
                    VStack(alignment: .leading, spacing: 16) {
                        SectionHeading(store.needsPassword ? "登入分析服務" : "連接你的分析服務",
                                       subtitle: "沿用你的行情、自選股與 AI 報告。")
                        if store.serverAddress.isEmpty || showAddress || !store.needsPassword {
                            TextField("https://你的服務網址", text: $store.serverAddress)
                                .keyboardType(.URL).textContentType(.URL)
                                .textInputAutocapitalization(.never).autocorrectionDisabled()
                                .padding(14).background(Theme.background, in: RoundedRectangle(cornerRadius: 12))
                                .accessibilityIdentifier("server-address")
                        } else {
                            Text(store.serverAddress).font(.caption).foregroundStyle(Theme.secondary)
                            Button("變更服務網址") { showAddress = true; store.needsPassword = false }
                        }
                        AccessSettingsView()
                        if store.needsPassword {
                            SecureField("管理員密碼", text: $password)
                                .textContentType(.password)
                                .padding(14).background(Theme.background, in: RoundedRectangle(cornerRadius: 12))
                                .accessibilityIdentifier("server-password")
                        }
                        if let error = store.connectionError { ErrorStateView(message: error) }
                        Button {
                            Task {
                                await store.connect(password: store.needsPassword ? password : nil)
                                password = ""
                            }
                        } label: {
                            HStack {
                                if store.connecting { ProgressView().tint(Theme.background) }
                                Text(store.connecting ? "連接中…" : store.needsPassword ? "登入" : "連接服務")
                                Spacer()
                                Image(systemName: "arrow.right")
                            }
                        }
                        .buttonStyle(PressableButtonStyle())
                        .disabled(store.connecting || store.serverAddress.isEmpty || (store.needsPassword && password.isEmpty))
                        .accessibilityIdentifier("connect-button")
                    }
                }
                VStack(alignment: .leading, spacing: 16) {
                    feature("chart.xyaxis.line", "行情與研究，同一個畫面", "日 K、報價與最新 AI 判斷相互對照。")
                    feature("list.bullet.clipboard", "每個觀點，都能追溯", "查看理由、資料來源與判斷失效條件。")
                    feature("lock.shield", "安全連接分析服務", "登入狀態保存在裝置 Keychain，不保存密碼。")
                }
                Text("更換服務網址後，請使用原本的管理員密碼重新登入。AI 分析供研究參考，評分不代表勝率；報價與報告以各自標示的時間為準。")
                    .font(.caption).foregroundStyle(Theme.secondary).padding(.bottom, 20)
            }
        }
        #if DEBUG && DSA_ACCESS_UITEST
        .onAppear { password = ProcessInfo.processInfo.environment["DSA_ACCESS_TEST_PASSWORD"] ?? "" }
        #endif
    }

    private func feature(_ icon: String, _ title: String, _ detail: String) -> some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: icon).frame(width: 24).foregroundStyle(Theme.accent)
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
                Text(detail).font(.caption).foregroundStyle(Theme.secondary)
            }
        }
    }
}
