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
    # 1. Trending (API 필수)
    "KR_Daily_Trending": "https://charts.youtube.com/charts/TrendingVideos/kr/RightNow",
    "US_Daily_Trending": "https://charts.youtube.com/charts/TrendingVideos/us/RightNow",
    
    # 2. MV (API 안씀 -> HTML 히든/공개 태그 긁기)
    "KR_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/kr/daily",
    "KR_Weekly_Top_MV": "https://charts.youtube.com/charts/TopVideos/kr/weekly",
    "US_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/us/daily",
    "US_Weekly_Top_MV": "https://charts.youtube.com/charts/TopVideos/us/weekly",
    
    # 3. Songs (ID 없음 -> 화면 숫자 긁기 필수)
    "KR_Weekly_Top_Songs": "https://charts.youtube.com/charts/TopSongs/kr/weekly",
    "US_Weekly_Top_Songs": "https://charts.youtube.com/charts/TopSongs/us/weekly",
    
    # 4. Shorts (ID 있음 -> 딥다이브 개수 긁기)
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

# ================= API 조회 (Trending 전용) =================
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

# ================= 스크래핑 로직 =================
def scrape_chart(driver, chart_name, url):
    print(f"🚀 Scraping {chart_name}...")
    driver.get(url)
    
    time.sleep(8)
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
    
    # 차트 구분
    is_trending = "Trending" in chart_name
    is_daily_mv = "Daily_Top_MV" in chart_name
    is_weekly = "Weekly" in chart_name 
    is_shorts = "Shorts" in chart_name
    
    for row in rows:
        try:
            title = row.find('div', class_='title').get_text(strip=True)
            artist = ""
            artist_tag = row.find('span', class_='artistName')
            if not artist_tag: artist_tag = row.find('div', class_='subtitle')
            if artist_tag: artist = artist_tag.get_text(strip=True)
            
            # [수정] Video ID 추출 (정규식으로 11자리 ID 강제 추출)
            vid = ""
            img = row.find('img')
            if img and 'src' in img.attrs:
                # /vi/ 또는 /vi_webp/ 뒤에 있는 11자리 문자열 추출
                match = re.search(r'/vi(?:_webp)?/([a-zA-Z0-9_-]{11})', img['src'])
                if match:
                    vid = match.group(1)
            
            final_views = 0
            
            # -------------------------------------------------------
            # 1. Trending: API 사용 (0으로 둠)
            # -------------------------------------------------------
            if is_trending:
                pass 

            # -------------------------------------------------------
            # 2. Shorts: 딥다이브 (0으로 둠)
            # -------------------------------------------------------
            elif is_shorts:
                pass

            # -------------------------------------------------------
            # 3. Daily Top MV: "hidden" 태그 긁기 (HTML)
            # -------------------------------------------------------
            elif is_daily_mv:
                # hidden 속성이 있는 div를 모두 찾음
                hidden_divs = row.find_all('div', attrs={'hidden': True})
                for h in hidden_divs:
                    txt = h.get_text(strip=True)
                    # 숫자가 있고(Daily view), 길이가 좀 되는 것(단순 랭크변동 1,2 아님) 확인
                    if txt and re.search(r'\d', txt):
                        val = parse_count_strict(txt)
                        # 일간 조회수가 보통 1000은 넘으므로 필터링 (랭크 변동 숫자 제외 목적)
                        if val > 100: 
                            final_views = val
                            break

            # -------------------------------------------------------
            # 4. Weekly (MV/Songs): 화면 "맨 오른쪽" 컬럼 긁기
            # -------------------------------------------------------
            elif is_weekly:
                # metric 클래스들 중 가장 마지막 것이 Weekly Views임
                metrics = row.find_all('div', class_='metric')
                if metrics:
                    # 뒤에서 첫번째
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
            # 1. 1차 수집
            chart_data = scrape_chart(driver, name, url)
            
            # 2. 후처리
            
            # [A] Trending Only -> API 사용
            if "Trending" in name:
                ids = [d["Video_ID"] for d in chart_data if d["Video_ID"]]
                if ids:
                    api_stats = get_views_from_api(ids)
                    for item in chart_data:
                        if item["Video_ID"] in api_stats:
                            item["Views"] = api_stats[item["Video_ID"]]
            
            # [B] Shorts -> 딥다이브 (개수 파악)
            elif "Shorts" in name:
                print(f"  ↳ 🕵️‍♂️ Checking Shorts count for {len(chart_data)} items...")
                for item in chart_data:
                    if item["Video_ID"]:
                        cnt = get_shorts_count_deep(driver, item["Video_ID"])
                        item["Views"] = cnt
            
            # [C] MV, Songs -> 이미 scrape_chart에서 HTML 로직으로 다 가져왔음 (추가 작업 X)
            
            final_data.extend(chart_data)
            print(f"✅ {name}: {len(chart_data)} rows done.")
            
        except Exception as e:
            print(f"Error on {name}: {e}")
            
    driver.quit()
    
    webhook = os.environ.get("APPS_SCRIPT_WEBHOOK")
    if final_data and webhook:
        print(f"Total {len(final_data)} rows. Sending...")
        try:
            requests.post(webhook, json=final_data)
            print("Success!")
        except Exception as e:
            print(f"Send Error: {e}")
    else:
        print("No data or webhook missing.")
