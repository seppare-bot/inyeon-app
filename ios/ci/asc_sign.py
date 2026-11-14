#!/usr/bin/env python3
"""(인연큐레이터) App Store Connect API 로 이번 빌드 전용 배포 인증서 + App Store 프로파일을 만들고(setup),
업로드가 끝나면 지운다(cleanup). 테스트 기기 없이 TestFlight 업로드를 하기 위한 것.
환경변수: KID, IID, KEYFILE, BUNDLE_ID, WORK(작업 폴더)"""
import base64, json, os, subprocess, sys, time, urllib.request, urllib.error
import jwt  # PyJWT

API = "https://api.appstoreconnect.apple.com/v1"
KID, IID, KEYFILE = os.environ["KID"], os.environ["IID"], os.environ["KEYFILE"]
BUNDLE_ID = os.environ.get("BUNDLE_ID", "com.inyeoncurator.app")
WORK = os.environ.get("WORK", os.path.expanduser("~/asc"))
os.makedirs(WORK, exist_ok=True)
STATE = os.path.join(WORK, "state.json")

def token():
    now = int(time.time())
    return jwt.encode({"iss": IID, "iat": now, "exp": now + 1000, "aud": "appstoreconnect-v1"},
                      open(KEYFILE).read(), algorithm="ES256", headers={"kid": KID, "typ": "JWT"})

def call(method, path, body=None):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + token(), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        print(f"::error::App Store Connect {method} {path} → {e.code} {e.read().decode()[:600]}")
        raise

def sh(*a): subprocess.run(a, check=True)

