#!/usr/bin/env python3
"""인연큐레이터 App Store 상품을 App Store Connect API 로 등록한다 (이미 있는 상품은 건너뜀).
  - 구독 그룹 '인연 멤버십' + 1개월 자동갱신 구독 4개 (블랙 > 플래티넘 > 골드 > 실버)
  - 소모형 5개 (포인트 3종, 관람권 2종)
  - 한국어 이름·설명, 대한민국 가격, 판매 국가: 대한민국, 심사용 스크린샷
제품 ID 는 Google Play 와 같다 (서버 store_products 와 맞춤).
환경변수: KID, IID, KEYFILE (App Store Connect API 키), BUNDLE_ID"""
import hashlib, json, os, sys, time, urllib.request, urllib.error
import jwt  # PyJWT

API = "https://api.appstoreconnect.apple.com"
KID, IID, KEYFILE = os.environ["KID"], os.environ["IID"], os.environ["KEYFILE"]
BUNDLE_ID = os.environ.get("BUNDLE_ID", "com.inyeoncurator.app")
HERE = os.path.dirname(__file__)
SHOT_SUB, SHOT_IAP = os.path.join(HERE, "review-sub.png"), os.path.join(HERE, "review-shop.png")

GROUP = ("인연 멤버십", "인연큐레이터 멤버십")   # (참조 이름, 앱스토어 표시 이름)
# (제품 ID, 이름 ≤30자, 설명 ≤45자, 가격 원, 그룹 레벨 1=최상위)
SUBS = [
    ("inyeon.sub.black", "블랙 멤버십", "대화·꽃 무제한, 대기 우선, 몰래 관람", 59000, 1),
    ("inyeon.sub.platinum", "플래티넘 멤버십", "대화 신청·꽃 무제한, 꽃 보낸 사람 보기", 39000, 2),
    ("inyeon.sub.gold", "골드 멤버십", "대화 하루 5회, 꽃 20송이, 꽃 보낸 사람 보기", 19900, 3),
    ("inyeon.sub.silver", "실버 멤버십", "대화 신청 하루 3회, 꽃 하루 10송이", 9900, 4),
]
# (제품 ID, 이름, 설명, 가격 원)  모두 소모형
IAPS = [
    ("inyeon.point.300", "300 포인트", "대화 신청에 쓰는 포인트 300P", 3300),
    ("inyeon.point.1000", "1,100 포인트", "포인트 1,000P + 보너스 100P", 9900),
    ("inyeon.point.3300", "3,800 포인트", "포인트 3,300P + 보너스 500P", 29000),
    ("inyeon.ticket.5", "관람권 5장", "프로필 상세 보기에 쓰는 관람권 5장", 3300),
    ("inyeon.ticket.20", "관람권 20장", "프로필 상세 보기에 쓰는 관람권 20장", 9900),
]
REVIEW_NOTE = ("하단 '지갑' 탭에서 로그인한 회원만 살 수 있습니다. 멤버십은 1개월 자동 갱신 구독이며, "
               "포인트·관람권은 쓸 때마다 줄어드는 소모형입니다. 지갑 아래 '구매 복원'으로 구독을 되찾을 수 있습니다.")

def token():
    now = int(time.time())
    return jwt.encode({"iss": IID, "iat": now, "exp": now + 1000, "aud": "appstoreconnect-v1"},
                      open(KEYFILE).read(), algorithm="ES256", headers={"kid": KID, "typ": "JWT"})

def call(method, path, body=None, ok404=False):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + token(), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        msg = e.read().decode()[:800]
        if ok404 and e.code == 404: return None
        print(f"::error::App Store Connect {method} {path} → {e.code} {msg}")
        raise

def all_pages(path):
    out, nxt = [], path
    while nxt:
        j = call("GET", nxt)
        out += j.get("data", [])
        nxt = (j.get("links") or {}).get("next")
        if nxt: nxt = nxt.replace(API, "")
    return out

def pick(points, won):
    pts = [(float(p["attributes"]["customerPrice"]), p["id"]) for p in points]
    exact = [p for p in pts if p[0] == won]
    if exact: return exact[0][1], won
    up = sorted(p for p in pts if p[0] >= won) or sorted(pts, reverse=True)
    print(f"::warning::₩{won} 가격대가 없어 ₩{int(up[0][0])} 로 정함")
    return up[0][1], int(up[0][0])

