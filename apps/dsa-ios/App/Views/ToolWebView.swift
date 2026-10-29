import SwiftUI
import WebKit

struct ToolWebView: View {
    let path: String
    let title: String
    @EnvironmentObject private var store: AppStore
    @State private var loading = true
    @State private var error: String?
    @State private var reloadID = UUID()

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                Image(systemName: "lock.shield")
                Text("已連接你的分析服務 · 完整研究工具")
                Spacer()
            }
            .font(.caption2).foregroundStyle(Theme.secondary).padding(12).background(Theme.surface)
            if loading { ProgressView().tint(Theme.accent).padding(10) }
            if let error {
                ErrorStateView(message: error, retry: { self.error = nil; loading = true; reloadID = UUID() }).padding()
            }
            if let baseURL = store.baseURL, let session = store.session {
                AuthenticatedWebContent(baseURL: baseURL, path: path, session: session,
                                        loading: $loading, error: $error)
                    .id(reloadID)
            }
        }
        .background(Theme.background)
        .navigationTitle(title).navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button { error = nil; loading = true; reloadID = UUID() } label: { Image(systemName: "arrow.clockwise") }
                    .accessibilityLabel("重新載入工具")
            }
        }
    }
}

private struct AuthenticatedWebContent: UIViewRepresentable {
    let baseURL: URL
    let path: String
    let session: URLSession
    @Binding var loading: Bool
    @Binding var error: String?

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        config.userContentController.addUserScript(WKUserScript(
            source: "try { localStorage.setItem('dsa.uiLanguage', 'zh-TW'); } catch (_) {}",
            injectionTime: .atDocumentStart, forMainFrameOnly: true))
        let web = WKWebView(frame: .zero, configuration: config)
        web.isOpaque = false
        web.backgroundColor = UIColor(Theme.background)
        web.scrollView.backgroundColor = UIColor(Theme.background)
        web.navigationDelegate = context.coordinator
        web.uiDelegate = context.coordinator
        web.allowsBackForwardNavigationGestures = true
        guard let url = URL(string: path, relativeTo: baseURL)?.absoluteURL,
              Coordinator.sameOrigin(url, baseURL) else {
            error = "工具網址不屬於目前的分析服務。"
            loading = false
            return web
        }
        Task { @MainActor in
            for cookie in session.configuration.httpCookieStorage?.cookies(for: baseURL) ?? [] where cookie.name == "dsa_session" {
                await config.websiteDataStore.httpCookieStore.setCookie(cookie)
            }
            web.load(URLRequest(url: url))
        }
        return web
    }

    func updateUIView(_ uiView: WKWebView, context: Context) { }

    static func dismantleUIView(_ uiView: WKWebView, coordinator: Coordinator) {
        uiView.stopLoading()
        uiView.navigationDelegate = nil
        uiView.uiDelegate = nil
    }

    @MainActor final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate {
        var parent: AuthenticatedWebContent
        init(_ parent: AuthenticatedWebContent) { self.parent = parent }

        static func sameOrigin(_ lhs: URL, _ rhs: URL) -> Bool {
            lhs.scheme?.lowercased() == rhs.scheme?.lowercased()
                && lhs.host?.lowercased() == rhs.host?.lowercased()
                && (lhs.port ?? (lhs.scheme == "https" ? 443 : 80)) == (rhs.port ?? (rhs.scheme == "https" ? 443 : 80))
        }

        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
            if Self.sameOrigin(url, parent.baseURL) { decisionHandler(.allow); return }
            // 外部新聞只由使用者明確點擊交給系統瀏覽器，不把服務 cookie 帶往別站。
            if navigationAction.navigationType == .linkActivated,
               ["http", "https"].contains(url.scheme?.lowercased() ?? "") {
                UIApplication.shared.open(url)
            } else if url.absoluteString != "about:blank" {
                parent.error = "工具嘗試導向其他服務，已停止載入。"
                parent.loading = false
            }
            decisionHandler(.cancel)
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            parent.loading = false
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { fail(error) }
        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { fail(error) }

        private func fail(_ error: Error) {
            if (error as NSError).code == NSURLErrorCancelled { return }
            parent.loading = false
            parent.error = error.localizedDescription
        }

        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                     for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
            if let url = navigationAction.request.url, Self.sameOrigin(url, parent.baseURL) {
                webView.load(navigationAction.request)
            }
            return nil
        }
    }
}
