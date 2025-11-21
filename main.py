import os
import json
import requests
import pandas as pd
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
from bs4 import BeautifulSoup
import time
import re

# ================= 설정 =================
YOUTUBE_API_KEY = "AIzaSyDFFZNYygA85qp5p99qUG2Mh8Kl5qoLip4"

TARGET_URLS = {
    # 기존 차트
    "KR_Daily_Trending": "https://charts.youtube.com/charts/Trending/kr/global",
    "KR_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/kr/daily",
    "KR_Weekly_Top_MV": "https://charts.youtube.com/charts/TopVideos/kr/weekly",
    "KR_Weekly_Top_Songs": "https://charts.youtube.com/charts/TopSongs/kr/weekly",
    "US_Daily_Trending": "https://charts.youtube.com/charts/Trending/us/global",
    "US_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/us/daily",
    "US_Weekly_Top_MV": "https://charts.youtube.com/charts/TopVideos/us/weekly",
    "US_Weekly_Top_Songs": "https://charts.youtube.com/charts/TopSongs/us/weekly",
    
    # [신규 추가] 쇼츠 차트
    "KR_Daily_Top_Shorts": "https://charts.youtube.com/charts/TopShortsSongs/kr/daily",
    "US_Daily_Top_Shorts": "https://charts.youtube.com/charts/TopShortsSongs/us/daily"
}

# ================= 숫자 변환기 (1.2M -> 1200000) =================
def parse_view_count(text):
    if not text: return 0
    clean_text = text.lower().replace('views', '').replace('조회수', '').replace('shorts', '').strip()
    try:
        multiplier = 1
        if 'm' in clean_text:
            multiplier = 1_000_000
            clean_text = clean_text.replace('m', '')
        elif 'k' in clean_text:
            multiplier = 1_000
            clean_text = clean_text.replace('k', '')
        elif 'b' in clean_text:
            multiplier = 1_000_000_000
            clean_text = clean_text.replace('b', '')
            
        return int(float(clean_text.replace(',', '')) * multiplier)
    except:
        return 0

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

# ================= 크롤링 로직 =================
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080") 
    # 영어로 설정해야 'Views' 텍스트 찾기가 수월함
    chrome_options.add_argument("--lang=en-US") 
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def scrape_chart(driver, chart_name, url):
    print(f"Scraping {chart_name}...")
    driver.get(url)
    
    # 쇼츠나 트렌딩은 로딩이 김
    wait_time = 15 if ("Trending" in chart_name or "Shorts" in chart_name) else 7
    time.sleep(wait_time)
    
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(3)
    
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    rows = soup.find_all('ytmc-entry-row')
    
    # 못 찾았으면 한 번 더 (안전장치)
    if not rows:
        time.sleep(5)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        rows = soup.find_all('ytmc-entry-row')
    
    chart_data = []
    today = datetime.now().strftime("%Y-%m-%d")
    rank = 1
    
    for row in rows:
        try:
            title = row.find('div', class_='title').get_text(strip=True)
            
            artist_tag = row.find('span', class_='artistName')
            if not artist_tag: artist_tag = row.find('div', class_='subtitle')
            artist = artist_tag.get_text(strip=True) if artist_tag else ""
            
            # Video ID 추출 (MV 차트용)
            img = row.find('img')
            vid = ""
            if img and 'src' in img.attrs and '/vi/' in img['src']:
                vid = img['src'].split('/vi/')[1].split('/')[0]
            
            # 조회수 텍스트 추출 (Song/Shorts 차트용)
            # 1. class='views' 찾기
            views_text = ""
            views_div = row.find('div', class_='views')
            if not views_div: views_div = row.find('div', class_='metric') # 쇼츠는 metric일수도
            
            if views_div:
                views_text = views_div.get_text(strip=True)
            else:
                # 2. 없으면 정규식으로 M, K, B 찾기
                row_text = row.get_text(separator=' ', strip=True)
                match = re.search(r'([\d,.]+[M|K|B])', row_text, re.IGNORECASE)
                if match:
                    views_text = match.group(1)
            
            # 텍스트를 숫자로 변환 (API 실패 시 사용)
            scraped_views = parse_view_count(views_text)

            chart_data.append({
                "Date": today,
                "Chart": chart_name,
                "Rank": rank,
                "Title": title,
                "Artist": artist,
                "Video_ID": vid,
                "Views": scraped_views # 일단 스크래핑한 값 넣기
            })
            rank += 1
        except: continue
        
    return chart_data

# ================= 메인 실행 =================
if __name__ == "__main__":
    driver = get_driver()
    final_data = []
    
    for name, url in TARGET_URLS.items():
        try:
            # 1. 기본 스크래핑 (화면 텍스트 위주)
            data = scrape_chart(driver, name, url)
            
            # 2. Video ID가 있는 경우 API로 덮어쓰기 (더 정확하니까)
            ids_to_fetch = [d["Video_ID"] for d in data if d["Video_ID"]]
            if ids_to_fetch:
                api_stats = get_views_from_api(ids_to_fetch)
                for item in data:
                    if item["Video_ID"] in api_stats:
                        item["Views"] = api_stats[item["Video_ID"]]
            
            final_data.extend(data)
            print(f"✅ {name}: {len(data)} rows (API update: {len(ids_to_fetch)})")
            
        except Exception as e:
            print(f"Error on {name}: {e}")
            
    driver.quit()
    
    # 전송
    webhook = os.environ.get("APPS_SCRIPT_WEBHOOK")
    if final_data and webhook:
        print(f"Total {len(final_data)} rows. Sending...")
        requests.post(webhook, json=final_data)
    else:
        print("No data or webhook missing.")
