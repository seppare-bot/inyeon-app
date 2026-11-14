package com.inyeoncurator.app;

import android.annotation.SuppressLint;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.view.ViewGroup;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;

import android.Manifest;
import android.content.pm.PackageManager;
import android.os.Build;

import androidx.activity.OnBackPressedCallback;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.content.ContextCompat;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowCompat;
import androidx.core.view.WindowInsetsCompat;

import org.json.JSONObject;

/**
 * 인연큐레이터 — https://inyeoncurator.com 을 앱 안에서 여는 화면 (성모의 뜰 앱과 같은 구조).
 * 웹을 고치면(Netlify 배포) 앱을 다시 올리지 않아도 바로 반영된다.
 * 앱만 하는 일: 스토어 결제(Bridge), 로그인은 크롬 탭으로, 사진 고르기, 뒤로 가기.
 */
public class MainActivity extends AppCompatActivity {

    static final String DEEP_LINK_SCHEME = "com.inyeoncurator.app";
    static final String HOST = Uri.parse(BuildConfig.START_URL).getHost();
    static final int BG = 0xFF1C0609;

    static volatile MainActivity current;
    WebView webView;
    Bridge bridge;
    private boolean pageLoaded = false;
    private String pendingDeepLink = null;

    // 프로필 사진 올리기: 웹의 <input type=file> → 사진 고르기 화면
    private ValueCallback<Uri[]> fileCallback;
    private final ActivityResultLauncher<Intent> filePicker =
            registerForActivityResult(new ActivityResultContracts.StartActivityForResult(), r -> {
                if (fileCallback == null) return;
                Uri[] picked = WebChromeClient.FileChooserParams.parseResult(r.getResultCode(), r.getData());
                if (picked == null && r.getData() != null && r.getData().getClipData() != null) {
                    int n = r.getData().getClipData().getItemCount();
                    picked = new Uri[n];
                    for (int i = 0; i < n; i++) picked[i] = r.getData().getClipData().getItemAt(i).getUri();
                }
                fileCallback.onReceiveValue(picked);
                fileCallback = null;
            });

    // 알림 권한 (안드로이드 13 이상)
    private Runnable afterNotifPermission;
    private final ActivityResultLauncher<String> notifPermission =
            registerForActivityResult(new ActivityResultContracts.RequestPermission(), granted -> {
                Runnable r = afterNotifPermission; afterNotifPermission = null;
                if (r != null) r.run();
            });

