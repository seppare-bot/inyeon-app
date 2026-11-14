import StoreKit
import UIKit

struct StoreError: Error { let code: String; let message: String }

/// App Store 결제 (StoreKit 2).
/// 지급은 서버(verify-purchase)가 Apple 에 거래를 확인한 뒤에만 하고, 지급이 끝나면 웹이 consume(거래번호)를 불러 finish 한다.
/// 결제할 때 appAccountToken 에 회원 id(UUID)를 넣어, 다른 사람의 거래로 지급받는 것을 서버가 막을 수 있게 한다.
@MainActor
final class Store {
    static let shared = Store()
    private var updates: Task<Void, Never>?

    /// 앱이 꺼져 있는 동안 승인된 결제(부모 승인 등)도 놓치지 않게 듣기만 한다 (finish 는 서버 지급 후 웹이 요청)
    func startListening() {
        updates = Task.detached { for await _ in Transaction.updates { } }
    }

    private func info(_ t: Transaction) -> [String: Any] {
        let id = String(t.id)
        return ["productId": t.productID, "transactionId": id, "purchaseToken": id, "originalTransactionId": String(t.originalID)]
    }

    func buy(_ productId: String, accountId: String) async throws -> [String: Any] {
        let products = try await Product.products(for: [productId])
        guard let product = products.first else { throw StoreError(code: "no_product", message: "상품을 찾지 못했어요 (\(productId))") }
        var options: Set<Product.PurchaseOption> = []
        if let uuid = UUID(uuidString: accountId) { options.insert(.appAccountToken(uuid)) }
        let result = try await product.purchase(options: options)
        switch result {
        case .success(let verification):
            switch verification {
            case .verified(let t): return info(t)
            case .unverified(_, let err): throw StoreError(code: "unverified", message: "결제 확인에 실패했어요 (\(err.localizedDescription))")
            }
        case .userCancelled: throw StoreError(code: "canceled", message: "결제를 취소했어요")
        case .pending: throw StoreError(code: "pending", message: "결제 승인을 기다리고 있어요. 승인되면 다음에 들어올 때 자동으로 채워져요.")
        @unknown default: throw StoreError(code: "error", message: "결제를 마치지 못했어요")
        }
    }

    /// 서버 지급이 끝난 거래를 마무리
    func finish(_ transactionId: String) async {
        for await v in Transaction.unfinished {
            if case .verified(let t) = v, String(t.id) == transactionId { await t.finish(); return }
        }
    }

    /// 결제는 됐는데 아직 지급·마무리가 안 된 거래
    func unfinished() async -> [[String: Any]] {
        var out: [[String: Any]] = []
        for await v in Transaction.unfinished {
            if case .verified(let t) = v, t.revocationDate == nil { out.append(info(t)) }
        }
        return out
    }

    /// App Store 구독 관리 화면 (해지·등급 변경)
    func manageSubscriptions() async {
        if let scene = UIApplication.shared.connectedScenes.first(where: { $0.activationState == .foregroundActive }) as? UIWindowScene {
            try? await AppStore.showManageSubscriptions(in: scene)
        } else if let u = URL(string: "https://apps.apple.com/account/subscriptions") {
            await UIApplication.shared.open(u)
        }
    }

    /// 구매 복원: App Store 와 동기화한 뒤, 지금 가지고 있는(환불 안 된) 아이템 목록
    func entitlements() async throws -> [[String: Any]] {
        try? await AppStore.sync()
        var out: [[String: Any]] = []
        for await v in Transaction.currentEntitlements {
            if case .verified(let t) = v, t.revocationDate == nil, t.productType == .nonConsumable || t.productType == .autoRenewable { out.append(info(t)) }
        }
        return out
    }
}
