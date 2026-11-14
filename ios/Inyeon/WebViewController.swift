import UIKit
import WebKit
import AuthenticationServices
import SafariServices

/// 인연큐레이터 — https://inyeoncurator.com 을 앱 안에서 여는 화면 (안드로이드 앱과 같은 구조).
/// 웹을 고치면(Netlify 배포) 앱을 다시 올리지 않아도 바로 반영된다.
/// 앱만 하는 일: App Store 결제(Store), 로그인은 시스템 로그인 창으로, 오프라인 안내.
/// 웹에는 안드로이드와 같은 window.InyeonNative 를 제공한다 (platform() 만 'ios').
final class WebViewController: UIViewController, WKScriptMessageHandler, WKNavigationDelegate, WKUIDelegate,
                               ASWebAuthenticationPresentationContextProviding {
    static let startURL = URL(string: "https://inyeoncurator.com/")!
    static let redirectScheme = "com.inyeoncurator.app"
    private var web: WKWebView!
    private var authSession: ASWebAuthenticationSession?
    private let bg = UIColor(red: 0x1C/255.0, green: 0x06/255.0, blue: 0x09/255.0, alpha: 1)

    override var preferredStatusBarStyle: UIStatusBarStyle { .lightContent }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = bg

        let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0"
        let build = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "0"
        let shim = """
        window.InyeonNative = {
          version: function(){ return '\(version) (\(build))'; },
          platform: function(){ return 'ios'; },
          openUrl: function(u){ window.webkit.messageHandlers.inyeon.postMessage({ m: 'openUrl', url: String(u) }); },
          call: function(method, id, json){ window.webkit.messageHandlers.inyeon.postMessage({ m: 'call', method: method, id: id, json: json }); }
        };
        (function(){
          var post = function(lvl, a){ try { window.webkit.messageHandlers.inyeonLog.postMessage(lvl + ' ' + Array.prototype.map.call(a, String).join(' ')); } catch (e) {} };
          var e0 = console.error; console.error = function(){ post('error', arguments); e0.apply(console, arguments); };
          window.addEventListener('error', function(ev){ post('onerror', [ev.message, ev.filename + ':' + ev.lineno]); });
        })();
        """
        let cfg = WKWebViewConfiguration()
        let ucc = WKUserContentController()
        ucc.addUserScript(WKUserScript(source: shim, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        ucc.add(self, name: "inyeon")
        ucc.add(self, name: "inyeonLog")
        cfg.userContentController = ucc
        cfg.allowsInlineMediaPlayback = true
        cfg.applicationNameForUserAgent = "InyeonApp/\(version) iOS"

        web = WKWebView(frame: .zero, configuration: cfg)
        web.navigationDelegate = self
        web.uiDelegate = self
        web.isOpaque = false
        web.backgroundColor = bg
        web.scrollView.backgroundColor = bg
        web.scrollView.bounces = false
        web.scrollView.contentInsetAdjustmentBehavior = .never
        web.allowsBackForwardNavigationGestures = true      // 약관 페이지 등에서 밀어서 돌아가기
        if #available(iOS 16.4, *) { web.isInspectable = true }
        web.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(web)
        let g = view.safeAreaLayoutGuide
        NSLayoutConstraint.activate([
            web.topAnchor.constraint(equalTo: g.topAnchor),
            web.bottomAnchor.constraint(equalTo: g.bottomAnchor),
            web.leadingAnchor.constraint(equalTo: g.leadingAnchor),
            web.trailingAnchor.constraint(equalTo: g.trailingAnchor),
        ])
        web.load(URLRequest(url: Self.startURL))
    }

    // MARK: - JS → 앱
    func userContentController(_ ucc: WKUserContentController, didReceive message: WKScriptMessage) {
        if message.name == "inyeonLog" { NSLog("[InyeonJS] %@", String(describing: message.body)); return }
        guard let body = message.body as? [String: Any], let m = body["m"] as? String else { return }
        if m == "openUrl", let s = body["url"] as? String, let url = URL(string: s) { openUrl(url); return }
        guard m == "call", let method = body["method"] as? String else { return }
        let id = (body["id"] as? NSNumber)?.intValue ?? 0
        let arg = (body["json"] as? String).flatMap { try? JSONSerialization.jsonObject(with: Data($0.utf8)) as? [String: Any] } ?? [:]
        handle(method, id: id, arg: arg)
    }

    private func handle(_ method: String, id: Int, arg: [String: Any]) {
        Task { @MainActor in
            do {
                switch method {
                case "buy":
                    resolve(id, ok: true, try await Store.shared.buy(arg["productId"] as? String ?? "", accountId: arg["accountId"] as? String ?? ""))
                case "consume":
                    await Store.shared.finish(arg["purchaseToken"] as? String ?? "")
                    resolve(id, ok: true, [String: Any]())
                case "unfinished":
                    resolve(id, ok: true, await Store.shared.unfinished())
                case "pushToken":
                    resolve(id, ok: true, try await Push.shared.requestToken())
                case "entitlements":
                    resolve(id, ok: true, try await Store.shared.entitlements())
                default:
                    resolve(id, ok: false, ["code": "unknown", "message": "알 수 없는 요청: \(method)"])
                }
            } catch let e as StoreError {
                resolve(id, ok: false, ["code": e.code, "message": e.message])
            } catch {
                resolve(id, ok: false, ["code": "error", "message": error.localizedDescription])
            }
        }
    }

    private func resolve(_ id: Int, ok: Bool, _ payload: Any) {
        let data = (try? JSONSerialization.data(withJSONObject: payload)) ?? Data("{}".utf8)
        let json = String(data: data, encoding: .utf8) ?? "{}"
        let lit = (try? JSONSerialization.data(withJSONObject: [json])).flatMap { String(data: $0, encoding: .utf8) } ?? "[\"{}\"]"
        web.evaluateJavaScript("window.__nativeResolve && window.__nativeResolve(\(id), \(ok), \(lit)[0]);", completionHandler: nil)
    }

    // MARK: - 링크 · 로그인
    private func isOurHost(_ url: URL) -> Bool {
        guard let h = url.host else { return false }
        return h == "inyeoncurator.com" || h == "www.inyeoncurator.com"
    }

    private func openUrl(_ url: URL) {
        let s = url.absoluteString
        if s.contains("/auth/v1/authorize") || s.contains("/auth/v1/user/identities/authorize") {
            // 카카오·Google·Apple 로그인: 시스템 로그인 창 → com.inyeoncurator.app://auth 로 돌아옴
            let session = ASWebAuthenticationSession(url: url, callbackURLScheme: Self.redirectScheme) { [weak self] cb, _ in
                if let cb = cb { self?.deliverDeepLink(cb) }
                self?.authSession = nil
            }
            session.presentationContextProvider = self
            session.prefersEphemeralWebBrowserSession = false
            authSession = session
            session.start()
        } else if url.scheme == "http" || url.scheme == "https" {
            present(SFSafariViewController(url: url), animated: true)
        } else {
            UIApplication.shared.open(url)
        }
    }

    func deliverDeepLink(_ url: URL) {
        let lit = (try? JSONSerialization.data(withJSONObject: [url.absoluteString])).flatMap { String(data: $0, encoding: .utf8) } ?? "[\"\"]"
        web.evaluateJavaScript("window.__onDeepLink && window.__onDeepLink(\(lit)[0]);", completionHandler: nil)
    }

    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        view.window ?? ASPresentationAnchor()
    }

    // 인연큐레이터 안 페이지(약관 등)는 그대로, 바깥 링크는 사파리 창으로
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { return decisionHandler(.allow) }
        if url.scheme == Self.redirectScheme { deliverDeepLink(url); return decisionHandler(.cancel) }
        if url.scheme == "about" || url.scheme == "data" || url.scheme == "blob" { return decisionHandler(.allow) }
        if action.targetFrame?.isMainFrame == false { return decisionHandler(.allow) }   // 웹 안의 작은 프레임
        if isOurHost(url) { return decisionHandler(.allow) }
        if url.scheme == "mailto" || url.scheme == "tel" { UIApplication.shared.open(url); return decisionHandler(.cancel) }
        openUrl(url)
        decisionHandler(.cancel)
    }

    // target=_blank / window.open
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url { if isOurHost(url) { webView.load(URLRequest(url: url)) } else { openUrl(url) } }
        return nil
    }

    // 인터넷이 끊겨 첫 화면을 못 불러오면 안내와 다시 시도 버튼
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        let code = (error as NSError).code
        if code == NSURLErrorCancelled { return }
        let html = """
        <!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>
        <body style='margin:0;font-family:-apple-system,sans-serif;background:#1c0609;color:#f4e6d0;display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;text-align:center;padding:24px;box-sizing:border-box'>
        <h2 style='margin:0 0 8px;color:#e8c9a0'>인연큐레이터</h2><p style='color:#b9a68a;line-height:1.6'>인터넷에 연결되지 않았어요.<br>연결을 확인한 뒤 다시 시도해 주세요.</p>
        <button onclick="location.href='\(Self.startURL.absoluteString)'" style='margin-top:12px;padding:12px 28px;border:0;border-radius:6px;background:#d9b46a;color:#2a1a05;font-size:16px'>다시 시도</button></body>
        """
        webView.loadHTMLString(html, baseURL: Self.startURL)
    }

    // alert / confirm
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let a = UIAlertController(title: nil, message: message, preferredStyle: .alert)
        a.addAction(UIAlertAction(title: "확인", style: .default) { _ in completionHandler() })
        present(a, animated: true)
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let a = UIAlertController(title: nil, message: message, preferredStyle: .alert)
        a.addAction(UIAlertAction(title: "취소", style: .cancel) { _ in completionHandler(false) })
        a.addAction(UIAlertAction(title: "확인", style: .default) { _ in completionHandler(true) })
        present(a, animated: true)
    }

    // 웹 프로세스가 죽으면(메모리 부족 등) 다시 띄우기
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { webView.reload() }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        Push.shared.onOpen = { [weak self] kind, ref in self?.pushOpened(kind, ref) }
        if let p = Push.shared.pendingOpen {
            Push.shared.pendingOpen = nil
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in self?.pushOpened(p.0, p.1) }
        }
    }

    /// 알림을 눌러 들어온 경우 → 웹이 알림함/대화를 열게
    func pushOpened(_ kind: String, _ ref: String) {
        let lit = (try? JSONSerialization.data(withJSONObject: [kind, ref])).flatMap { String(data: $0, encoding: .utf8) } ?? "[\"\",\"\"]"
        web.evaluateJavaScript("window.__onPushOpen && window.__onPushOpen.apply(null, \(lit));", completionHandler: nil)
    }
}
