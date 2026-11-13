# 인연큐레이터 · 안드로이드 / 아이폰 앱

https://inyeoncurator.com 을 앱 안에서 여는 프로젝트 (성모의 뜰 앱과 같은 구조). 웹(Netlify)을 고치면 앱을 다시 올리지 않아도 바로 반영돼요.

- 패키지 / 번들 ID: `com.inyeoncurator.app` (운영: 유일트레이드)
- 로그인: Supabase OAuth(카카오·Google·Apple) → 크롬 커스텀 탭 / iOS 시스템 로그인 창 → `com.inyeoncurator.app://auth` 로 복귀 → 웹이 PKCE 코드 교환
- 사진: 프로필 사진 올리기(웹의 파일 선택)를 앱의 사진 고르기 화면으로 연결
- 결제: Google Play Billing 8 / StoreKit 2 연결 코드만 들어 있음 (상품·영수증 검증은 다음 단계)
- 웹에서 앱인지 확인: `window.InyeonNative` (platform() = 'android' | 'ios')

## 빌드
`main` 에 push 하면 GitHub Actions 가 자동 빌드 → 저장소 **Releases** 에서 받기.
- `inyeon-1.0.N.aab` : Play Console 업로드용
- `inyeon-1.0.N-release.apk` : 휴대폰에 바로 설치해 보는 파일
- 아이폰: `ios/**` 를 바꾸면 TestFlight 로 자동 업로드 (Actions 탭에서 Run workflow 로도 가능)

## GitHub Secrets (Settings → Secrets and variables → Actions) — 부캉이·성모의 뜰과 같은 값
| 이름 | 내용 |
|---|---|
| KEYSTORE_BASE64 | 업로드 키(.jks) base64 |
| KEYSTORE_PASSWORD / KEY_PASSWORD | 키 비밀번호 |
| KEY_ALIAS | `upload` |
| ASC_ISSUER_ID / ASC_KEY_ID / ASC_KEY_P8 | App Store Connect API 키 |

## 앱을 다시 올려야 할 때
웹 화면 수정은 Netlify 배포만으로 충분해요. 결제·로그인 연결, 권한, 아이콘처럼 이 저장소의 파일을 바꿨을 때만 push → 새 AAB 업로드.
