import os
import re
import time
import json
import requests
import traceback
from datetime import datetime
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By

# ==========================================
# [PART 1] 유튜브 설정 및 크롤러 (원본 유지)
# ==========================================

YOUTUBE_API_KEY = "AIzaSyDFFZNYygA85qp5p99qUG2Mh8Kl5qoLip4"

TARGET_URLS = {
    # 1. Trending (API)
    "KR_Daily_Trending": "https://charts.youtube.com/charts/TrendingVideos/kr/RightNow",
    "US_Daily_Trending": "https://charts.youtube.com/charts/TrendingVideos/us/RightNow",
    
    # 2. Daily MV (Hidden Div)
    "KR_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/kr/daily",
    "US_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/us/daily",

    # 3. Weekly (Visible Metric)
    "KR_Weekly_Top_MV": "https://charts.youtube.com/charts/TopVideos/kr/weekly",
    "US_Weekly_Top_MV": "https://charts.youtube.com/charts/TopVideos/us/weekly",
    "KR_Weekly_Top_Songs": "https://charts.youtube.com/charts/TopSongs/kr/weekly",
    "US_Weekly_Top_Songs": "https://charts.youtube.com/charts/TopSongs/us/weekly",
    
    # 4. Shorts (HTML Text Parsing)
    "KR_Daily_Top_Shorts": "https://charts.youtube.com/charts/TopShortsSongs/kr/daily",
    "US_Daily_Top_Shorts": "https://charts.youtube.com/charts/TopShortsSongs/us/daily"
}

# [NEW] 추가 플랫폼 URL
EXTRA_URLS = {
    "Melon_Daily_Top100": "https://www.melon.com/chart/day/index.htm",
    "Genie_Daily_Top200": "https://www.genie.co.kr/chart/top200",
    "Spotify_Global_Daily": "https://kworb.net/spotify/country/global_daily.html",
    "Spotify_US_Daily": "https://kworb.net/spotify/country/us_daily.html",
    "Spotify_KR_Daily": "https://kworb.net/spotify/country/kr_daily.html",
    "Billboard_Hot100": "https://kworb.net/charts/billboard/hot100.html"
}

# ================= 유틸리티 =================
def parse_count_strict(text):
    if not text: return 0
    t = str(text).lower().strip().replace(',', '')
    multiplier = 1
    if 'k' in t: multiplier = 1_000
    elif 'm' in t: multiplier = 1_000_000
    elif 'b' in t: multiplier = 1_000_000_000
    clean = re.sub(r'[^\d.]', '', t)
    if not clean: return 0
    try:
        val = float(clean)
        return int(val * multiplier)
    except: return 0

def clean_text(text):
    return re.sub(r'\s+', ' ', text).strip()

# ================= 드라이버 설정 =================
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--lang=en-US")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36")
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

# ================= Shorts 딥다이브 (유튜브용) =================
def get_shorts_creation_count(driver, video_id):
    if not video_id: return 0
    url = f"https://www.youtube.com/source/{video_id}/shorts"
    try:
        driver.get(url)
        time.sleep(1)
        body_text = driver.find_element(By.TAG_NAME, "body").text
        match = re.search(r'([\d,.]+[KMB]?)\s*Shorts', body_text, re.IGNORECASE)
        if match:
            return parse_count_strict(match.group(1))
        return 0
    except: return 0

# ================= API 조회 (유튜브용) =================
def get_views_from_api(video_ids):
    if not video_ids: return {}
    url = "https://www.googleapis.com/youtube/v3/videos"
    stats_map = {}
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i+50]
        params = {"part": "statistics", "id": ",".join(chunk), "key": YOUTUBE_API_KEY}
        try:
            res = requests.get(url, params=params).json()
            if "items" in res:
                for item in res["items"]:
                    vid = item["id"]
                    view_count = int(item["statistics"].get("viewCount", 0))
                    stats_map[vid] = view_count
        except: pass
    return stats_map

