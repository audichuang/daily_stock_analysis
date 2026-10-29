import SwiftUI
import WebKit

struct ToolWebView: View {
    let path: String
    let title: String
    @EnvironmentObject private var store: AppStore
    @State private var loading = true
    @State private var error: String?
    @State private var reloadID = UUID()
    @State private var exportedFile: WebExportFile?

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
                                        loading: $loading, error: $error, exportedFile: $exportedFile)
                    .id(reloadID)
            }
        }
        .background(Theme.background)
        .navigationTitle(title).navigationBarTitleDisplayMode(.inline)
        .sheet(item: $exportedFile) { file in
            WebExportShareSheet(fileURL: file.url)
                .onDisappear { file.removeTemporaryCopy() }
        }
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
    @Binding var exportedFile: WebExportFile?

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
              WebNavigationPolicy.sameOrigin(url, baseURL) else {
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
        coordinator.cancelDownloads()
        uiView.stopLoading()
        uiView.navigationDelegate = nil
        uiView.uiDelegate = nil
    }

    @MainActor final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
        var parent: AuthenticatedWebContent
        private var downloads: [ObjectIdentifier: WKDownload] = [:]
        private var destinations: [ObjectIdentifier: URL] = [:]
        init(_ parent: AuthenticatedWebContent) { self.parent = parent }

        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
            let origin = navigationAction.sourceFrame.securityOrigin
            var source = URLComponents()
            source.scheme = origin.protocol
            source.host = origin.host
            if origin.port != 0 { source.port = origin.port }
            switch WebNavigationPolicy.action(url: url, baseURL: parent.baseURL, sourceOrigin: source.url,
                                               shouldDownload: navigationAction.shouldPerformDownload,
                                               userLink: navigationAction.navigationType == .linkActivated) {
            case .allow: decisionHandler(.allow)
            case .download:
                parent.error = nil
                decisionHandler(.download)
            case .external:
                // 外部新聞只由使用者明確點擊交給系統瀏覽器，不把服務 cookie 帶往別站。
                UIApplication.shared.open(url)
                decisionHandler(.cancel)
            case .cancel:
                if url.absoluteString != "about:blank" {
                    parent.error = "工具嘗試導向其他服務，已停止載入。"
                    parent.loading = false
                }
                decisionHandler(.cancel)
            }
        }

        func webView(_ webView: WKWebView, decidePolicyFor navigationResponse: WKNavigationResponse,
                     decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
            guard let url = navigationResponse.response.url, WebNavigationPolicy.trustedDownload(url, baseURL: parent.baseURL) else {
                decisionHandler(.cancel)
                return
            }
            let disposition = (navigationResponse.response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Content-Disposition")?.lowercased() ?? ""
            decisionHandler(!navigationResponse.canShowMIMEType || disposition.hasPrefix("attachment") ? .download : .allow)
        }

        func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
            attach(download)
        }

        func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
            attach(download)
        }

        private func attach(_ download: WKDownload) {
            downloads[ObjectIdentifier(download)] = download
            download.delegate = self
        }

        func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String,
                      completionHandler: @escaping (URL?) -> Void) {
            guard let url = response.url, WebNavigationPolicy.trustedDownload(url, baseURL: parent.baseURL) else {
                parent.error = "下載來源不屬於目前的分析服務。"
                completionHandler(nil)
                return
            }
            do {
                let directory = FileManager.default.temporaryDirectory.appendingPathComponent("DSAExport-\(UUID().uuidString)", isDirectory: true)
                try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                                                        attributes: [.protectionKey: FileProtectionType.complete])
                let destination = directory.appendingPathComponent(WebNavigationPolicy.safeFilename(suggestedFilename))
                destinations[ObjectIdentifier(download)] = destination
                completionHandler(destination)
            } catch {
                parent.error = "無法保存匯出檔案：\(error.localizedDescription)"
                completionHandler(nil)
            }
        }

        func download(_ download: WKDownload, willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                      decisionHandler: @escaping (WKDownload.RedirectPolicy) -> Void) {
            guard let url = request.url, WebNavigationPolicy.sameOrigin(url, parent.baseURL) else {
                parent.error = "下載嘗試轉送到其他服務，已取消。"
                decisionHandler(.cancel)
                return
            }
            decisionHandler(.allow)
        }

        func downloadDidFinish(_ download: WKDownload) {
            let identifier = ObjectIdentifier(download)
            downloads.removeValue(forKey: identifier)
            guard let destination = destinations.removeValue(forKey: identifier) else { return }
            parent.loading = false
            parent.exportedFile = WebExportFile(url: destination)
        }

        func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
            let identifier = ObjectIdentifier(download)
            downloads.removeValue(forKey: identifier)
            if let destination = destinations.removeValue(forKey: identifier) {
                WebExportFile(url: destination).removeTemporaryCopy()
            }
            fail(error)
        }

        func cancelDownloads() {
            let activeDownloads = Array(downloads.values)
            downloads.removeAll()
            for download in activeDownloads { download.cancel { _ in } }
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
            if let url = navigationAction.request.url, WebNavigationPolicy.sameOrigin(url, parent.baseURL) {
                webView.load(navigationAction.request)
            }
            return nil
        }
    }
}

private struct WebExportFile: Identifiable {
    let url: URL
    var id: URL { url }

    func removeTemporaryCopy() {
        // 僅清理由這次下載建立的 UUID 暫存目錄，使用者另存的檔案不受影響。
        try? FileManager.default.removeItem(at: url.deletingLastPathComponent())
    }
}

private struct WebExportShareSheet: UIViewControllerRepresentable {
    let fileURL: URL

    func makeUIViewController(context: Context) -> UIActivityViewController {
        let controller = UIActivityViewController(activityItems: [fileURL], applicationActivities: nil)
        controller.view.accessibilityIdentifier = "web-export-share"
        return controller
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) { }
}
