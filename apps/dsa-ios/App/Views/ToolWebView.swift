import SwiftUI
import WebKit
import DSACore

struct ToolWebView: View {
    let path: String
    let title: String
    @EnvironmentObject private var store: AppStore
    @State private var loading = true
    @State private var error: String?
    @State private var reloadID = UUID()
    @State private var exportedFile: WebExportFile?
    @State private var progress = 0.0
    @State private var exportError: String?

    var body: some View {
        Group {
            if let error {
                // 載入失敗時不留 WebView：重試會以新的 reloadID 重建。
                ErrorStateView(message: error, retry: reload)
                    .padding()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .accessibilityIdentifier("tool-error")
            } else if let baseURL = store.baseURL, store.session != nil {
                AuthenticatedWebContent(baseURL: baseURL, path: path, dataStore: store.toolWebDataStore,
                                        prepareCookies: { try await store.toolCookies() },
                                        loading: $loading, progress: $progress, error: $error,
                                        exportError: $exportError, exportedFile: $exportedFile)
                    .id(reloadID)
                    .overlay(alignment: .top) {
                        if loading {
                            ProgressView(value: max(progress, 0.05))
                                .progressViewStyle(.linear)
                                .tint(Theme.accent)
                                .accessibilityIdentifier("tool-loading")
                        }
                    }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Theme.background)
        .navigationTitle(title).navigationBarTitleDisplayMode(.inline)
        .toolbar(.hidden, for: .tabBar)
        .alert("匯出失敗", isPresented: Binding(get: { exportError != nil }, set: { if !$0 { exportError = nil } })) {
            Button("好", role: .cancel) { }
        } message: {
            Text(exportError ?? "")
        }
        .sheet(item: $exportedFile) { file in
            WebExportShareSheet(fileURL: file.url)
                .onDisappear { file.removeTemporaryCopy() }
        }
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button(action: reload) { Image(systemName: "arrow.clockwise") }
                    .accessibilityLabel("重新載入工具")
            }
        }
    }

    private func reload() {
        error = nil
        loading = true
        progress = 0
        reloadID = UUID()
    }
}

private struct AuthenticatedWebContent: UIViewRepresentable {
    let baseURL: URL
    let path: String
    let dataStore: WKWebsiteDataStore
    let prepareCookies: () async throws -> [HTTPCookie]
    @Binding var loading: Bool
    @Binding var progress: Double
    @Binding var error: String?
    @Binding var exportError: String?
    @Binding var exportedFile: WebExportFile?

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = dataStore
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
        context.coordinator.observeProgress(of: web)
        guard let url = WebNavigationPolicy.embeddedToolURL(path: path, baseURL: baseURL),
              WebNavigationPolicy.sameOrigin(url, baseURL) else {
            error = "工具網址不屬於目前的分析服務。"
            loading = false
            return web
        }
        Task { @MainActor in
            do {
                for cookie in try await prepareCookies() {
                    await config.websiteDataStore.httpCookieStore.setCookie(cookie)
                }
                web.load(URLRequest(url: url))
            } catch {
                self.error = error.localizedDescription
                loading = false
            }
        }
        return web
    }

    func updateUIView(_ uiView: WKWebView, context: Context) { }

    static func dismantleUIView(_ uiView: WKWebView, coordinator: Coordinator) {
        coordinator.cancelDownloads()
        coordinator.stopObservingProgress()
        uiView.stopLoading()
        uiView.navigationDelegate = nil
        uiView.uiDelegate = nil
    }

    @MainActor final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
        var parent: AuthenticatedWebContent
        private var downloads: [ObjectIdentifier: WKDownload] = [:]
        private var destinations: [ObjectIdentifier: URL] = [:]
        private var blockedAccessRedirect = false
        private var downloadStarting = false
        private var progressObservation: NSKeyValueObservation?
        init(_ parent: AuthenticatedWebContent) { self.parent = parent }

        func observeProgress(of web: WKWebView) {
            progressObservation = web.observe(\.estimatedProgress, options: [.new]) { [weak self] _, change in
                guard let value = change.newValue else { return }
                Task { @MainActor in self?.parent.progress = value }
            }
        }

        func stopObservingProgress() {
            progressObservation?.invalidate()
            progressObservation = nil
        }

        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
            if CloudflareAccess.isLoginURL(url) {
                blockedAccessRedirect = true
                parent.error = DSAError.cloudflareAccess.localizedDescription
                parent.loading = false
                decisionHandler(.cancel)
                return
            }
            let origin = navigationAction.sourceFrame.securityOrigin
            let source = WebNavigationPolicy.sourceOrigin(protocolValue: origin.protocol, host: origin.host, port: origin.port)
            switch WebNavigationPolicy.action(url: url, baseURL: parent.baseURL, sourceOrigin: source,
                                               shouldDownload: navigationAction.shouldPerformDownload,
                                               userLink: navigationAction.navigationType == .linkActivated) {
            case .allow:
                blockedAccessRedirect = false
                downloadStarting = false
                decisionHandler(.allow)
            case .download:
                parent.error = nil
                downloadStarting = true
                decisionHandler(.download)
            case .external:
                // 外部新聞只由使用者明確點擊交給系統瀏覽器，不把服務 cookie 帶往別站。
                UIApplication.shared.open(url)
                decisionHandler(.cancel)
            case .cancel:
                // 整頁錯誤會移除 WebView，只有主頁框被擋才算；子頁框（如 srcdoc iframe）被擋不能賠上整頁。
                if url.absoluteString != "about:blank", navigationAction.targetFrame?.isMainFrame == true {
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
            let shouldDownload = !navigationResponse.canShowMIMEType || disposition.hasPrefix("attachment")
            if shouldDownload { downloadStarting = true }
            decisionHandler(shouldDownload ? .download : .allow)
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
                parent.exportError = "下載來源不屬於目前的分析服務。"
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
                parent.exportError = "無法保存匯出檔案：\(error.localizedDescription)"
                completionHandler(nil)
            }
        }

        func download(_ download: WKDownload, willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                      decisionHandler: @escaping (WKDownload.RedirectPolicy) -> Void) {
            guard let url = request.url, WebNavigationPolicy.sameOrigin(url, parent.baseURL) else {
                if request.url.map(CloudflareAccess.isLoginURL) == true {
                    parent.error = DSAError.cloudflareAccess.localizedDescription
                } else {
                    parent.exportError = "下載嘗試轉送到其他服務，已取消。"
                }
                parent.loading = false
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
            // 匯出失敗不影響已載入的頁面，用提示框，不換成整頁錯誤。
            parent.loading = false
            if (error as NSError).code != NSURLErrorCancelled {
                parent.exportError = WebNavigationPolicy.pageLoadMessage(for: error)
            }
        }

        func cancelDownloads() {
            let activeDownloads = Array(downloads.values)
            downloads.removeAll()
            for download in activeDownloads { download.cancel { _ in } }
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            downloadStarting = false
            parent.loading = false
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { fail(error) }
        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { fail(error) }

        private func fail(_ error: Error) {
            if WebNavigationPolicy.preservesAccessError(error, blockedAccessRedirect: blockedAccessRedirect) { return }
            if (error as NSError).code == NSURLErrorCancelled { return }
            if WebNavigationPolicy.isDownloadInterruption(error, downloadStarting: downloadStarting) {
                downloadStarting = false
                return
            }
            parent.loading = false
            parent.error = WebNavigationPolicy.pageLoadMessage(for: error)
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