# ================= 메인 스크래퍼 (유튜브) =================
def scrape_chart(chart_name, url, driver):
    print(f"🚀 Scraping {chart_name}...")
    driver.get(url)
    time.sleep(5)
    
    data_list = []
    today = datetime.now().strftime("%Y-%m-%d")
    
    is_trending = "Trending" in chart_name
    is_shorts = "Shorts" in chart_name
    is_daily_mv = "Daily_Top_MV" in chart_name
    is_weekly = "Weekly" in chart_name
    
    # CASE 1: Shorts (HTML Text 파싱 -> Deep Dive)
    if is_shorts:
        print("   ↳ Shorts Mode: Parsing HTML text directly...")
        last_height = driver.execute_script("return document.body.scrollHeight")
        for _ in range(30):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.5)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height: break
            last_height = new_height
        time.sleep(2)

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        rows = soup.find_all('ytmc-entry-row')

        for idx, row in enumerate(rows):
            try:
                title = row.find('div', class_='title').get_text(strip=True)
                artist_tag = row.find('span', class_='artistName') or row.find('div', class_='subtitle')
                artist = artist_tag.get_text(strip=True) if artist_tag else ""
                
                row_html = str(row)
                vid = ""
                match = re.search(r'watch\?v=([a-zA-Z0-9_-]{11})', row_html)
                if match:
                    vid = match.group(1)
                
                shorts_count = 0
                if vid:
                    shorts_count = get_shorts_creation_count(driver, vid)
                
                data_list.append({
                    "Date": today, "Chart": chart_name, "Rank": idx+1,
                    "Title": title, "Artist": artist, "Video_ID": vid, "Views": shorts_count
                })
            except: continue

    # CASE 2: MV / Songs / Trending
    else:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        rows = soup.find_all('ytmc-entry-row')
        
        for idx, row in enumerate(rows):
            try:
                title = row.find('div', class_='title').get_text(strip=True)
                artist_tag = row.find('span', class_='artistName') or row.find('div', class_='subtitle')
                artist = artist_tag.get_text(strip=True) if artist_tag else ""
                
                vid = ""
                anchor = row.find('a')
                if anchor and 'href' in anchor.attrs:
                    m = re.search(r"v=([A-Za-z0-9_-]{11})", anchor['href'])
                    if m: vid = m.group(1)
                
                if not vid:
                    img = row.find('img')
                    if img and 'src' in img.attrs:
                        m = re.search(r'/vi(?:_webp)?/([a-zA-Z0-9_-]{11})', img['src'])
                        if m: vid = m.group(1)

                final_views = 0
                
                if is_trending:
                    pass 
                elif is_daily_mv:
                    hidden_divs = row.find_all('div', class_='tablet-non-displayed-metric')
                    max_val = 0
                    for h in hidden_divs:
                        val = parse_count_strict(h.get_text(strip=True))
                        if val > max_val: max_val = val
                    final_views = max_val
                elif is_weekly:
                    metrics = row.find_all('div', class_='metric')
                    if metrics:
                        final_views = parse_count_strict(metrics[-1].get_text(strip=True))
                
                data_list.append({
                    "Date": today, "Chart": chart_name, "Rank": idx+1,
                    "Title": title, "Artist": artist, "Video_ID": vid, "Views": final_views
                })
            except: continue

    return data_list

# ==========================================
# [PART 2] 신규 플랫폼 크롤러
# ==========================================

# 1. Melon Scraper
def scrape_melon():
    print("🍈 Scraping Melon Daily...")
    url = EXTRA_URLS["Melon_Daily_Top100"]
    headers = {'User-Agent': 'Mozilla/5.0'}
    data = []
    today = datetime.now().strftime("%Y-%m-%d")

    try:
        res = requests.get(url, headers=headers)
        soup = BeautifulSoup(res.text, 'html.parser')
        rows = soup.select('tr.lst50, tr.lst100')

        for row in rows:
            try:
                rank = int(row.select_one('span.rank').text)
                title = row.select_one('div.ellipsis.rank01 > span > a').text.strip()
                artist = row.select_one('div.ellipsis.rank02 > a').text.strip()
                
                data.append({
                    "Date": today, "Chart": "Melon_Daily_Top100", "Rank": rank,
                    "Title": title, "Artist": artist, "Video_ID": "", "Views": 0
                })
            except: continue
        print(f"✅ Melon: {len(data)} rows")
    except Exception as e: print(f"❌ Melon Error: {e}")
    return data

