# scraper.py
import json, re, time, csv, webbrowser
from pathlib import Path
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

JST = timezone(timedelta(hours=9))

def parse_due(text: str):
    if not text: return None
    t = " ".join(text.strip().split())
    pats = [
        r"(\d{4})[\/\.-](\d{1,2})[\/\.-](\d{1,2})\s+(\d{1,2}):(\d{2})",
        r"(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})",
        r"(\d{1,2})[\/\.](\d{1,2})\s+(\d{1,2}):(\d{2})"
    ]
    for p in pats:
        m = re.search(p, t)
        if not m: continue
        g = m.groups()
        try:
            if len(g) == 5:
                Y, M, D, h, m2 = map(int, g)
            else:
                nowY = datetime.now(JST).year
                if "月" in p:
                    M, D, h, m2 = map(int, g)
                else:
                    M, D, h, m2 = map(int, g)
                Y = nowY
            return datetime(Y, M, D, h, m2, tzinfo=JST)
        except:
            pass
    return None

def pick(el):
    return " ".join(el.get_text(" ", strip=True).split()) if el else ""

def scrape_html(html: str, conf: dict, source: str):
    soup = BeautifulSoup(html, "lxml")
    out = []
    for card in soup.select(conf["item"]):
        title = pick(card.select_one(conf["title"]))
        if not title:
            continue
        course = pick(card.select_one(conf["course"])) or f"(科目不明/{source})"
        due_raw = pick(card.select_one(conf["due"]))
        due_dt = parse_due(due_raw)
        out.append({
            "source": source,
            "title": title,
            "course": course,
            "due_raw": due_raw,
            "due_iso": due_dt.isoformat() if due_dt else "",
            "due_ts": int(due_dt.timestamp()) if due_dt else 0
        })
    return out

def write_outputs(rows, outdir: Path):
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "assignments.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    with (outdir / "assignments.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["タイトル","科目","期限","ソース"])
        for r in rows:
            w.writerow([r["title"], r["course"], r["due_raw"], r["source"]])
    print("✅ assignments.json / csv を出力しました。")

def main():
    cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))
    target = cfg["targets"][0]

    CHROMEDRIVER_PATH = r"C:\Users\hatar\Downloads\chromedriver-win64\chromedriver-win64\chromedriver.exe"
    options = Options()
    options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
    service = Service(CHROMEDRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=options)

    print("🌐 Classroom にアクセス中...")
    driver.get(target["url"])

    WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, target["item"])))
    print("✅ ページを読み込みました。")

    html = driver.page_source
    Path("out/debug.html").write_text(html, encoding="utf-8")

    rows = scrape_html(html, target, target["name"])
    write_outputs(rows, Path("out"))
    driver.quit()

    # ブラウザで index.html を開く
    webbrowser.open(str(Path("index.html").resolve()))

if __name__ == "__main__":
    main()
