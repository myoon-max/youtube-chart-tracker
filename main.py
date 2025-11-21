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
    # [건드리지 않음] Trending: API 사용
    "KR_Daily_Trending": "https://charts.youtube.com/charts/TrendingVideos/kr/RightNow",
    "US_Daily_Trending": "https://charts.youtube.com/charts/TrendingVideos/us/RightNow",
    
    # [원복 대상] 6개 차트: HTML 숨겨진 태그(hidden) 정밀 타격
    "KR_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/kr/daily",
    "KR_Weekly_Top_MV": "https://charts.youtube.com/charts/TopVideos/kr/weekly",
    "US_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/us/daily",
    "US_Weekly_Top_MV": "https://charts.youtube.com/charts/TopVideos/us/weekly",
    "KR_Weekly_Top_Songs": "https://charts.youtube.com/charts/TopSongs/kr/weekly",
    "US_Weekly_Top_Songs": "https://charts.youtube.com/charts/TopSongs/us/weekly",
    
    # [쇼츠] 딥다이브
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
    
    # 숫자와 점(.)만 남김
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

# ================= 쇼츠 개수 딥다이브 (수정됨) =================
def get_shorts_count_deep(driver, video_id):
    if not video_id: return 0
    url = f"https://www.youtube.com/source/{video_id}/shorts"
    try:
        driver.get(url)
        # 로딩 대기 시간 약간 증가 (0 방지)
        time.sleep(2) 
        
        # body 전체 텍스트에서 패턴 검색
        body_text = driver.find_element(By.TAG_NAME, "body").text
        
        # 패턴: "82K shorts" 또는 "1.5M videos" (대소문자 무시)
        # 어떤 경우는 그냥 숫자만 뜰 수도 있어서 유연하게 대처
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
    
    for row in rows:
        try:
            title = row.find('div', class_='title').get_text(strip=True)
            artist = ""
            artist_tag = row.find('span', class_='artistName')
            if not artist_tag: artist_tag = row.find('div', class_='subtitle')
            if artist_tag: artist = artist_tag.get_text(strip=True)
            
            img = row.find('img')
            vid = ""
            if img and 'src' in img.attrs and '/vi/' in img['src']:
                vid = img['src'].split('/vi/')[1].split('/')[0]
            
            final_views = 0
            
            # [A] Trending: API 사용 (0으로 둠 -> 후처리)
            if is_trending:
                pass

            # [B] Shorts: 딥다이브 사용 (0으로 둠 -> 후처리)
            elif is_shorts:
                pass

            # [C] MV / Songs (6개 차트): HTML 태그 정밀 타격 (원복됨)
            else:
                # 1순위: 님이 찾은 그 숨겨진 태그 (tablet-non-displayed-metric)
                # Top Songs나 Daily MV의 '콤마 숫자'가 여기 들어있음
                hidden_metric = row.select_one('.tablet-non-displayed-metric')
                
                # 2순위: 일반 views (보이는 숫자)
                views_div = row.find('div', class_='views')
                if not views_div: views_div = row.find('div', class_='metric')
                
                found_text = ""
                
                if hidden_metric:
                    found_text = hidden_metric.get_text(strip=True)
                elif views_div:
                    found_text = views_div.get_text(strip=True)
                
                # 추출한 텍스트만 파싱 (행 전체 텍스트 X -> 2025 오류 해결)
                final_views = parse_count_strict(found_text)

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
