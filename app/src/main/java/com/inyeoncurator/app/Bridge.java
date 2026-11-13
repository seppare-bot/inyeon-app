package com.inyeoncurator.app;

import android.net.Uri;
import android.webkit.JavascriptInterface;

import androidx.annotation.NonNull;
import androidx.browser.customtabs.CustomTabColorSchemeParams;
import androidx.browser.customtabs.CustomTabsIntent;

import com.android.billingclient.api.BillingClient;
import com.android.billingclient.api.BillingClientStateListener;
import com.android.billingclient.api.BillingFlowParams;
import com.android.billingclient.api.BillingResult;
import com.android.billingclient.api.ConsumeParams;
import com.android.billingclient.api.PendingPurchasesParams;
import com.android.billingclient.api.ProductDetails;
import com.android.billingclient.api.Purchase;
import com.android.billingclient.api.PurchasesUpdatedListener;
import com.android.billingclient.api.QueryProductDetailsParams;
import com.android.billingclient.api.QueryPurchasesParams;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.Collections;
import java.util.List;

/**
 * 웹(JS) ↔ 안드로이드 연결. 웹에서는 window.InyeonNative 로 보인다.
 * JS: InyeonNative.call(method, id, json) → 결과는 window.__nativeResolve(id, ok, json) 으로 돌아감.
 *   buy        : 구글플레이 결제창 { productId, accountId } → { productId, purchaseToken, orderId }
 *   consume    : 소비형 상품(관람권 등) 소비 처리 → 다시 살 수 있게 (서버가 지급을 확인한 뒤에만 부름)
 *   unfinished : 결제는 됐는데 아직 지급/소비가 안 끝난 구매 목록
 * InyeonNative.openUrl(url): 크롬 커스텀 탭 (카카오·구글·애플 로그인)
 */
public class Bridge implements PurchasesUpdatedListener {

    private final MainActivity act;
    private final BillingClient billing;
    private int pendingBuyId = -1;

    Bridge(MainActivity act) {
        this.act = act;
        billing = BillingClient.newBuilder(act)
                .setListener(this)
                .enablePendingPurchases(PendingPurchasesParams.newBuilder().enableOneTimeProducts().build())
                .enableAutoServiceReconnection()
                .build();
    }

    // ---------------- JS 에서 부르는 함수 ----------------

    @JavascriptInterface
    public String version() { return BuildConfig.VERSION_NAME + " (" + BuildConfig.VERSION_CODE + ")"; }

    @JavascriptInterface
    public String platform() { return "android"; }

    @JavascriptInterface
    public void openUrl(String url) {
        act.runOnUiThread(() -> {
            try {
                CustomTabsIntent tab = new CustomTabsIntent.Builder()
                        .setDefaultColorSchemeParams(new CustomTabColorSchemeParams.Builder().setToolbarColor(0xFF1C0609).build())
                        .setShowTitle(true)
                        .build();
                tab.launchUrl(act, Uri.parse(url));
            } catch (Exception e) {
                act.openExternal(Uri.parse(url));
            }
        });
    }

    @JavascriptInterface
    public void call(String method, int id, String json) {
        JSONObject a;
        try { a = new JSONObject(json == null ? "{}" : json); } catch (Exception e) { a = new JSONObject(); }
        final JSONObject args = a;
        act.runOnUiThread(() -> {
            switch (method) {
                case "buy": buy(id, args.optString("productId"), args.optString("accountId")); break;
                case "consume": consume(id, args.optString("purchaseToken")); break;
                case "unfinished": unfinished(id); break;
                default: fail(id, "unknown", "알 수 없는 요청: " + method);
            }
        });
    }

    // ---------------- 결과 돌려주기 ----------------

    private void ok(int id, Object payload) { act.resolveJs(id, true, payload.toString()); }

    private void fail(int id, String code, String message) {
        JSONObject o = new JSONObject();
        try { o.put("code", code); o.put("message", message); } catch (Exception ignored) { }
        act.resolveJs(id, false, o.toString());
    }

    // ---------------- 구글플레이 결제 ----------------

    private void whenReady(int id, Runnable task) {
        if (billing.isReady()) { task.run(); return; }
        billing.startConnection(new BillingClientStateListener() {
            @Override
            public void onBillingSetupFinished(@NonNull BillingResult r) {
                if (r.getResponseCode() == BillingClient.BillingResponseCode.OK) act.runOnUiThread(task);
                else fail(id, "billing_unavailable", "구글플레이 결제에 연결하지 못했어요 (" + r.getResponseCode() + ")");
            }

            @Override
            public void onBillingServiceDisconnected() { }
        });
    }