def upload(kind, rel, rel_type, obj_id, path):
    data = open(path, "rb").read()
    r = call("POST", f"/v1/{kind}", {"data": {"type": kind,
        "attributes": {"fileName": os.path.basename(path), "fileSize": len(data)},
        "relationships": {rel: {"data": {"type": rel_type, "id": obj_id}}}}})["data"]
    for op in r["attributes"]["uploadOperations"]:
        chunk = data[op["offset"]: op["offset"] + op["length"]]
        req = urllib.request.Request(op["url"], method=op["method"], data=chunk,
                                     headers={h["name"]: h["value"] for h in op.get("requestHeaders", [])})
        urllib.request.urlopen(req).read()
    call("PATCH", f"/v1/{kind}/{r['id']}", {"data": {"type": kind, "id": r["id"],
        "attributes": {"uploaded": True, "sourceFileChecksum": hashlib.md5(data).hexdigest()}}})

def try_(label, fn):
    try: fn(); return True
    except Exception: print(f"::warning::{label} 실패 — App Store Connect 에서 확인해 주세요"); return False

def do_subs(app_id, report):
    groups = all_pages(f"/v1/apps/{app_id}/subscriptionGroups?limit=50")
    g = next((x for x in groups if x["attributes"]["referenceName"] == GROUP[0]), None)
    if g: gid = g["id"]
    else:
        gid = call("POST", "/v1/subscriptionGroups", {"data": {"type": "subscriptionGroups",
            "attributes": {"referenceName": GROUP[0]},
            "relationships": {"app": {"data": {"type": "apps", "id": app_id}}}}})["data"]["id"]
        try_("구독 그룹 한국어 이름", lambda: call("POST", "/v1/subscriptionGroupLocalizations", {"data": {
            "type": "subscriptionGroupLocalizations", "attributes": {"locale": "ko", "name": GROUP[1]},
            "relationships": {"subscriptionGroup": {"data": {"type": "subscriptionGroups", "id": gid}}}}}))
        report.append(f"구독 그룹 만듦  {GROUP[0]}")
    have = {s["attributes"]["productId"]: s["id"] for s in all_pages(f"/v1/subscriptionGroups/{gid}/subscriptions?limit=50")}
    for pid, name, desc, won, level in SUBS:
        if pid in have: report.append(f"건너뜀  {pid}"); continue
        sid = call("POST", "/v1/subscriptions", {"data": {"type": "subscriptions",
            "attributes": {"name": name, "productId": pid, "subscriptionPeriod": "ONE_MONTH", "groupLevel": level,
                           "familySharable": False, "reviewNote": REVIEW_NOTE},
            "relationships": {"group": {"data": {"type": "subscriptionGroups", "id": gid}}}}})["data"]["id"]
        try_(f"{pid} 한국어 이름", lambda: call("POST", "/v1/subscriptionLocalizations", {"data": {
            "type": "subscriptionLocalizations", "attributes": {"locale": "ko", "name": name[:30], "description": desc[:45]},
            "relationships": {"subscription": {"data": {"type": "subscriptions", "id": sid}}}}}))
        pp, real = pick(all_pages(f"/v1/subscriptions/{sid}/pricePoints?filter[territory]=KOR&limit=200"), won)
        try_(f"{pid} 가격", lambda: call("POST", "/v1/subscriptionPrices", {"data": {"type": "subscriptionPrices",
            "attributes": {"startDate": None, "preserveCurrentPrice": False},
            "relationships": {"subscription": {"data": {"type": "subscriptions", "id": sid}},
                              "subscriptionPricePoint": {"data": {"type": "subscriptionPricePoints", "id": pp}},
                              "territory": {"data": {"type": "territories", "id": "KOR"}}}}}))
        try_(f"{pid} 판매 국가", lambda: call("POST", "/v1/subscriptionAvailabilities", {"data": {"type": "subscriptionAvailabilities",
            "attributes": {"availableInNewTerritories": False},
            "relationships": {"subscription": {"data": {"type": "subscriptions", "id": sid}},
                              "availableTerritories": {"data": [{"type": "territories", "id": "KOR"}]}}}}))
        try_(f"{pid} 심사용 스크린샷", lambda: upload("subscriptionAppStoreReviewScreenshots", "subscription", "subscriptions", sid, SHOT_SUB))
        report.append(f"등록  {pid}  {name}  월 ₩{real}  레벨 {level}")
        time.sleep(0.5)
    time.sleep(3)
    for s in all_pages(f"/v1/subscriptionGroups/{gid}/subscriptions?limit=50"):
        report.append(f"상태  {s['attributes']['productId']}  {s['attributes'].get('state')}")

