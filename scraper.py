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
    outdir = Path("out"); outdir.mkdir(exist_ok=True)

    def log(msg):
        print(msg)
        with (outdir / "log.txt").open("a", encoding="utf-8") as f:
            f.write(msg + "\n")

    try:
        cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))
        CHROMEDRIVER_PATH = r"C:\Users\hatar\Downloads\chromedriver-win64\chromedriver-win64\chromedriver.exe"

        # 1) Driver起動
        opts = Options()
        opts.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
        driver = webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=opts)

        # 2) 2種類のURLを順に試す
        urls = [
            "https://classroom.google.com/u/0/a/assigned/all",
            "https://classroom.google.com/u/0/a/not-turned-in/all",
        ]

        def pick(el):
            return " ".join(el.get_text(" ", strip=True).split()) if el else ""

        rows_final = []
        for url in urls:
            log(f"🌐 アクセス: {url}")
            driver.get(url)

            # ページ待機（緩め）
            try:
                WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "body"))
                )
                log("✅ body検出")
            except Exception as e:
                log(f"⚠️ body待機失敗: {type(e).__name__}: {e}")

            # 展開クリック
            toggles = [
                "[aria-label*='展開']",
                "button[aria-label*='展開']",
                "div[role='button'][aria-label*='展開']",
                "[data-tooltip*='展開']",
            ]
            found = 0
            for sel in toggles:
                for b in driver.find_elements(By.CSS_SELECTOR, sel):
                    try:
                        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", b)
                        time.sleep(0.2); b.click(); time.sleep(0.2)
                        found += 1
                    except: pass
            log(f"🔽 展開クリック数: {found}")
            time.sleep(1.2)

            # HTML保存＆解析
            html = driver.page_source
            (outdir / "debug.html").write_text(html, encoding="utf-8")
            try:
                driver.save_screenshot(str(outdir / "screen.png"))
            except: pass

            soup = BeautifulSoup(html, "lxml")
            item_sel   = "div[role='listitem'], c-wiz[jsrenderer], .YVvGBb, .VfPpkd-card"
            title_sel  = "h3, h2, .TrZEUc, .YVvGBb, .VfPpkd-card__title"
            course_sel = ".Kk7lMc, .tUJKGd, .tdCJdf"
            due_sel    = "time, .IMvYId, .dR9lJ, .bFjUmb"

            rows = []
            cards = soup.select(item_sel)
            log(f"🔍 検出カード数: {len(cards)}")
            for c in cards:
                title = pick(c.select_one(title_sel))
                if not title: 
                    continue
                course = pick(c.select_one(course_sel)) or "(科目不明/classroom)"
                due    = pick(c.select_one(due_sel))
                rows.append({
                    "source": "classroom",
                    "title": title,
                    "course": course,
                    "due_raw": due,
                    "due_iso": "",
                    "due_ts": 0,
                })

            if rows:
                rows_final = rows
                log(f"✅ 取得成功: {len(rows)}件（このURLを採用）")
                break
            else:
                log("⚠️ 0件だったため次URLを試します…")

        write_outputs(rows_final, outdir)
        log(f"📦 最終件数: {len(rows_final)}  出力: assignments.json / csv")
        webbrowser.open(str(Path("index.html").resolve()))
        driver.quit()

    except Exception as e:
        err = f"💥 例外: {type(e).__name__}: {e}"
        print(err)
        with (Path("out") / "log.txt").open("a", encoding="utf-8") as f:
            f.write(err + "\n")
