import os
import json
import requests
import pandas as pd
from datetime import datetime
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
    # 요청하신 URL로 전면 교체 완료
    "KR_Daily_Trending": "https://charts.youtube.com/charts/TrendingVideos/kr/RightNow",
    "KR_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/kr/daily",
    "KR_Weekly_Top_MV": "https://charts.youtube.com/charts/TopVideos/kr/weekly",
    "KR_Weekly_Top_Songs": "https://charts.youtube.com/charts/TopSongs/kr/weekly",
    "US_Daily_Trending": "https://charts.youtube.com/charts/TrendingVideos/us/RightNow",
    "US_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/us/daily",
    "US_Weekly_Top_MV": "https://charts.youtube.com/charts/TopVideos/us/weekly",
    "US_Weekly_Top_Songs": "https://charts.youtube.com/charts/TopSongs/us/weekly",
    "KR_Daily_Top_Shorts": "https://charts.youtube.com/charts/TopShortsSongs/kr/daily",
    "US_Daily_Top_Shorts": "https://charts.youtube.com/charts/TopShortsSongs/us/daily"
}

# ================= 숫자 변환기 (콤마 숫자 완벽 지원) =================
def parse_view_count(text):
    if not text: return 0
    # 공백 및 불필요한 문자 제거
    clean_text = text.lower().replace('views', '').replace('weekly', '').strip()
    
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
            
        # 숫자와 점(.)만 남기고 다 날림 (콤마 제거 포함)
        # 예: "4,842,974" -> "4842974"
        clean_text = re.sub(r'[^\d.]', '', clean_text)
        
        if not clean_text: return 0
        
        return int(float(clean_text) * multiplier)
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
    # 영문 페이지로 강제 (숫자 파싱 통일성 위해)
    chrome_options.add_argument("--lang=en-US") 
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def scrape_chart(driver, chart_name, url):
    print(f"Scraping {chart_name}...")
    driver.get(url)
    
    # 로딩 대기
    time.sleep(10)
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(5)
    
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    rows = soup.find_all('ytmc-entry-row')
    
    # 재시도 로직
    if not rows:
        print("  -> Retrying load...")
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
            
            # Video ID (MV 차트용)
            img = row.find('img')
            vid = ""
            if img and 'src' in img.attrs and '/vi/' in img['src']:
                vid = img['src'].split('/vi/')[1].split('/')[0]
            
            # [핵심 수정] 조회수 텍스트 추출
            views_text = "0"
            
            # 전략 1: class='views' (MV/Shorts 차트)
            views_div = row.find('div', class_='views')
            if not views_div: views_div = row.find('div', class_='metric')
            
            if views_div:
                views_text = views_div.get_text(strip=True)
            else:
                # 전략 2: Song 차트용 (콤마 숫자 or M/K 찾기)
                # 행 안의 모든 텍스트 덩어리를 가져옴
                all_divs = row.find_all('div')
                
                # 보통 조회수는 맨 뒤쪽에 위치함 -> 뒤에서부터 검사
                for div in reversed(all_divs):
                    txt = div.get_text(strip=True)
                    
                    # 패턴 A: "1.5M" 처럼 단축된 숫자
                    if re.search(r'\d+(\.\d+)?[MKB]', txt, re.IGNORECASE):
                        views_text = txt
                        break
                    
                    # 패턴 B: "4,842,974" 처럼 콤마가 포함된 완전한 숫자 (이게 Top Songs임!)
                    # 조건: 숫자로 시작하고, 콤마가 있고, 숫자로 끝남. (랭크 1, 2 등과 구별 위해 길이 체크)
                    if re.match(r'^\d{1,3}(,\d{3})+$', txt):
                        views_text = txt
                        break

            # 텍스트 -> 숫자 변환
            scraped_views = parse_view_count(views_text)

            chart_data.append({
                "Date": today,
                "Chart": chart_name,
                "Rank": rank,
                "Title": title,
                "Artist": artist,
                "Video_ID": vid,
                "Views": scraped_views 
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
            data = scrape_chart(driver, name, url)
            
            # Video ID 있으면 API로 업데이트 (MV 차트 정확도 UP)
            ids_to_fetch = [d["Video_ID"] for d in data if d["Video_ID"]]
            if ids_to_fetch:
                api_stats = get_views_from_api(ids_to_fetch)
                for item in data:
                    if item["Video_ID"] in api_stats:
                        item["Views"] = api_stats[item["Video_ID"]]
            
            final_data.extend(data)
            print(f"✅ {name}: {len(data)} rows collected.")
            
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