    void withNotifPermission(Runnable then) {
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            afterNotifPermission = then;
            notifPermission.launch(Manifest.permission.POST_NOTIFICATIONS);
        } else then.run();
    }

    /** FCM 토큰이 바뀌면 웹이 서버에 다시 등록 */
    void pushTokenChanged(String token) {
        if (!pageLoaded) return;
        webView.evaluateJavascript("window.__onPushToken && window.__onPushToken(" + JSONObject.quote(token) + ")", null);
    }

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        current = this;
        PushService.ensureChannel(this);
        WindowCompat.setDecorFitsSystemWindows(getWindow(), false);
        WindowCompat.getInsetsController(getWindow(), getWindow().getDecorView()).setAppearanceLightStatusBars(false);
        WindowCompat.getInsetsController(getWindow(), getWindow().getDecorView()).setAppearanceLightNavigationBars(false);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(BG);
        webView = new WebView(this);
        webView.setBackgroundColor(BG);
        root.addView(webView, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);

        // 상태바·내비게이션바·노치·키보드만큼 안쪽으로 (화면이 가려지지 않게)
        ViewCompat.setOnApplyWindowInsetsListener(root, (v, insets) -> {
            Insets bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() | WindowInsetsCompat.Type.displayCutout());
            Insets ime = insets.getInsets(WindowInsetsCompat.Type.ime());
            v.setPadding(bars.left, bars.top, bars.right, Math.max(bars.bottom, ime.bottom));
            return WindowInsetsCompat.CONSUMED;
        });

        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);
        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setTextZoom(100);                             // 휴대폰 글자 크기 설정 때문에 3D 전시관 글자가 깨지지 않게
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(true);                  // 고른 사진(content://)을 웹이 읽을 수 있게
        s.setUserAgentString(s.getUserAgentString() + " InyeonApp/" + BuildConfig.VERSION_NAME);

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = callback;
                try {
                    Intent i = params.createIntent();
                    i.addCategory(Intent.CATEGORY_OPENABLE);
                    if (params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE) i.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
                    filePicker.launch(Intent.createChooser(i, "사진 고르기"));
                } catch (Exception e) {
                    fileCallback = null;
                    return false;
                }
                return true;
            }
        });
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri u = request.getUrl();
                if (DEEP_LINK_SCHEME.equals(u.getScheme())) { deliverDeepLink(u.toString()); return true; }
                String h = u.getHost();
                if (h != null && (h.equals(HOST) || h.equals("www." + HOST))) return false;   // 인연큐레이터 안 페이지(약관 등)
                openExternal(u);                                                              // 메일·바깥 링크는 다른 앱으로
                return true;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                pageLoaded = true;
                if (pendingDeepLink != null) { String d = pendingDeepLink; pendingDeepLink = null; deliverDeepLink(d); }
                if (pendingPush != null) { String p = pendingPush; pendingPush = null; webView.postDelayed(() -> webView.evaluateJavascript(p, null), 1500); }
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) showOffline();
            }
        });

        bridge = new Bridge(this);
        webView.addJavascriptInterface(bridge, "InyeonNative");

        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                webView.evaluateJavascript("(window.__onBack && window.__onBack()) ? '1' : '0'", v -> {
                    if ("\"1\"".equals(v)) return;
                    if (webView.canGoBack()) webView.goBack();
                    else finish();
                });
            }
        });

        if (savedInstanceState != null) webView.restoreState(savedInstanceState);
        else webView.loadUrl(BuildConfig.START_URL);
        handleIntent(getIntent());
    }

    private void showOffline() {
        pageLoaded = false;
        String html = "<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>"
                + "<body style='margin:0;font-family:sans-serif;background:#1c0609;color:#f4e6d0;display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;text-align:center;padding:24px;box-sizing:border-box'>"
                + "<h2 style='margin:0 0 8px;color:#e8c9a0'>인연큐레이터</h2><p style='color:#b9a68a;line-height:1.6'>인터넷에 연결되지 않았어요.<br>연결을 확인한 뒤 다시 시도해 주세요.</p>"
                + "<button onclick=\"location.href='" + BuildConfig.START_URL + "'\" style='margin-top:12px;padding:12px 28px;border:0;border-radius:6px;background:#d9b46a;color:#2a1a05;font-size:16px'>다시 시도</button></body>";
        webView.loadDataWithBaseURL(BuildConfig.START_URL, html, "text/html", "utf-8", null);
    }

    @Override
    protected void onNewIntent(@NonNull Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleIntent(intent);
    }

    private String pendingPush = null;

    private void handleIntent(Intent intent) {
        if (intent == null) return;
        String kind = intent.getStringExtra("push_kind");
        if (kind != null) {                                      // 알림을 눌러서 들어온 경우 → 웹이 알림함/대화를 열게
            intent.removeExtra("push_kind");
            String js = "window.__onPushOpen && window.__onPushOpen(" + JSONObject.quote(kind) + "," + JSONObject.quote(String.valueOf(intent.getStringExtra("push_ref"))) + ")";
            if (pageLoaded) webView.evaluateJavascript(js, null); else pendingPush = js;
        }
        if (intent.getData() == null) return;
        Uri u = intent.getData();
        if (DEEP_LINK_SCHEME.equals(u.getScheme())) deliverDeepLink(u.toString());
    }

    /** 카카오·구글·애플 로그인에서 돌아온 주소를 웹(JS)에 전달 */
    void deliverDeepLink(String url) {
        if (!pageLoaded) { pendingDeepLink = url; return; }
        webView.evaluateJavascript("window.__onDeepLink && window.__onDeepLink(" + JSONObject.quote(url) + ")", null);
    }

    void openExternal(Uri u) {
        try { startActivity(new Intent(Intent.ACTION_VIEW, u)); } catch (Exception ignored) { }
    }

    /** JS 로 결과 돌려주기 (Bridge 에서 사용) */
    void resolveJs(int id, boolean ok, String payload) {
        runOnUiThread(() -> webView.evaluateJavascript(
                "window.__nativeResolve && window.__nativeResolve(" + id + "," + ok + "," + JSONObject.quote(payload) + ")", null));
    }

    @Override
    protected void onSaveInstanceState(@NonNull Bundle outState) {
        super.onSaveInstanceState(outState);
        webView.saveState(outState);
    }

    @Override
    protected void onPause() {
        super.onPause();
        PushService.foreground = false;
        webView.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        PushService.foreground = true;
        webView.onResume();
    }

    @Override
    protected void onDestroy() {
        if (current == this) current = null;
        if (bridge != null) bridge.destroy();
        if (webView != null) {
            ((ViewGroup) webView.getParent()).removeView(webView);
            webView.destroy();
        }
        super.onDestroy();
    }
}
