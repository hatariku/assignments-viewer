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
    options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")  # 既に開いてるChromeへ接続
    service = Service(CHROMEDRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=options)

    # === 試すURLを2パターン ===
    urls = [
        "https://classroom.google.com/u/0/a/assigned/all",      # 割り当て済み
        "https://classroom.google.com/u/0/a/not-turned-in/all", # 未提出
    ]

    all_rows = []
    for url in urls:
        print(f"🌐 Classroom にアクセス中... ({url})")
        driver.get(url)

        try:
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "body"))
            )
            print("✅ ページの基本構造を検出。")
        except:
            print("⚠️ ページが完全に読み込まれませんでしたが続行します。")

        # === 「展開」ボタンをクリック ===
        print("🔽 展開ボタンをクリック中...")
        toggle_selectors = [
            "[aria-label*='展開']",
            "button[aria-label*='展開']",
            "div[role='button'][aria-label*='展開']",
            "[data-tooltip*='展開']"
        ]
        for sel in toggle_selectors:
            for b in driver.find_elements(By.CSS_SELECTOR, sel):
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", b)
                    time.sleep(0.3)
                    b.click()
                    print(f"　➡ 展開クリック: {sel}")
                    time.sleep(0.4)
                except Exception:
                    pass

        time.sleep(1.5)
        html = driver.page_source
        soup = BeautifulSoup(html, "lxml")

        # 広めのセレクタ
        item_sel = "div[role='listitem'], c-wiz[jsrenderer], .YVvGBb, .VfPpkd-card"
        title_sel = "h3, h2, .TrZEUc, .YVvGBb, .VfPpkd-card__title"
        course_sel = ".Kk7lMc, .tUJKGd, .tdCJdf"
        due_sel = "time, .IMvYId, .dR9lJ, .bFjUmb"

        def pick(el):
            return " ".join(el.get_text(" ", strip=True).split()) if el else ""

        rows = []
        for card in soup.select(item_sel):
            title = pick(card.select_one(title_sel))
            if not title:
                continue
            course = pick(card.select_one(course_sel)) or "(科目不明/classroom)"
            due = pick(card.select_one(due_sel))
            rows.append({
                "source": "classroom",
                "title": title,
                "course": course,
                "due_raw": due,
                "due_iso": "",
                "due_ts": 0
            })

        print(f"🔍 {len(rows)} 件の課題を検出。")
        if rows:
            all_rows = rows
            break  # どちらかで取得できたら終了

    # === 出力 ===
    Path("out").mkdir(exist_ok=True)
    Path("out/debug.html").write_text(driver.page_source, encoding="utf-8")
    write_outputs(all_rows, Path("out"))
    print(f"✅ 最終 {len(all_rows)} 件の課題を検出。assignments.json / csv を出力しました。")

    # ブラウザで index.html を開く
    webbrowser.open(str(Path("index.html").resolve()))

    driver.quit()
