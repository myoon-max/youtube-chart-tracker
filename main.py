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
    # 1. Trending (API 유지 - 건드리지 않음)
    "KR_Daily_Trending": "https://charts.youtube.com/charts/TrendingVideos/kr/RightNow",
    "US_Daily_Trending": "https://charts.youtube.com/charts/TrendingVideos/us/RightNow",
    
    # 2. Daily MV (스크린샷 기반 Hidden 태그 정밀 타격)
    "KR_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/kr/daily",
    "US_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/us/daily",

    # 3. Weekly (기존 코드 유지 - 잘 작동함)
    "KR_Weekly_Top_MV": "https://charts.youtube.com/charts/TopVideos/kr/weekly",
    "US_Weekly_Top_MV": "https://charts.youtube.com/charts/TopVideos/us/weekly",
    "KR_Weekly_Top_Songs": "https://charts.youtube.com/charts/TopSongs/kr/weekly",
    "US_Weekly_Top_Songs": "https://charts.youtube.com/charts/TopSongs/us/weekly",
    
    # 4. Shorts (ID 추출 방식: Method 3 Anchor 태그 적용)
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
    # Source ID 기반이 아니라 Video ID 기반으로 리다이렉트 태우는게 더 안전
    url = f"https://www.youtube.com/source/{video_id}/shorts"
    try:
        driver.get(url)
        time.sleep(1.5) 
        body_text = driver.find_element(By.TAG_NAME, "body").text
        # "82K shorts" 또는 "1.2M videos" 패턴
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
    
    time.sleep(8)
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(3)
    
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    rows = soup.find_all('ytmc-entry-row')
    
    # 로딩 실패 시 재시도
    if not rows:
        time.sleep(5)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        rows = soup.find_all('ytmc-entry-row')
    
    data_list = []
    today = datetime.now().strftime("%Y-%m-%d")
    rank = 1
    
    # 차트 타입 플래그
    is_trending = "Trending" in chart_name
    is_daily_mv = "Daily_Top_MV" in chart_name
    is_weekly = "Weekly" in chart_name 
    is_shorts = "Shorts" in chart_name
    
    for row in rows:
        try:
            # 1. 제목/아티스트
            title = row.find('div', class_='title').get_text(strip=True)
            artist = ""
            artist_tag = row.find('span', class_='artistName')
            if not artist_tag: artist_tag = row.find('div', class_='subtitle')
            if artist_tag: artist = artist_tag.get_text(strip=True)
            
            # 2. Video ID 추출 (강력해진 로직)
            vid = ""
            
            # [Method 3] <a> 태그의 href 속성에서 추출 (가장 정확함, Shorts 해결책)
            # 보통 href="/watch?v=ID" 또는 music.youtube.com/watch?v=ID 형태임
            anchor = row.find('a')
            if anchor and 'href' in anchor.attrs:
                href = anchor['href']
                # v= 뒤에 오는 11자리 ID 추출
                match_href = re.search(r'v=([a-zA-Z0-9_-]{11})', href)
                if match_href:
                    vid = match_href.group(1)
            
            # href로 못 찾았을 경우(거의 없지만), 기존 img src 방식 백업 실행
            if not vid:
                img = row.find('img')
                if img and 'src' in img.attrs:
                    match_img = re.search(r'/vi(?:_webp)?/([a-zA-Z0-9_-]{11})', img['src'])
                    if match_img:
                        vid = match_img.group(1)
            
            final_views = 0
            
            # 3. 뷰 카운트 및 후처리 전략
            
            # [A] Trending: API (0으로 둠)
            if is_trending:
                pass 

            # [B] Shorts: 딥다이브 예정 (0으로 둠)
            elif is_shorts:
                pass

            # [C] Daily Top MV (문제의 구간 해결)
            # 스크린샷 분석: tablet-non-displayed-metric 클래스가 2개 있음.
            # 하나는 순위변동(작은수), 하나는 뷰카운트(큰수/hidden).
            # 전략: 해당 클래스를 가진 모든 놈을 찾아서 가장 큰 값을 View로 간주한다.
            elif is_daily_mv:
                hidden_metrics = row.find_all('div', class_='tablet-non-displayed-metric')
                max_val = 0
                for m in hidden_metrics:
                    txt = m.get_text(strip=True)
                    val = parse_count_strict(txt)
                    if val > max_val:
                        max_val = val
                final_views = max_val

            # [D] Weekly: 맨 오른쪽 metric
            elif is_weekly:
                metrics = row.find_all('div', class_='metric')
                if metrics:
                    final_views = parse_count_strict(metrics[-1].get_text(strip=True))

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
            
            # [Trending] API 사용
            if "Trending" in name:
                ids = [d["Video_ID"] for d in chart_data if d["Video_ID"]]
                if ids:
                    api_stats = get_views_from_api(ids)
                    for item in chart_data:
                        if item["Video_ID"] in api_stats:
                            item["Views"] = api_stats[item["Video_ID"]]
            
            # [Shorts] 딥다이브 (ID가 이제 확실하므로 잘 작동함)
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
        try:
            requests.post(webhook, json=final_data)
            print("Success!")
        except Exception as e:
            print(f"Send Error: {e}")
    else:
        print("No data or webhook missing.")