    private void buy(int id, String productId, String accountId) {
        if (pendingBuyId != -1) { fail(id, "busy", "이미 결제가 진행 중이에요"); return; }
        whenReady(id, () -> {
            QueryProductDetailsParams params = QueryProductDetailsParams.newBuilder()
                    .setProductList(Collections.singletonList(QueryProductDetailsParams.Product.newBuilder()
                            .setProductId(productId)
                            .setProductType(BillingClient.ProductType.INAPP)
                            .build()))
                    .build();
            billing.queryProductDetailsAsync(params, (r, result) -> {
                List<ProductDetails> list = result.getProductDetailsList();
                if (r.getResponseCode() != BillingClient.BillingResponseCode.OK || list == null || list.isEmpty()) {
                    fail(id, "no_product", "상품을 찾지 못했어요 (" + productId + ")");
                    return;
                }
                BillingFlowParams.Builder flow = BillingFlowParams.newBuilder()
                        .setProductDetailsParamsList(Collections.singletonList(
                                BillingFlowParams.ProductDetailsParams.newBuilder().setProductDetails(list.get(0)).build()));
                // 구매를 이 계정에 묶어 둠 → 서버가 다른 사람 영수증을 가로채 쓰는 것을 막음
                if (accountId != null && !accountId.isEmpty()) flow.setObfuscatedAccountId(accountId);
                act.runOnUiThread(() -> {
                    pendingBuyId = id;
                    BillingResult launch = billing.launchBillingFlow(act, flow.build());
                    if (launch.getResponseCode() != BillingClient.BillingResponseCode.OK) {
                        pendingBuyId = -1;
                        failFromResult(id, launch);
                    }
                });
            });
        });
    }

    @Override
    public void onPurchasesUpdated(@NonNull BillingResult r, List<Purchase> purchases) {
        int id = pendingBuyId;
        pendingBuyId = -1;
        if (id == -1) return;   // 앱 밖에서 생긴 구매는 다음에 들어올 때 unfinished 로 처리
        if (r.getResponseCode() == BillingClient.BillingResponseCode.OK && purchases != null && !purchases.isEmpty()) {
            Purchase p = purchases.get(0);
            if (p.getPurchaseState() == Purchase.PurchaseState.PURCHASED) ok(id, purchaseJson(p));
            else fail(id, "pending", "결제가 아직 승인 대기 중이에요. 승인되면 다음에 들어올 때 자동으로 채워져요.");
        } else {
            failFromResult(id, r);
        }
    }

    private void failFromResult(int id, BillingResult r) {
        switch (r.getResponseCode()) {
            case BillingClient.BillingResponseCode.USER_CANCELED: fail(id, "canceled", "결제를 취소했어요"); break;
            case BillingClient.BillingResponseCode.ITEM_ALREADY_OWNED: fail(id, "owned", "이전 결제를 마무리하는 중이에요. 잠시 뒤 다시 들어와 주세요."); break;
            default: fail(id, "billing_error", "결제에 실패했어요 (" + r.getResponseCode() + ") " + r.getDebugMessage());
        }
    }

    private JSONObject purchaseJson(Purchase p) {
        JSONObject o = new JSONObject();
        try {
            o.put("productId", p.getProducts().isEmpty() ? "" : p.getProducts().get(0));
            o.put("purchaseToken", p.getPurchaseToken());
            o.put("orderId", p.getOrderId() == null ? "" : p.getOrderId());
        } catch (Exception ignored) { }
        return o;
    }

    private void consume(int id, String token) {
        whenReady(id, () -> billing.consumeAsync(ConsumeParams.newBuilder().setPurchaseToken(token).build(), (r, t) -> {
            if (r.getResponseCode() == BillingClient.BillingResponseCode.OK) ok(id, new JSONObject());
            else fail(id, "consume_failed", "소비 처리 실패 (" + r.getResponseCode() + ")");
        }));
    }

    private void unfinished(int id) {
        whenReady(id, () -> billing.queryPurchasesAsync(
                QueryPurchasesParams.newBuilder().setProductType(BillingClient.ProductType.INAPP).build(),
                (r, list) -> {
                    // 소비형 상품: 아직 소비 안 된 '결제 완료' 구매 = 지급이 덜 끝난 것
                    JSONArray arr = new JSONArray();
                    if (list != null) for (Purchase p : list) {
                        if (p.getPurchaseState() == Purchase.PurchaseState.PURCHASED) arr.put(purchaseJson(p));
                    }
                    ok(id, arr);
                }));
    }

    void destroy() {
        try { billing.endConnection(); } catch (Exception ignored) { }
    }
}