# 2. Genie Scraper
def scrape_genie():
    print("🧞 Scraping Genie Daily...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    data = []
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        for page in range(1, 3):
            res = requests.get(f"{EXTRA_URLS['Genie_Daily_Top200']}?pg={page}", headers=headers)
            soup = BeautifulSoup(res.text, 'html.parser')
            rows = soup.select('tbody > tr.list')
            for row in rows:
                try:
                    rank = int(row.select_one('td.number').text.split()[0])
                    title = row.select_one('a.title').text.strip()
                    artist = row.select_one('a.artist').text.strip()
                    
                    data.append({
                        "Date": today, "Chart": "Genie_Daily_Top200", "Rank": rank,
                        "Title": title, "Artist": artist, "Video_ID": "", "Views": 0
                    })
                except: continue
        print(f"✅ Genie: {len(data)} rows")
    except Exception as e: print(f"❌ Genie Error: {e}")
    return data

# 3. Kworb Scraper (Spotify/Billboard)
def scrape_kworb(chart_key, url):
    print(f"🟢 Scraping {chart_key} via Kworb...")
    data = []
    today = datetime.now().strftime("%Y-%m-%d")
    platform = "Billboard" if "Billboard" in chart_key else "Spotify"

    try:
        res = requests.get(url)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        rows = soup.select('tbody > tr')

        for row in rows:
            cols = row.find_all('td')
            if not cols: continue
            try:
                # Rank Clean
                rank_raw = cols[0].get_text(strip=True)
                rank_match = re.match(r'(\d+)', rank_raw)
                if not rank_match: continue
                rank = int(rank_match.group(1))

                # Artist - Title Clean
                col_idx = 1
                check_text = cols[1].get_text(strip=True)
                # 추이(+1, NEW 등) 컬럼이 있으면 한 칸 밀림
                if re.match(r'^[\+\-=]?\d*|NEW|RE$', check_text): 
                    col_idx = 2

                full_text = clean_text(cols[col_idx].get_text())
                if " - " in full_text:
                    parts = full_text.split(" - ", 1)
                    artist = parts[0].strip()
                    title = parts[1].strip()
                else:
                    artist = "Unknown"
                    title = full_text

                # Streams
                streams = 0
                if platform == "Spotify":
                    for c in reversed(cols):
                        txt = c.get_text().replace(',', '').strip()
                        if txt.isdigit() and len(txt) > 3:
                            streams = int(txt)
                            break

                data.append({
                    "Date": today, "Chart": chart_key, "Rank": rank,
                    "Title": title, "Artist": artist, "Video_ID": "", "Views": streams
                })
            except: continue
        print(f"✅ {chart_key}: {len(data)} rows")
    except Exception as e: print(f"❌ Kworb Error ({chart_key}): {e}")
    return data

# ==========================================
# [PART 3] 메인 실행 (통합 로직)
# ==========================================
if __name__ == "__main__":
    driver = None
    final_data = [] 

    try:
        # 1. [기존] 유튜브 크롤링
        print("=== [1] Starting YouTube Scraping (Selenium) ===")
        try:
            driver = get_driver()
            for name, url in TARGET_URLS.items():
                try:
                    chart_data = scrape_chart(name, url, driver)
                    
                    if "Trending" in name:
                        ids = [d["Video_ID"] for d in chart_data if d["Video_ID"]]
                        if ids:
                            api_stats = get_views_from_api(ids)
                            for item in chart_data:
                                if item["Video_ID"] in api_stats:
                                    item["Views"] = api_stats[item["Video_ID"]]
                    
                    final_data.extend(chart_data)
                    print(f"✅ YouTube {name}: {len(chart_data)} rows.")
                except Exception as e:
                    print(f"⚠️ Error on YouTube {name}: {e}")
        except Exception as yt_e:
            print(f"🔥 YouTube Driver Error: {yt_e}")
        finally:
            if driver: driver.quit()

        # 2. [추가] 멜론 & 지니
        print("\n=== [2] Starting Domestic Charts (Requests) ===")
        final_data.extend(scrape_melon())
        final_data.extend(scrape_genie())

        # 3. [추가] Kworb (Spotify, Billboard)
        print("\n=== [3] Starting Global Charts (Kworb) ===")
        for key, url in EXTRA_URLS.items():
            if "Spotify" in key or "Billboard" in key:
                final_data.extend(scrape_kworb(key, url))

        # 4. [전송] Apps Script
        print("\n=== [4] Sending Data to DB ===")
        webhook = os.environ.get("APPS_SCRIPT_WEBHOOK")
        if final_data and webhook:
            print(f"🚀 Sending {len(final_data)} total rows...")
            chunk_size = 2000
            for i in range(0, len(final_data), chunk_size):
                chunk = final_data[i:i+chunk_size]
                try:
                    requests.post(webhook, json=chunk)
                    print(f"  -> Chunk {i//chunk_size + 1} sent ({len(chunk)} rows).")
                    time.sleep(1)
                except Exception as e:
                    print(f"❌ Send Error (Chunk {i}): {e}")
            print("✨ All Scrapers Completed Successfully!")
        else:
            print("⚠️ No webhook URL or empty data.")

    except Exception as main_e:
        print("🔥 FATAL ERROR: Script crashed.")
        print(traceback.format_exc())
