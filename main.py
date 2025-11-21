import os
import json
import requests
import pandas as pd
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
import time
import re

# ================= 설정 =================
YOUTUBE_API_KEY = "AIzaSyDFFZNYygA85qp5p99qUG2Mh8Kl5qoLip4"

TARGET_URLS = {
    # [건드리지 않음] Trending
    "KR_Daily_Trending": "https://charts.youtube.com/charts/TrendingVideos/kr/RightNow",
    "US_Daily_Trending": "https://charts.youtube.com/charts/TrendingVideos/us/RightNow",
    
    # [Daily MV] HTML 숨겨진 태그(hidden)만 타격
    "KR_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/kr/daily",
    "US_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/us/daily",

    # [Weekly] 화면에 보이는 맨 오른쪽 컬럼 타격
    "KR_Weekly_Top_MV": "https://charts.youtube.com/charts/TopVideos/kr/weekly",
    "US_Weekly_Top_MV": "https://charts.youtube.com/charts/TopVideos/us/weekly",
    "KR_Weekly_Top_Songs": "https://charts.youtube.com/charts/TopSongs/kr/weekly",
    "US_Weekly_Top_Songs": "https://charts.youtube.com/charts/TopSongs/us/weekly",
    
    # [쇼츠]
    "KR_Daily_Top_Shorts": "https://charts.youtube.com/charts/TopShortsSongs/kr/daily",
    "US_Daily_Top_Shorts": "https://charts.youtube.com/charts/TopShortsSongs/us/daily"
}

# ================= 숫자 변환기 =================
def parse_count_strict(text):
    if not text: return 0
    t = str(text).lower().strip()
    
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

# ================= 쇼츠 개수 딥다이브 =================
def get_shorts_count_deep(driver, video_id):
    if not video_id: return 0
    url = f"https://www.youtube.com/source/{video_id}/shorts"
    try:
        driver.get(url)
        time.sleep(1.5)
        body_text = driver.find_element(By.TAG_NAME, "body").text
        match = re.search(r'([\d,.]+[KMB]?)\s*(shorts|videos)', body_text, re.IGNORECASE)
        if match:
            return parse_count_strict(match.group(1))
        return 0
    except: return 0

# ================= 드라이버 설정 =================
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--lang=en-US") 
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

# ================= 메인 스크래핑 =================
def scrape_chart(driver, chart_name, url):
    print(f"🚀 Scraping {chart_name}...")
    driver.get(url)
    
    time.sleep(7)
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(3)
    
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    rows = soup.find_all('ytmc-entry-row')
    
    if not rows:
        time.sleep(5)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        rows = soup.find_all('ytmc-entry-row')
    
    data_list = []
    today = datetime.now().strftime("%Y-%m-%d")
    rank = 1
    
    # 차트 타입 구분
    is_trending = "Trending" in chart_name
    is_shorts = "Shorts" in chart_name
    is_weekly = "Weekly" in chart_name
    is_daily_mv = "Daily_Top_MV" in chart_name # Top Songs는 Weekly만 있음
    
    for row in rows:
        try:
            # 1. 제목/아티스트
            title = row.find('div', class_='title').get_text(strip=True)
            artist = ""
            artist_tag = row.find('span', class_='artistName')
            if not artist_tag: artist_tag = row.find('div', class_='subtitle')
            if artist_tag: artist = artist_tag.get_text(strip=True)
            
            # 2. Video ID 추출 (강력한 Regex 적용)
            vid = ""
            img = row.find('img')
            if img and 'src' in img.attrs:
                src = img['src']
                # /vi/ 뒤에 오는 11자리 ID 무조건 추출 (webp 등 확장자 무시)
                match = re.search(r'/vi(?:_webp)?/([a-zA-Z0-9_-]{11})', src)
                if match:
                    vid = match.group(1)
            
            final_views = 0
            
            # 3. 뷰 카운트 로직 (차트별 분기)

            # [A] Trending & Shorts -> 후처리 대상 (일단 0)
            if is_trending or is_shorts:
                pass

            # [B] Daily Top MV -> "hidden" 속성이 있는 태그만 찾음
            elif is_daily_mv:
                # hidden 속성이 있는 div를 찾음. 
                # (주의: Rank변동이나 다른 정보가 hidden일 수도 있으니, 숫자(콤마 포함)인지 체크)
                hidden_divs = row.find_all('div', attrs={'hidden': True})
                for h_div in hidden_divs:
                    txt = h_div.get_text(strip=True)
                    # 콤마가 있거나 숫자가 큰 경우 (Last week=1,2 이런거 거름)
                    if txt and (',' in txt or parse_count_strict(txt) > 1000):
                        final_views = parse_count_strict(txt)
                        break
                
                # 만약 못찾았으면 fallback (거의 없을 것임)
                if final_views == 0:
                     # tablet-non-displayed-metric 중 가장 큰 숫자
                     metrics = row.find_all('div', class_='tablet-non-displayed-metric')
                     max_val = 0
                     for m in metrics:
                         val = parse_count_strict(m.get_text(strip=True))
                         if val > max_val: max_val = val
                     final_views = max_val

            # [C] Weekly Charts -> 화면 맨 끝에 보이는 "Weekly views"
            elif is_weekly:
                # class="metric" 인 것들 중 맨 마지막 요소가 Weekly Views임
                metrics = row.find_all('div', class_='metric')
                # 보통 Rank(metric) -> Last week(metric) -> Weeks on chart(metric) -> Views(metric) 순서임
                # 뒤에서부터 훑어서 숫자가 큰 걸 잡음
                if metrics:
                    last_metric = metrics[-1].get_text(strip=True)
                    final_views = parse_count_strict(last_metric)

            data_list.append({
                "Date": today,
                "Chart": chart_name,
                "Rank": rank,
                "Title": title,
                "Artist": artist,
                "Video_ID": vid,
                "Views": final_views
            })
            rank += 1
        except: continue
        
    return data_list

# ================= 메인 실행 =================
if __name__ == "__main__":
    driver = get_driver()
    final_data = []
    
    for name, url in TARGET_URLS.items():
        try:
            # 1. 기본 수집
            chart_data = scrape_chart(driver, name, url)
            
            # 2. 후처리
            
            # [Trending] API 조회
            if "Trending" in name:
                ids = [d["Video_ID"] for d in chart_data if d["Video_ID"]]
                if ids:
                    api_stats = get_views_from_api(ids)
                    for item in chart_data:
                        if item["Video_ID"] in api_stats:
                            item["Views"] = api_stats[item["Video_ID"]]
            
            # [Shorts] 딥다이브
            elif "Shorts" in name:
                print(f"  ↳ 🕵️‍♂️ Shorts Deep Dive ({len(chart_data)} items)...")
                for item in chart_data:
                    if item["Video_ID"]:
                        cnt = get_shorts_count_deep(driver, item["Video_ID"])
                        item["Views"] = cnt
            
            final_data.extend(chart_data)
            print(f"✅ {name}: {len(chart_data)} rows done.")
            
        except Exception as e:
            print(f"Error on {name}: {e}")
            
    driver.quit()
    
    webhook = os.environ.get("APPS_SCRIPT_WEBHOOK")
    if final_data and webhook:
        print(f"Total {len(final_data)} rows. Sending...")
        requests.post(webhook, json=final_data)
        print("Success!")
    else:
        print("No data or webhook missing.")
