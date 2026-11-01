import SwiftUI

struct AccessSettingsView: View {
    @EnvironmentObject private var store: AppStore
    @State private var clientID = ""
    @State private var secret = ""
    @State private var configured = false
    @State private var replacing = false
    @State private var error: String?

    var body: some View {
        DisclosureGroup(isExpanded: $store.accessExpanded) {
            VStack(alignment: .leading, spacing: 12) {
                Text("憑證只用於目前服務，安全保存在這部裝置。登出與更新 App 都會保留。")
                    .font(.caption).foregroundStyle(Theme.secondary)
                if configured {
                    Text("已設定 Cloudflare Access").accessibilityIdentifier("access-configured")
                    HStack {
                        Button("更換憑證") { replacing = true }.accessibilityIdentifier("access-replace")
                        Spacer()
                        Button("移除憑證", role: .destructive) {
                            do {
                                try store.removeAccessCredentials()
                                configured = false; replacing = false; clientID = ""; secret = ""; error = nil
                            } catch { self.error = error.localizedDescription }
                        }.accessibilityIdentifier("access-remove")
                    }
                }
                if !configured || replacing {
                    TextField("Client ID", text: $clientID)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                        .padding(14).background(Theme.background, in: RoundedRectangle(cornerRadius: 12))
                        .accessibilityIdentifier("access-client-id")
                    SecureField("Client Secret", text: $secret)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                        .padding(14).background(Theme.background, in: RoundedRectangle(cornerRadius: 12))
                        .accessibilityIdentifier("access-client-secret")
                    Button("儲存憑證") {
                        do {
                            try store.saveAccessCredentials(clientID: clientID, secret: secret)
                            secret = ""; clientID = ""; configured = true; replacing = false; error = nil
                        } catch { self.error = error.localizedDescription }
                    }
                    .disabled(clientID.isEmpty || secret.isEmpty || store.connecting)
                    .accessibilityIdentifier("access-save")
                }
                if let error {
                    Label(error, systemImage: "exclamationmark.circle")
                        .font(.caption)
                        .foregroundStyle(Theme.warning)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }.padding(.top, 10)
        } label: {
            Text("Cloudflare Access（選填）").accessibilityIdentifier("access-section")
        }
        .onAppear { configured = store.hasAccessCredentials() }
        .onChange(of: store.serverAddress) { _, _ in
            configured = store.hasAccessCredentials()
            replacing = false; clientID = ""; secret = ""; error = nil
        }
        #if DEBUG && DSA_ACCESS_UITEST
        .onAppear {
            // 僅 UITest 建置可預填；避免 XCTest typeText 把秘密寫進動作日誌。
            let environment = ProcessInfo.processInfo.environment
            if environment["DSA_ACCESS_TEST_PREFILL"] == "1" {
                clientID = environment["DSA_ACCESS_TEST_CLIENT_ID"] ?? ""
                secret = environment["DSA_ACCESS_TEST_CLIENT_SECRET"] ?? ""
            }
        }
        #endif
    }
}
