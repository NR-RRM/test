#!/usr/bin/env python3
"""저장한 장소마다 최근 블로그 리뷰 10개를 열어 협찬 글이 몇 개인지 세어 data/sponsor.json 에 저장합니다.

사용법: python3 sponsor.py [--refresh]
- 페이지가 열릴 때마다 확인하면 너무 무거우므로, 여기서 한 번 미리 계산해 숫자만 페이지에 넣습니다.
- 판별 기준 (네이버 블로그 본문):
  1) 글 앞/끝부분의 공정위 표기 문구: 협찬, 체험단, 원고료, 제공받아, 지원받아, 업체로부터 …
  2) 체험단 플랫폼의 배너/링크 도메인: revu.net, reviewnote.co.kr, dinnerqueen.net …
- 결과 형식: {장소ID: [확인한 글 수, 협찬 글 수]}
"""
import json, re, sys, time, threading, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "data/sponsor.json"
KH = {"User-Agent": "Mozilla/5.0", "Referer": "https://place.map.kakao.com/", "pf": "web"}
NH = {"User-Agent": "Mozilla/5.0"}
TEXT = re.compile(r"(협찬|체험단|원고료|소정의\s*(수수료|금액|제품|서비스)|제공\s*받|지원\s*받|무상으로\s*제공|업체로부터|광고\s*포함|유료\s*광고|대가를\s*받|초대\s*받아|서포터즈)")
# 체험단 플랫폼 이름 (도메인 끝이 .co.kr/.net/.cloud 등 무엇이든 이름 부분만 비교)
SPONSOR_NAMES = {"revu", "reviewnote", "dinnerqueen", "mrblog", "4blog", "seoulouba", "reviewplace", "ringble",
                 "tble", "chvu", "modublog", "storyn", "weble", "popomon", "cometoplay", "assaview", "dinodan",
                 "reviewjin", "xn--939au0g4vj8sq", "ohmyblog", "blogdex", "realreview", "gangnam-mat"}
HOST = re.compile(r"https?://([^/\"'?#\s]+)")


def get(url, headers):
    for n in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
                return r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            if e.code in (403, 404): raise
            time.sleep(2 ** (n + 1))
        except Exception:
            if n == 2: raise
            time.sleep(2 ** (n + 1))


def is_sponsored(url):
    m = re.search(r"blog\.naver\.com/([^/?#]+)/(\d+)", url) or re.search(r"blogId=([^&]+)&logNo=(\d+)", url)
    if not m:
        return None  # 네이버 블로그가 아닌 글은 세지 않음
    s = get(f"https://m.blog.naver.com/PostView.naver?blogId={m[1]}&logNo={m[2]}", NH)
    i = s.find("se-main-container")
    body = s[i:] if i >= 0 else s
    j = body.find("post_footer")
    body = body[:j] if j > 0 else body
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))
    if TEXT.search(text[:600]) or TEXT.search(text[-1500:]):
        return True
    if "/gongjeong/" in body:  # 공정위 표기 배너 이미지 경로
        return True
    labels = {part for h in HOST.findall(body) for part in h.lower().split(".")}
    return bool(labels & SPONSOR_NAMES)


def check_place(pid):
    d = json.loads(get(f"https://place-api.map.kakao.com/places/tab/reviews/blog/{pid}?page=1", KH))
    seen = hit = 0
    for r in d.get("reviews", []):
        try:
            v = is_sponsored(r.get("origin_url", ""))
        except Exception:
            continue
        if v is None: continue
        seen += 1; hit += v
    return [seen, hit]


def main():
    reviews = json.loads((ROOT / "data/reviews.json").read_text())
    ids = sorted(k for k, v in reviews.items() if v and v[2] > 0)  # 블로그 리뷰가 있는 곳만
    have = {} if "--refresh" in sys.argv or not OUT.exists() else json.loads(OUT.read_text())
    todo = [i for i in ids if i not in have]
    print(f"{len(ids)}곳 중 {len(todo)}곳 확인 중…", flush=True)
    lock, done = threading.Lock(), [0]

    def save():
        OUT.write_text(json.dumps(have, separators=(",", ":")))

    def job(pid):
        try:
            v = check_place(pid)
        except Exception:
            return
        with lock:
            have[pid] = v; done[0] += 1
            if done[0] % 100 == 0: save(); print(done[0], flush=True)

    with ThreadPoolExecutor(6) as ex:
        list(ex.map(job, todo))
    save()
    print("완료:", len(have), "곳")


if __name__ == "__main__":
    main()
