#!/usr/bin/env python3
"""구독이 '메타데이터 누락'일 때: 앱과 같은 모든 판매 국가로 넓히고, 한국 가격에 맞춘 각국 가격(애플 자동 환산)을 채운다."""
import os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from asc_products import call, all_pages, BUNDLE_ID, try_
aid = call("GET", f"/v1/apps?filter[bundleId]={BUNDLE_ID}")["data"][0]["id"]
terrs = [t["id"] for t in all_pages("/v1/territories?limit=200")]
print("국가 수", len(terrs))
for g in all_pages(f"/v1/apps/{aid}/subscriptionGroups?limit=10"):
    for s in all_pages(f"/v1/subscriptionGroups/{g['id']}/subscriptions?limit=50"):
        sid, pid = s["id"], s["attributes"]["productId"]
        try_(f"{pid} 판매 국가", lambda: call("POST", "/v1/subscriptionAvailabilities", {"data": {"type": "subscriptionAvailabilities",
            "attributes": {"availableInNewTerritories": True},
            "relationships": {"subscription": {"data": {"type": "subscriptions", "id": sid}},
                              "availableTerritories": {"data": [{"type": "territories", "id": t} for t in terrs]}}}}))
        have = set()
        for p in all_pages(f"/v1/subscriptions/{sid}/prices?include=territory&limit=200"):
            t = (p.get("relationships", {}).get("territory", {}) or {}).get("data")
            if t: have.add(t["id"])
        kor = all_pages(f"/v1/subscriptions/{sid}/prices?include=subscriptionPricePoint,territory&filter[territory]=KOR&limit=5")
        ppid = kor[0]["relationships"]["subscriptionPricePoint"]["data"]["id"]
        eq = all_pages(f"/v1/subscriptionPricePoints/{ppid}/equalizations?include=territory&limit=200")
        n = 0
        for e in eq:
            t = e["relationships"]["territory"]["data"]["id"]
            if t in have or t == "KOR": continue
            if try_(f"{pid} {t} 가격", lambda: call("POST", "/v1/subscriptionPrices", {"data": {"type": "subscriptionPrices",
                "attributes": {"startDate": None, "preserveCurrentPrice": False},
                "relationships": {"subscription": {"data": {"type": "subscriptions", "id": sid}},
                                  "subscriptionPricePoint": {"data": {"type": "subscriptionPricePoints", "id": e["id"]}},
                                  "territory": {"data": {"type": "territories", "id": t}}}}})): n += 1
        print(pid, "가격 추가", n, "기존", len(have))
time.sleep(5)
for g in all_pages(f"/v1/apps/{aid}/subscriptionGroups?limit=10"):
    for s in all_pages(f"/v1/subscriptionGroups/{g['id']}/subscriptions?limit=50"):
        print("상태", s["attributes"]["productId"], s["attributes"].get("state"))
