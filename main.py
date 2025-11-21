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

# ================= 설정 =================
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

# ================= [수정됨] 드라이버 설정 (서버 충돌 방지용) =================
def get_driver():
    chrome_options = Options()
    # GitHub Actions 등 리눅스 서버에서 크롬이 죽지 않게 하는 필수 옵션들
    chrome_options.add_argument("--headless=new") # 구버전 headless보다 안정적
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage") # 메모리 부족 방지
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--lang=en-US")
    # User-Agent 추가 (봇 차단 방지)
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36")
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

# ================= Shorts 딥다이브 (82K 긁기) =================
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

# ================= 메인 스크래퍼 =================
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
        print("  ↳ Shorts Mode: Parsing HTML text directly...")
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
                # HTML 소스 내 watch?v=ID 찾기
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

# ================= 메인 실행 (에러 처리 추가됨) =================
if __name__ == "__main__":
    driver = None
    try:
        driver = get_driver()
        final_data = []
        
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
                print(f"✅ {name}: {len(chart_data)} rows done.")
                
            except Exception as e:
                print(f"Error on {name}: {e}")
                print(traceback.format_exc()) # 상세 에러 출력

        # 전송
        webhook = os.environ.get("APPS_SCRIPT_WEBHOOK")
        if final_data and webhook:
            print(f"Total {len(final_data)} rows. Sending...")
            try:
                requests.post(webhook, json=final_data)
                print("Success!")
            except Exception as e:
                print(f"Send Error: {e}")
        else:
            print("No webhook or data.")

    except Exception as main_e:
        # 여기가 핵심: 브라우저 실행 실패시 에러 메시지 출력 (Exit code 1 원인 파악용)
        print("🔥 FATAL ERROR: Script crashed.")
        print(main_e)
        print(traceback.format_exc())
        
    finally:
        if driver:
            driver.quit()
