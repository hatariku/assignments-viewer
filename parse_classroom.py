from bs4 import BeautifulSoup
from pathlib import Path
import csv

html_path = Path("out/debug.html")
html = html_path.read_text(encoding="utf-8")
soup = BeautifulSoup(html, "lxml")

assignments = []

for card in soup.select("div[jscontroller][jsaction]"):
    title = card.select_one(".TrZEUc, .YVvGBb, .VfPpkd-card__title")
    course = card.select_one(".Kk7lMc, .tUJKGd, .tdCJdf")
    due = card.select_one(".IMvYId, .dR9lJ, .bFjUmb")

    title_text = title.get_text(strip=True) if title else ""
    course_text = course.get_text(strip=True) if course else ""
    due_text = due.get_text(strip=True) if due else ""

    if title_text:
        assignments.append([title_text, course_text, due_text])

out_csv = Path("out/classroom_assignments.csv")
with out_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["タイトル", "科目", "期限"])
    writer.writerows(assignments)

print(f"✅ {len(assignments)} 件の課題を検出しました。結果を {out_csv} に保存しました。")