def do_iaps(app_id, report):
    have = {i["attributes"]["productId"]: i["id"] for i in all_pages(f"/v1/apps/{app_id}/inAppPurchasesV2?limit=200")}
    for pid, name, desc, won in IAPS:
        if pid in have: report.append(f"건너뜀  {pid}"); continue
        iid = call("POST", "/v2/inAppPurchases", {"data": {"type": "inAppPurchases",
            "attributes": {"name": f"{name} ({pid})"[:64], "productId": pid, "inAppPurchaseType": "CONSUMABLE",
                           "reviewNote": REVIEW_NOTE, "familySharable": False},
            "relationships": {"app": {"data": {"type": "apps", "id": app_id}}}}})["data"]["id"]
        try_(f"{pid} 한국어 이름", lambda: call("POST", "/v1/inAppPurchaseLocalizations", {"data": {"type": "inAppPurchaseLocalizations",
            "attributes": {"locale": "ko", "name": name[:30], "description": desc[:45]},
            "relationships": {"inAppPurchaseV2": {"data": {"type": "inAppPurchases", "id": iid}}}}}))
        pp, real = pick(all_pages(f"/v2/inAppPurchases/{iid}/pricePoints?filter[territory]=KOR&limit=200"), won)
        try_(f"{pid} 가격", lambda: call("POST", "/v1/inAppPurchasePriceSchedules", {"data": {"type": "inAppPurchasePriceSchedules",
            "relationships": {"inAppPurchase": {"data": {"type": "inAppPurchases", "id": iid}},
                              "baseTerritory": {"data": {"type": "territories", "id": "KOR"}},
                              "manualPrices": {"data": [{"type": "inAppPurchasePrices", "id": "${p1}"}]}}},
            "included": [{"type": "inAppPurchasePrices", "id": "${p1}", "attributes": {"startDate": None},
                          "relationships": {"inAppPurchasePricePoint": {"data": {"type": "inAppPurchasePricePoints", "id": pp}}}}]}))
        try_(f"{pid} 판매 국가", lambda: call("POST", "/v1/inAppPurchaseAvailabilities", {"data": {"type": "inAppPurchaseAvailabilities",
            "attributes": {"availableInNewTerritories": False},
            "relationships": {"inAppPurchase": {"data": {"type": "inAppPurchases", "id": iid}},
                              "availableTerritories": {"data": [{"type": "territories", "id": "KOR"}]}}}}))
        try_(f"{pid} 심사용 스크린샷", lambda: upload("inAppPurchaseAppStoreReviewScreenshots", "inAppPurchaseV2", "inAppPurchases", iid, SHOT_IAP))
        report.append(f"등록  {pid}  {name}  ₩{real}  소모형")
        time.sleep(0.5)
    time.sleep(3)
    for i in all_pages(f"/v1/apps/{app_id}/inAppPurchasesV2?limit=200"):
        report.append(f"상태  {i['attributes']['productId']}  {i['attributes'].get('state')}")

def main():
    apps = call("GET", f"/v1/apps?filter[bundleId]={BUNDLE_ID}")["data"]
    if not apps:
        print(f"::error::App Store Connect 에 번들 ID {BUNDLE_ID} 앱이 없어요."); sys.exit(1)
    app_id = apps[0]["id"]
    report = []
    do_subs(app_id, report)
    do_iaps(app_id, report)
    print("\n".join(report))
    s = os.environ.get("GITHUB_STEP_SUMMARY")
    if s: open(s, "a").write("### 인앱 상품\n```\n" + "\n".join(report) + "\n```\n")

if __name__ == "__main__":
    main()
