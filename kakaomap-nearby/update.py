#!/usr/bin/env python3
"""카카오맵 공유 폴더에서 장소를 받아 index.html을 다시 만듭니다.

사용법:  pip install pyproj  &&  python3 update.py
- folders.txt 의 공유 링크를 읽어 장소 목록을 내려받습니다 (비공식 웹 API 사용).
- 좌표가 없는 장소는 카카오 내부 좌표(WCONGNAMUL)를 위경도로 변환합니다.
- 결과: data/places.json, index.html (artifact 용 본문은 dist/artifact.html)
"""
import csv, json, re, sys, time, datetime, urllib.request, urllib.parse
from pathlib import Path
from pyproj import Transformer

ROOT = Path(__file__).parent
UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://map.kakao.com/"}
# WCONGNAMUL = Korea TM(중부원점, GRS80) * 2.5
TM = Transformer.from_crs("+proj=tmerc +lat_0=38 +lon_0=127 +k=1 +x_0=200000 +y_0=500000 "
                          "+ellps=GRS80 +units=m +no_defs", "EPSG:4326", always_xy=True)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None

def get(url, tries=4):
    for n in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return r.read()
        except Exception as e:
            if n == tries - 1: raise
            time.sleep(2 ** (n + 1))

def resolve_share(link):
    if "folderid" in link:
        s = urllib.parse.unquote(link)
    else:
        op = urllib.request.build_opener(NoRedirect)
        try:
            op.open(urllib.request.Request(link, headers=UA), timeout=30); return None
        except urllib.error.HTTPError as e:
            if e.code not in (301, 302): return None
            s = urllib.parse.unquote(e.headers["Location"])
    m = re.search(r"folderid=(\d+).*?share_code=([\w-]+)", s)
    return m and (m.group(1), m.group(2))

def main():
    links = [l.strip() for l in (ROOT / "folders.txt").read_text().splitlines() if l.strip() and not l.startswith("#")]
    folders, places = [], []
    for link in links:
        r = resolve_share(link)
        if not r: print("건너뜀 (열리지 않는 링크):", link, file=sys.stderr); continue
        fid, code = r
        info = json.loads(get(f"https://map.kakao.com/folder/info?folderId={fid}&share_code={code}"))["folders"][0]
        favs = json.loads(get(f"https://map.kakao.com/favorite/list?share_code={code}&folderid={fid}")).get("favorites", [])
        idx = len(folders); folders.append({"name": info["title"], "count": len(favs)})
        for x in favs:
            lat, lon = x.get("lat"), x.get("lon")
            if lat is None:
                lon, lat = TM.transform(x["x"] / 2.5, x["y"] / 2.5)
            places.append([x["display1"], x.get("display2", ""), x.get("memo", ""), idx,
                           x.get("key", ""), round(lat, 7), round(lon, 7), 1 if x["type"] == "ADDRESS" else 0])
        print(f"{info['title']}: {len(favs)}곳")
    data = {"updated": datetime.date.today().isoformat(), "folders": folders, "places": places}
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data/places.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    build(data)
    print("별점·리뷰 수를 갱신하려면: python3 reviews.py && python3 update.py --build-only")

def build(data=None):
    data = data or json.loads((ROOT / "data/places.json").read_text())
    gaz = (ROOT / "data/gazetteer.json").read_text()
    rev_path = ROOT / "data/reviews.json"
    if rev_path.exists():
        rev = json.loads(rev_path.read_text())
        # 카카오맵에 정보가 없는(폐업·삭제) 장소는 빼고, 목록을 data/removed.csv 로 남김
        gone = [p for p in data["places"] if p[4] in rev and rev[p[4]] is None]
        keep = [p[:8] + (rev.get(p[4]) or []) for p in data["places"] if not (p[4] in rev and rev[p[4]] is None)]
        folders = [{**f, "count": sum(1 for p in keep if p[3] == i)} for i, f in enumerate(data["folders"])]
        data = {**data, "folders": folders, "places": keep}
        with open(ROOT / "data/removed.csv", "w", newline="", encoding="utf-8-sig") as fp:
            w = csv.writer(fp); w.writerow(["폴더", "이름", "주소", "메모", "카카오 장소 ID"])
            for p in gone: w.writerow([folders[p[3]]["name"], p[0], p[1], p[2], p[4]])
        print("카카오맵에 정보 없는 장소", len(gone), "곳 제외 → data/removed.csv")
    leaflet_css = (ROOT / "vendor/leaflet.css").read_text()
    body = (ROOT / "template.html").read_text()
    body = body.replace("__PLACES__", json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
    body = body.replace("__LEAFLET_CSS__", leaflet_css)
    body = body.replace("__GAZ__", gaz.replace("</", "<\\/"))
    (ROOT / "dist").mkdir(exist_ok=True)
    (ROOT / "dist/artifact.html").write_text(body)
    (ROOT / "index.html").write_text('<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
        '<style>body{margin:0}[hidden]{display:none!important}</style></head><body>\n' + body + '\n</body></html>\n')
    print("총", len(data["places"]), "곳 → index.html")

if __name__ == "__main__":
    build() if "--build-only" in sys.argv else main()
