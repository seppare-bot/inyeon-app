# 인연큐레이터 iOS 앱

- 안드로이드 앱과 같은 구조: https://inyeoncurator.com 을 WKWebView 로 열고, 앱은 결제·로그인 복귀만 맡음
- `window.InyeonNative` (platform() = 'ios'): buy / consume(finish) / unfinished / entitlements(구매 복원), openUrl(로그인 → ASWebAuthenticationSession)
- `.github/workflows/ios.yml`: Mac 없이 GitHub macOS 서버에서 XcodeGen → 시뮬레이터 실행·캡처(ci-shots-ios 브랜치) → (Secrets 있으면) 서명 → TestFlight

## GitHub Secrets (부캉이·성모의 뜰과 같은 값)
| 이름 | 내용 |
|---|---|
| ASC_ISSUER_ID | App Store Connect API 발급자 ID |
| ASC_KEY_ID | App Store Connect API 키 ID |
| ASC_KEY_P8 | 그 키의 .p8 파일 내용 전체 |
