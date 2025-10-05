# scraper.py
import json, re, time, csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

JST = timezone(timedelta(hours=9))

def parse_due(text: str):
    """日本語混じりの期限 → datetime(JST) に正規化"""
    if not text: return None
    t = " ".join(text.strip().split())
    pats = [
        r"(\d{4})[\/\.-](\d{1,2})[\/\.-](\d{1,2})\s+(\d{1,2}):(\d{2})",  # 2025/10/12 23:55
        r"(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})",                   # 10月12日 23:55（年なし→今年）
        r"(\d{1,2})[\/\.](\d{1,2})\s+(\d{1,2}):(\d{2})"                   # 10/12 23:55（年なし）
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
                    M, D, h, m2 = map(int, g)  # 10/12 23:55
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

def dedupe(rows):
    rows = sorted(rows, key=lambda r: (r["title"].lower(), r["due_ts"] or 0))
    merged = []
    for r in rows:
        if not merged: merged.append(r); continue
        p = merged[-1]
        same = r["title"].strip().lower() == p["title"].strip().lower()
        close = (r["due_ts"] and p["due_ts"] and abs(r["due_ts"]-p["due_ts"]) <= 86400)
        if same and (close or (not r["due_ts"] or not p["due_ts"])):
            if r["due_ts"] and not p["due_ts"]:
                p["due_ts"], p["due_iso"], p["due_raw"] = r["due_ts"], r["due_iso"], r["due_raw"]
            p["course"] = " / ".join(sorted(set([p["course"], r["course"]])))
            p["source"] = " / ".join(sorted(set(p["source"].split(" / ") + [r["source"]])))
        else:
            merged.append(r)
    return merged

def write_outputs(rows, outdir: Path):
    outdir.mkdir(parents=True, exist_ok=True)
    # CSV
    with (outdir / "assignments.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["title","course","due_iso(JST)","due_human","source"])
        for r in rows:
            w.writerow([r["title"], r["course"], r["due_iso"], r["due_raw"], r["source"]])
    # JSON
    (outdir / "assignments.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    # ICS
    lines = ["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//Portfolio//Assignments//JP"]
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    def i(dt: datetime): return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for i_idx, r in enumerate(rows, 1):
        if not r["due_ts"]: continue
        dt = datetime.fromtimestamp(r["due_ts"], tz=JST)
        summary = f"{r['title']}（{r['course']}）"
        uid = f"{i_idx}-{abs(hash(summary))}@local"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now}",
            f"DTSTART:{i(dt)}",
            f"DTEND:{i(dt+timedelta(minutes=30))}",
            f"SUMMARY:{summary}",
            f"DESCRIPTION:Source:{r['source']} Raw:{r['due_raw']}",
            "END:VEVENT"
        ]
    (outdir / "assignments.ics").write_text("\r\n".join(lines), encoding="utf-8")

def do_steps(driver, steps: list):
    """ログイン後の遷移（WebClassへ移動→課題タブ→一覧表示 など）"""
    wait = WebDriverWait(driver, 20)
    for st in steps or []:
        if "wait_css" in st:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, st["wait_css"])))
        if "click_css" in st:
            el = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, st["click_css"])))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            el.click()
        if "goto" in st:
            driver.get(st["goto"])
        if "iframe_css" in st:
            iframe = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, st["iframe_css"])))
            driver.switch_to.frame(iframe)

def main():
    cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))

    # === Chromeの設定 ===
    options = Options()
    options.add_argument("--start-maximized")

    # ★ 普段使っているChromeプロファイルを指定（これが自動ログインのポイント！）
    options.add_argument(r"--user-data-dir=C:\Users\hatar\AppData\Local\Google\Chrome\User Data")
    options.add_argument("--profile-directory=Default")  # "Profile 1" など使っているプロファイルに応じて変更

    # === ChromeDriverを自動セットアップ ===
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.maximize_window()

    all_rows = []
    try:
        # 1) タブを開く
        print("タブを開きます…")
        for t in cfg["targets"]:
            print("GET:", t["url"])
            driver.execute_script(f"window.open('{t['url']}', '_blank');")

        print("👉 各タブでログインしてください。完了したらここで Enter を押します。")
        input()

        # 3) それぞれのタブで遷移→解析
        for t in cfg["targets"]:
            domain = t["url"].split("/")[2]
            for h in driver.window_handles:
                driver.switch_to.window(h)
                if domain in driver.current_url:
                    try:
                        driver.switch_to.default_content()
                    except:
                        pass

                    do_steps(driver, t.get("steps"))
                    time.sleep(1.0)
                    html = driver.page_source
                    rows = scrape_html(html, t, t["name"])
                    all_rows += rows

                    try:
                        driver.switch_to.default_content()
                    except:
                        pass
                    break

        if not all_rows:
            print("⚠️ 課題が見つかりませんでした。config のセレクタ（item/title/course/due）を調整してください。")
            return

        rows = dedupe(all_rows)
        write_outputs(rows, Path("out"))
        print("✅ out/assignments.csv, assignments.json, assignments.ics を出力しました。")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
