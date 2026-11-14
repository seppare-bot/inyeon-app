import UIKit
import UserNotifications

/// 푸시 알림 (APNs). 웹이 InyeonNative.call('pushToken') 하면 권한을 묻고 기기 토큰을 돌려준다.
/// 서버(send-push)가 이 토큰으로 애플에 직접 보낸다.
@MainActor
final class Push: NSObject, UNUserNotificationCenterDelegate {
    static let shared = Push()
    private var waiters: [CheckedContinuation<String, Error>] = []
    private(set) var token: String?
    /// 알림을 눌러 앱이 열렸을 때 웹에 넘길 내용 (kind, ref)
    var onOpen: ((String, String) -> Void)?
    var pendingOpen: (String, String)?

    func start() { UNUserNotificationCenter.current().delegate = self }

    func requestToken() async throws -> [String: Any] {
        let granted = (try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])) ?? false
        let t: String
        if let have = token { t = have } else {
            t = try await withCheckedThrowingContinuation { c in
                waiters.append(c)
                UIApplication.shared.registerForRemoteNotifications()
            }
        }
        return ["token": t, "platform": "ios", "enabled": granted]
    }

    func didRegister(_ deviceToken: Data) {
        let t = deviceToken.map { String(format: "%02x", $0) }.joined()
        token = t
        let w = waiters; waiters = []
        w.forEach { $0.resume(returning: t) }
    }

    func didFail(_ error: Error) {
        let w = waiters; waiters = []
        w.forEach { $0.resume(throwing: error) }
    }

    // 앱을 보고 있을 때는 웹 화면이 배너를 띄우므로 시스템 알림은 숨김
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                            withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([])
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                            withCompletionHandler completionHandler: @escaping () -> Void) {
        let info = response.notification.request.content.userInfo
        let kind = info["kind"] as? String ?? ""
        let ref = info["ref"] as? String ?? ""
        Task { @MainActor in
            if let f = Push.shared.onOpen { f(kind, ref) } else { Push.shared.pendingOpen = (kind, ref) }
            completionHandler()
        }
    }
}
