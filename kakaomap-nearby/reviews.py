#!/usr/bin/env python3
"""저장한 장소마다 카카오맵 별점·리뷰 수를 받아 data/reviews.json 에 저장합니다.

사용법: python3 reviews.py [--refresh]
- 이미 받은 장소는 건너뜁니다 (--refresh 를 주면 전부 다시 받음).
- 카카오 비공식 API(place-api.map.kakao.com)를 쓰며, 동시 요청 수를 낮게 유지합니다.
"""
import json, sys, time, threading, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "data/reviews.json"
H = {"User-Agent": "Mozilla/5.0", "Referer": "https://place.map.kakao.com/", "pf": "web"}

def fetch(pid):
    for n in range(4):
        try:
            req = urllib.request.Request(f"https://place-api.map.kakao.com/places/panel3/{pid}", headers=H)
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.load(r)
            s = (d.get("kakaomap_review") or {}).get("score_set") or {}
            b = d.get("blog_review") or {}
            # [별점, 카카오 리뷰 수, 블로그 리뷰 수]
            return pid, [s.get("average_score") or 0, s.get("review_count") or 0, b.get("review_count") or 0]
        except urllib.error.HTTPError as e:
            if e.code == 404: return pid, None
            time.sleep(2 ** (n + 1))
        except Exception:
            time.sleep(2 ** (n + 1))
    return pid, "ERR"

def main():
    data = json.loads((ROOT / "data/places.json").read_text())
    ids = sorted({p[4] for p in data["places"] if p[4] and not p[7]})
    have = {} if "--refresh" in sys.argv or not OUT.exists() else json.loads(OUT.read_text())
    todo = [i for i in ids if i not in have]
    print(f"{len(ids)}곳 중 {len(todo)}곳 받는 중…", flush=True)
    lock, done = threading.Lock(), [0]
    def save():
        OUT.write_text(json.dumps(have, ensure_ascii=False, separators=(",", ":")))
    def job(pid):
        time.sleep(0.1)
        pid, v = fetch(pid)
        with lock:
            if v != "ERR": have[pid] = v
            done[0] += 1
            if done[0] % 200 == 0: save(); print(done[0], flush=True)
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(job, todo))
    save()
    print("완료:", len(have), "곳, 실패:", len(ids) - len(have))

if __name__ == "__main__":
    main()
