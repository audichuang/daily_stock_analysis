import DSACore
import SwiftUI

/// 冷啟動只顯示連接中；太久才給慢速提示與取消，不先閃登入表單。
struct StartupConnectingView: View {
    @EnvironmentObject private var store: AppStore
    @State private var slow = false

    private var host: String {
        ServerAddress.normalized(store.serverAddress)?.host ?? store.serverAddress
    }

    var body: some View {
        VStack(spacing: 14) {
            BrandMark().frame(width: 48, height: 48)
            ProgressView("正在連接分析服務…")
                .foregroundStyle(Theme.secondary)
                .accessibilityIdentifier("startup-connecting")
            Text(host).font(.caption).foregroundStyle(Theme.secondary)
            if slow {
                Text("連線比平常久，服務可能正在啟動或網路不穩。")
                    .font(.caption).foregroundStyle(Theme.secondary)
                    .multilineTextAlignment(.center)
                    .accessibilityIdentifier("startup-slow")
                Button("取消") { store.cancelConnecting() }
                    .frame(minHeight: 44)
                    .accessibilityIdentifier("startup-cancel")
            }
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Theme.background)
        .task {
            try? await Task.sleep(for: .seconds(6))
            if !Task.isCancelled { slow = true }
        }
    }
}

struct ConnectionView: View {
    @EnvironmentObject private var store: AppStore
    @State private var password = ""
    @State private var showPassword = false
    @FocusState private var focus: Field?

    private enum Field: Hashable { case address, password }

    private var canSubmit: Bool {
        !store.connecting && !store.serverAddress.isEmpty && (!store.needsPassword || !password.isEmpty)
    }

    /// 該貼在欄位旁的錯誤；欄位不在目前畫面時才落到共用錯誤框。
    private func inlineError(_ field: ConnectionField) -> String? {
        guard let issue = store.connectionIssue, issue.field == field else { return nil }
        return issue.message
    }

    private var generalError: String? {
        guard let issue = store.connectionIssue else { return nil }
        switch issue.field {
        case .general: return issue.message
        case .address: return store.needsPassword ? issue.message : nil
        case .password: return store.needsPassword ? nil : issue.message
        case .access: return nil
        }
    }

    var body: some View {
        NavigationStack {
            PageScroll {
                HStack(spacing: 12) {
                    BrandMark().frame(width: 40, height: 40)
                    Text("Daily Stock AI")
                        .font(.title3.weight(.bold))
                        .foregroundStyle(Theme.text)
                }
                .padding(.top, 12)
                DSACard {
                    VStack(alignment: .leading, spacing: 14) {
                        Text(store.needsPassword ? "登入分析服務" : "連接分析服務")
                            .font(.headline).foregroundStyle(Theme.text)
                        if store.needsPassword {
                            serviceRow
                            passwordField
                            if let message = inlineError(.password) { fieldError(message, id: "connection.error.password") }
                        } else {
                            addressField
                            if let message = inlineError(.address) { fieldError(message, id: "connection.error.address") }
                        }
                        if let message = generalError {
                            ErrorStateView(title: "無法連線", message: message)
                        }
                        submitButton
                        if store.connecting {
                            Button("取消") { store.cancelConnecting() }
                                .frame(maxWidth: .infinity, minHeight: 44)
                                .accessibilityIdentifier("connect-cancel")
                        }
                        Divider().overlay(Theme.border)
                        if let message = inlineError(.access) { fieldError(message, id: "connection.error.access") }
                        AccessSettingsView()
                    }
                }
                Text("AI 分析供研究參考，評分不代表勝率。")
                    .font(.caption).foregroundStyle(Theme.secondary)
            }
            .scrollDismissesKeyboard(.interactively)
        }
        .onChange(of: store.needsPassword) { _, needsPassword in
            // 回到改網址就是換服務，舊密碼不留在記憶體。
            if !needsPassword { password = ""; showPassword = false }
        }
        #if DEBUG && DSA_ACCESS_UITEST
        .onAppear {
            if let value = ProcessInfo.processInfo.environment["DSA_ACCESS_TEST_PASSWORD"] { password = value }
        }
        #endif
    }

    private var serviceRow: some View {
        HStack(spacing: 8) {
            Image(systemName: "network").foregroundStyle(Theme.secondary).accessibilityHidden(true)
            Text(ServerAddress.normalized(store.serverAddress)?.host ?? store.serverAddress)
                .font(.caption).foregroundStyle(Theme.secondary)
                .lineLimit(1).truncationMode(.middle)
            Spacer(minLength: 8)
            Button("變更") {
                store.needsPassword = false
                store.connectionIssue = nil
                focus = .address
            }
            .font(.caption.weight(.semibold))
            .frame(minHeight: 44)
            .accessibilityLabel("變更服務網址")
            .accessibilityIdentifier("change-server-address")
        }
    }

    private var addressField: some View {
        TextField("https://你的服務網址", text: $store.serverAddress)
            .keyboardType(.URL).textContentType(.URL)
            .textInputAutocapitalization(.never).autocorrectionDisabled()
            .submitLabel(.go)
            .focused($focus, equals: .address)
            .onSubmit { submit() }
            .padding(14).background(Theme.background, in: RoundedRectangle(cornerRadius: 12))
            .accessibilityIdentifier("server-address")
    }

    private var passwordField: some View {
        HStack(spacing: 8) {
            Group {
                if showPassword {
                    TextField("管理員密碼", text: $password)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                } else {
                    SecureField("管理員密碼", text: $password)
                }
            }
            .textContentType(.password)
            .submitLabel(.go)
            .focused($focus, equals: .password)
            .onSubmit { submit() }
            .accessibilityIdentifier("server-password")
            Button {
                showPassword.toggle()
                focus = .password
            } label: {
                Image(systemName: showPassword ? "eye.slash" : "eye")
                    .foregroundStyle(Theme.secondary)
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(showPassword ? "隱藏密碼" : "顯示密碼")
            .accessibilityIdentifier("server-password-toggle")
        }
        .padding(.leading, 14)
        .frame(minHeight: 48)
        .background(Theme.background, in: RoundedRectangle(cornerRadius: 12))
    }

    private var submitButton: some View {
        Button { submit() } label: {
            HStack {
                if store.connecting { ProgressView().tint(Theme.background) }
                Text(store.connecting ? "連接中…" : store.needsPassword ? "登入" : "連接服務")
                Spacer()
                Image(systemName: "arrow.right")
            }
        }
        .buttonStyle(PressableButtonStyle())
        .disabled(!canSubmit)
        .accessibilityIdentifier("connect-button")
    }

    private func fieldError(_ message: String, id: String) -> some View {
        Label(message, systemImage: "exclamationmark.circle")
            .font(.caption)
            .foregroundStyle(Theme.warning)
            .fixedSize(horizontal: false, vertical: true)
            .accessibilityIdentifier(id)
    }

    private func submit() {
        guard canSubmit else { return }
        focus = nil
        let value = store.needsPassword ? password : nil
        // 密碼只在登入成功、換服務時才清（上面的 onChange 與離開此畫面），打錯不用重打。
        Task { await store.submitConnection(password: value) }
    }
}
