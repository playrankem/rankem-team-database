import os
import re
import csv
import json
import time
import requests

# Output config
OUT_DIR = "new"
DYNAMO_FILE = "new_dynamodb.json"
CSV_FILE = "Teams.csv"

os.makedirs(OUT_DIR, exist_ok=True)

def sanitize_team_id(name: str) -> str:
    return re.sub(r'[^A-Za-z0-9]', '', name)

def filename_with_spaces(name: str, ext: str) -> str:
    cleaned = re.sub(r'[\/:*?"<>|]+', '', name).strip()
    return f"{cleaned}{ext}"

def download_logo(url: str, filepath: str) -> bool:
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"  ! Failed to download {url}: {e}")
        return False
    with open(filepath, "wb") as f:
        f.write(r.content)
    return True

def ext_from_url(url: str) -> str:
    return os.path.splitext(url)[1] if os.path.splitext(url)[1] else ".png"

def fetch_all_teams():
    all_teams = []
    page = 1
    while True:
        url = f"https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams?page={page}"
        resp = requests.get(url, timeout=20)
        if resp.status_code != 200:
            break
        data = resp.json()
        try:
            teams = data["sports"][0]["leagues"][0]["teams"]
        except (KeyError, IndexError):
            break
        if not teams:
            break
        all_teams.extend(teams)
        page += 1
        time.sleep(0.1)
    return all_teams

def word_overlap_score(a, b):
    set_a = set(a.lower().replace("(","").replace(")","").split())
    set_b = set(b.lower().replace("(","").replace(")","").split())
    return len(set_a & set_b)

def find_best_match_csv_name(csv_name, espn_teams):
    """
    Match full 'School + Nickname' (CSV) against ESPN 'displayName' using token overlap and manual mapping
    """

    for t in espn_teams:
        t_data = t.get("team")
        if not t_data:
            continue
        if t_data.get("displayName","").lower() == csv_name:
            return t_data

    # 2. Token overlap
    best_team = None
    best_score = 0
    for t in espn_teams:
        t_data = t.get("team")
        if not t_data:
            continue
        espn_name = t_data.get("displayName","")
        score = word_overlap_score(csv_name, espn_name)
        if score > best_score:
            best_score = score
            best_team = t_data
    if best_score > 0:
        return best_team
    return None

def pick_best_logo(logos):
    if not logos:
        return None
    pngs = [l for l in logos if l.get("href","").lower().endswith(".png")]
    jpgs = [l for l in logos if l.get("href","").lower().endswith((".jpg", ".jpeg"))]
    for group in (pngs, jpgs):
        if group:
            group_sorted = sorted(group, key=lambda x: x.get("width",0), reverse=True)
            return group_sorted[0].get("href")
    return logos[0].get("href")

def main():
    espn_teams = fetch_all_teams()
    items_for_dynamo = []
    downloaded = 0

    with open(CSV_FILE, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            school = row["School"].strip()
            nickname = row["Nickname"].strip()
            csv_name = f"{school} {nickname}"

            matched_team = find_best_match_csv_name(csv_name, espn_teams)
            if not matched_team:
                print(f"  ! Team not found on ESPN: {csv_name}")
                continue

            logos = matched_team.get("logos") or []
            logo_url = pick_best_logo(logos)
            if not logo_url:
                print(f"  ! No logos for team: {csv_name}")
                continue

            ext = ext_from_url(logo_url)
            filename = filename_with_spaces(csv_name, ext)
            filepath = os.path.join(OUT_DIR, filename)

            if download_logo(logo_url, filepath):
                downloaded += 1
                print(f"  ✅ Downloaded {filename}")
            else:
                print(f"  ! Failed to download {csv_name}")
                continue

            team_id = sanitize_team_id(csv_name)
            dynamo_item = {
                "pk": "SPORT-CFB",
                "sk": f"TEAM-{team_id}",
                "teamName": matched_team.get("displayName",""),
                "displayName": matched_team.get("shortDisplayName",""),
                "logoFilename": filename,
                "logoUrl": logo_url
            }
            items_for_dynamo.append(dynamo_item)
            time.sleep(0.1)

    with open(DYNAMO_FILE, "w", encoding='utf-8') as f:
        json.dump(items_for_dynamo, f, indent=2, ensure_ascii=False)

    print(f"\nDownloaded logos: {downloaded}")
    print(f"DynamoDB JSON file: {DYNAMO_FILE}")
    print(f"Logo folder: {OUT_DIR}")

if __name__ == "__main__":
    main()
