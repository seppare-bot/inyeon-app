#!/usr/bin/env python3
"""App Store 상품이 앱에서 안 보일 때 점검: 앱 판매 국가, 상품별 상태·판매 국가·가격·현지화, 최근 빌드"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from asc_products import call, all_pages, BUNDLE_ID
app = call("GET", f"/v1/apps?filter[bundleId]={BUNDLE_ID}")["data"][0]; aid = app["id"]
print("앱", aid, app["attributes"].get("name"), app["attributes"].get("primaryLocale"))
av = call("GET", f"/v1/apps/{aid}/appAvailabilityV2", ok404=True)
if av:
    terr = all_pages(f"/v2/appAvailabilities/{av['data']['id']}/territoryAvailabilities?limit=200")
    on = [t for t in terr if t["attributes"].get("available")]
    print("앱 판매 국가:", len(on), "/", len(terr), "KOR:", [t["attributes"] for t in terr if t["id"].endswith("KOR") or "KOR" in str(t.get("relationships",""))][:1])
else: print("앱 판매 국가: 설정 없음")
for b in call("GET", f"/v1/builds?filter[app]={aid}&sort=-uploadedDate&limit=3")["data"]:
    print("빌드", b["attributes"]["version"], b["attributes"]["processingState"], b["attributes"].get("uploadedDate"))
for g in all_pages(f"/v1/apps/{aid}/subscriptionGroups?limit=10"):
    print("그룹", g["attributes"], [(l["attributes"]["locale"], l["attributes"].get("state"), l["attributes"].get("name"), l["attributes"].get("customAppName")) for l in all_pages(f"/v1/subscriptionGroups/{g['id']}/subscriptionGroupLocalizations")])
    for s in all_pages(f"/v1/subscriptionGroups/{g['id']}/subscriptions?limit=50"):
        sid = s["id"]; a = s["attributes"]
        loc = [l["attributes"]["locale"] for l in all_pages(f"/v1/subscriptions/{sid}/subscriptionLocalizations")]
        pr = all_pages(f"/v1/subscriptions/{sid}/prices?include=territory&limit=5")
        avs = call("GET", f"/v1/subscriptions/{sid}/subscriptionAvailability?include=availableTerritories", ok404=True)
        ters = [t["id"] for t in (avs or {}).get("included", [])] if avs else None
        L = all_pages(f"/v1/subscriptions/{sid}/subscriptionLocalizations")
        shot = call("GET", f"/v1/subscriptions/{sid}/appStoreReviewScreenshot", ok404=True)
        print("  현지화상태", [(l["attributes"]["locale"], l["attributes"].get("state"), l["attributes"].get("name"), l["attributes"].get("description")) for l in L])
        print("  스크린샷", shot and shot.get("data") and shot["data"]["attributes"].get("assetDeliveryState"))
        print("  속성", {k: a.get(k) for k in ("name","subscriptionPeriod","reviewNote","groupLevel","familySharable")})
        print("구독", a["productId"], a.get("state"), "현지화", loc, "가격수", len(pr), "판매국가", ters)
for i in all_pages(f"/v1/apps/{aid}/inAppPurchasesV2?limit=50"):
    print("상품", i["attributes"]["productId"], i["attributes"].get("state"))
