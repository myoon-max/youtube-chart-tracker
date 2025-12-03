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

# ================= [1] 유튜브 설정 (기존 유지) =================
YOUTUBE_API_KEY = "AIzaSyDFFZNYygA85qp5p99qUG2Mh8Kl5qoLip4"

TARGET_URLS = {
    "KR_Daily_Trending": "https://charts.youtube.com/charts/TrendingVideos/kr/RightNow",
    "US_Daily_Trending": "https://charts.youtube.com/charts/TrendingVideos/us/RightNow",
    "KR_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/kr/daily",
    "US_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/us/daily",
    "KR_Weekly_Top_MV": "https://charts.youtube.com/charts/TopVideos/kr/weekly",
    "US_Weekly_Top_MV": "https://charts.youtube.com/charts/TopVideos/us/weekly",
    "KR_Weekly_Top_Songs": "https://charts.youtube.com/charts/TopSongs/kr/weekly",
    "US_Weekly_Top_Songs": "https://charts.youtube.com/charts/TopSongs/us/weekly",
    "KR_Daily_Top_Shorts": "https://charts.youtube.com/charts/TopShortsSongs/kr/daily",
    "US_Daily_Top_Shorts": "https://charts.youtube.com/charts/TopShortsSongs/us/daily"
}

# ================= [2] 추가 플랫폼 설정 (Melon, Genie, Spotify, Billboard) =================
EXTRA_URLS = {
    "Melon_Daily_Top100": "https://www.melon.com/chart/day/index.htm",
    "Genie_Daily_Top200": "https://www.genie.co.kr/chart/top200",
    "Spotify_Global_Daily": "https://kworb.net/spotify/country/global_daily.html",
    "Spotify_US_Daily": "https://kworb.net/spotify/country/us_daily.html",
    "Spotify_KR_Daily": "https://kworb.net/spotify/country/kr_daily.html",
    "Billboard_Hot100": "https://kworb.net/charts/billboard/hot100.html" # Kworb 제공 빌보드 차트
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

# ================= Shorts 딥다이브 =================
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

# ================= API 조회 =================
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

# ================= [1] 유튜브 스크래퍼 (기존) =================
def scrape_youtube_chart(chart_name, url, driver):
    print(f"🚀 Scraping YouTube {chart_name}...")
    driver.get(url)
    time.sleep(5)
    
    data_list = []
    today = datetime.now().strftime("%Y-%m-%d")
    
    is_trending = "Trending" in chart_name
    is_shorts = "Shorts" in chart_name
    is_daily_mv = "Daily_Top_MV" in chart_name
    is_weekly = "Weekly" in chart_name
    
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
                if match: vid = match.group(1)
                
                shorts_count = 0
                if vid: shorts_count = get_shorts_creation_count(driver, vid)
                
                data_list.append({
                    "Date": today, "Chart": chart_name, "Rank": idx+1,
                    "Title": title, "Artist": artist, "Video_ID": vid, "Views": shorts_count
                })
            except: continue

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

# ================= [2] 멜론 스크래퍼 =================
def scrape_melon():
    print("🍈 Scraping Melon Daily Chart...")
    url = EXTRA_URLS["Melon_Daily_Top100"]
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    data_list = []
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
                data_list.append({
                    "Date": today, "Chart": "Melon_Daily_Top100", "Rank": rank,
                    "Title": title, "Artist": artist, "Video_ID": "", "Views": 0 # Views 비공개
                })
            except: continue
        print(f"✅ Melon: {len(data_list)} rows.")
    except Exception as e:
        print(f"❌ Melon Error: {e}")
    
    return data_list

# ================= [3] 지니 스크래퍼 =================
def scrape_genie():
    print("🧞 Scraping Genie Daily Chart...")
    # 지니는 페이지네이션이 있어 1~50위(1페이지) ~ 200위(4페이지) 순회 필요
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    data_list = []
    today = datetime.now().strftime("%Y-%m-%d")
    base_url = EXTRA_URLS["Genie_Daily_Top200"]

    try:
        for page in range(1, 5): # 1~4페이지 (200위까지)
            res = requests.get(f"{base_url}?pg={page}", headers=headers)
            soup = BeautifulSoup(res.text, 'html.parser')
            rows = soup.select('tbody > tr.list')
            
            for row in rows:
                try:
                    rank_str = row.select_one('td.number').text.split('\n')[0].strip()
                    rank = int(rank_str)
                    title = row.select_one('td.info > a.title').text.strip()
                    artist = row.select_one('td.info > a.artist').text.strip()
                    data_list.append({
                        "Date": today, "Chart": "Genie_Daily_Top200", "Rank": rank,
                        "Title": title, "Artist": artist, "Video_ID": "", "Views": 0
                    })
                except: continue
            time.sleep(1)
            
        print(f"✅ Genie: {len(data_list)} rows.")
    except Exception as e:
        print(f"❌ Genie Error: {e}")

    return data_list

# ================= [4] Kworb (Spotify/Billboard) 스크래퍼 =================
def scrape_kworb(chart_key, url):
    print(f"🟢 Scraping {chart_key} via Kworb...")
    data_list = []
    today = datetime.now().strftime("%Y-%m-%d")

    try:
        res = requests.get(url)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        rows = soup.select('tbody > tr')

        for row in rows:
            cols = row.find_all('td')
            if not cols: continue
            try:
                # Rank
                rank_txt = cols[0].text.replace('.', '').strip()
                if not rank_txt.isdigit(): continue # 순위 없으면 패스
                rank = int(rank_txt)

                # Title & Artist Parsing
                full_text = cols[1].text.strip()
                if " - " in full_text:
                    artist, title = full_text.split(" - ", 1)
                else:
                    artist, title = "Unknown", full_text
                
                # Streams (Spotify Only) - 빌보드는 Views 없음
                streams = 0
                if "Spotify" in chart_key and len(cols) > 6:
                    streams_txt = cols[6].text.replace(',', '')
                    if streams_txt.isdigit(): streams = int(streams_txt)

                data_list.append({
                    "Date": today, "Chart": chart_key, "Rank": rank,
                    "Title": title.strip(), "Artist": artist.strip(), 
                    "Video_ID": "", "Views": streams
                })
            except: continue
        print(f"✅ {chart_key}: {len(data_list)} rows.")
    except Exception as e:
        print(f"❌ Kworb Error ({chart_key}): {e}")

    return data_list

# ================= 메인 실행 로직 =================
if __name__ == "__main__":
    driver = None
    final_data = []

    try:
        # 1. 유튜브 크롤링 (Selenium 필수)
        try:
            driver = get_driver()
            for name, url in TARGET_URLS.items():
                try:
                    chart_data = scrape_youtube_chart(name, url, driver)
                    
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

        # 2. 멜론 크롤링
        melon_data = scrape_melon()
        final_data.extend(melon_data)

        # 3. 지니 크롤링
        genie_data = scrape_genie()
        final_data.extend(genie_data)

        # 4. 스포티파이 & 빌보드 (Kworb) 크롤링
        for key, url in EXTRA_URLS.items():
            if "Spotify" in key or "Billboard" in key:
                kworb_data = scrape_kworb(key, url)
                final_data.extend(kworb_data)

        # 5. 데이터 전송
        webhook = os.environ.get("APPS_SCRIPT_WEBHOOK")
        if final_data and webhook:
            print(f"🚀 Total {len(final_data)} rows collected. Sending to DB...")
            # 데이터 양이 많으므로 1000개씩 끊어서 전송 (안정성 확보)
            chunk_size = 1000
            for i in range(0, len(final_data), chunk_size):
                chunk = final_data[i:i+chunk_size]
                try:
                    requests.post(webhook, json=chunk)
                    print(f"   ↳ Sent chunk {i//chunk_size + 1} ({len(chunk)} rows)")
                    time.sleep(1) # 부하 방지
                except Exception as e:
                    print(f"❌ Send Error (Chunk {i}): {e}")
            print("✨ All Data Sent Successfully!")
        else:
            print("⚠️ No webhook URL or empty data.")

    except Exception as main_e:
        print("🔥 FATAL ERROR: Script crashed.")
        print(main_e)
        print(traceback.format_exc())