def setup():
    key, csr = os.path.join(WORK, "dist.key"), os.path.join(WORK, "dist.csr")
    sh("openssl", "req", "-new", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", csr,
       "-subj", "/CN=Inyeon CI/O=Uiltrade/C=KR")
    csr_txt = open(csr).read()
    # 이전 빌드가 쓴 인증서 정리: Apple 이 빌드를 처리하는 동안 인증서를 지우면 '유효하지 않은 바이너리'가 되므로
    # 업로드 직후가 아니라 '다음 빌드 때', 그리고 만든 지 45분 넘은 것만 지운다 (인증서 개수 제한(3개) 방지)
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    for c in call("GET", "/certificates?filter[certificateType]=DISTRIBUTION&limit=50").get("data", []):
        exp = c["attributes"].get("expirationDate")
        try:
            created = _dt.datetime.fromisoformat(exp.replace("Z", "+00:00")) - _dt.timedelta(days=365)
        except Exception:
            continue
        if now - created > _dt.timedelta(minutes=45):
            try: call("DELETE", f"/certificates/{c['id']}"); print("revoked old CI cert", c["id"])
            except Exception: pass
    cert = call("POST", "/certificates", {"data": {"type": "certificates", "attributes": {
        "certificateType": "DISTRIBUTION", "csrContent": csr_txt}}})["data"]
    cer = os.path.join(WORK, "dist.cer")
    open(cer, "wb").write(base64.b64decode(cert["attributes"]["certificateContent"]))
    # 임시 키체인에 키 + 인증서 넣기
    kc, pw = os.path.join(WORK, "ci.keychain-db"), "ci"
    sh("security", "create-keychain", "-p", pw, kc)
    sh("security", "set-keychain-settings", "-lut", "21600", kc)
    sh("security", "unlock-keychain", "-p", pw, kc)
    p12 = os.path.join(WORK, "dist.p12")
    pem = os.path.join(WORK, "dist.pem")
    sh("openssl", "x509", "-inform", "DER", "-in", cer, "-out", pem)
    # OpenSSL 3 는 -legacy 가 있어야 macOS security 가 읽을 수 있고, LibreSSL 은 -legacy 옵션이 없음
    if subprocess.run(["openssl", "pkcs12", "-export", "-legacy", "-inkey", key, "-in", pem, "-out", p12, "-passout", "pass:ci"]).returncode:
        sh("openssl", "pkcs12", "-export", "-inkey", key, "-in", pem, "-out", p12, "-passout", "pass:ci")
    sh("security", "import", p12, "-k", kc, "-P", "ci", "-T", "/usr/bin/codesign", "-T", "/usr/bin/security")
    sh("security", "set-key-partition-list", "-S", "apple-tool:,apple:,codesign:", "-s", "-k", pw, kc)
    existing = subprocess.run(["security", "list-keychains", "-d", "user"], capture_output=True, text=True).stdout.split()
    sh("security", "list-keychains", "-d", "user", "-s", kc, *[e.strip('"') for e in existing])
    # 번들 ID → App Store 프로파일
    bid = [b for b in call("GET", f"/bundleIds?filter[identifier]={BUNDLE_ID}")["data"] if b["attributes"]["identifier"] == BUNDLE_ID]
    if bid: bid = bid[0]["id"]
    else:  # 번들 ID 가 아직 없으면 등록 (App Store Connect 에서 앱을 만들 때 고를 수 있게)
        bid = call("POST", "/bundleIds", {"data": {"type": "bundleIds", "attributes": {
            "identifier": BUNDLE_ID, "name": os.environ.get("BUNDLE_NAME", "Inyeon"), "platform": "IOS"}}})["data"]["id"]
        print("registered bundle id", BUNDLE_ID)
    # 푸시 알림 기능이 꺼져 있으면 켬 (프로파일에 aps-environment 가 들어가야 푸시 가능)
    try:
        caps = call("GET", f"/bundleIds/{bid}/bundleIdCapabilities")["data"]
        if not any(c["attributes"].get("capabilityType") == "PUSH_NOTIFICATIONS" for c in caps):
            call("POST", "/bundleIdCapabilities", {"data": {"type": "bundleIdCapabilities",
                "attributes": {"capabilityType": "PUSH_NOTIFICATIONS"},
                "relationships": {"bundleId": {"data": {"type": "bundleIds", "id": bid}}}}})
            print("enabled PUSH_NOTIFICATIONS on", BUNDLE_ID)
    except Exception as e:
        print("::warning::푸시 기능 자동 설정 실패 (developer.apple.com 에서 직접 켜 주세요):", e)
    name = f"Inyeon CI {int(time.time())}"
    prof = call("POST", "/profiles", {"data": {"type": "profiles", "attributes": {"name": name, "profileType": "IOS_APP_STORE"},
        "relationships": {"bundleId": {"data": {"type": "bundleIds", "id": bid}},
                          "certificates": {"data": [{"type": "certificates", "id": cert["id"]}]}}}})["data"]
    pdir = os.path.expanduser("~/Library/MobileDevice/Provisioning Profiles")
    os.makedirs(pdir, exist_ok=True)
    uuid = prof["attributes"]["uuid"]
    open(os.path.join(pdir, uuid + ".mobileprovision"), "wb").write(base64.b64decode(prof["attributes"]["profileContent"]))
    json.dump({"cert": cert["id"], "profile": prof["id"], "name": name, "uuid": uuid, "keychain": kc}, open(STATE, "w"))
    gh = os.environ.get("GITHUB_ENV")
    if gh:
        with open(gh, "a") as f: f.write(f"PROFILE_NAME={name}\nPROFILE_UUID={uuid}\n")
    print("signing ready:", name)

def cleanup():
    if not os.path.exists(STATE): return
    s = json.load(open(STATE))
    # 인증서는 지우지 않음 (Apple 처리 중에 지우면 빌드가 무효가 됨) — 다음 빌드 때 정리
    try: call("DELETE", f"/profiles/{s['profile']}")
    except Exception: pass
    subprocess.run(["security", "delete-keychain", s["keychain"]])
    print("cleaned")

if __name__ == "__main__":
    {"setup": setup, "cleanup": cleanup}[sys.argv[1]]()
