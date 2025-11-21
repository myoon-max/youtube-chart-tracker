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

# ================= 숫자 변환기 (정밀 버전) =================
def parse_count_strict(text):
    if not text: return 0
    # 텍스트 소문자 변환
    t = str(text).lower().strip()
    
    # K, M, B 처리
    multiplier = 1
    if 'k' in t: multiplier = 1_000
    elif 'm' in t: multiplier = 1_000_000
    elif 'b' in t: multiplier = 1_000_000_000
    
    # 숫자와 점(.)만 추출 (콤마 제거)
    # 예: "82.5k shorts" -> "82.5"
    # 예: "4,842,974" -> "4842974"
    clean = re.sub(r'[^\d.]', '', t)
    
    if not clean: return 0
    
    # 점(.)이 여러 개면 오류이므로 첫 번째 점만 인정하거나 처리
    try:
        val = float(clean)
        return int(val * multiplier)
    except:
        return 0

# ================= API 조회 =================
def get_views_from_api(video_ids):
    if not video_ids: return {}
    url = "https://www.googleapis.com/youtube/v3/videos"
    stats_map = {}
    # 50개씩 배치 처리
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i+50]
        params = {"part": "statistics", "id": ",".join(chunk), "key": YOUTUBE_API_KEY}
        try:
            res = requests.get(url, params=params).json()
            if "items" in res:
                for item in res["items"]:
                    vid = item["id"]
                    # API는 문자열로 옴, int 변환
                    view_count = int(item["statistics"].get("viewCount", 0))
                    stats_map[vid] = view_count
        except: pass
    return stats_map

# ================= 쇼츠 개수 딥다이브 =================
def get_shorts_count_deep(driver, video_id):
    url = f"https://www.youtube.com/source/{video_id}/shorts"
    try:
        driver.get(url)
        time.sleep(1.5) # 너무 빠르면 로딩 안됨
        
        # 전체 텍스트에서 "82K shorts" 패턴 찾기
        body_text = driver.find_element(By.TAG_NAME, "body").text
        
        # 정규식: 숫자(콤마/점 포함) + 공백(옵션) + shorts
        # 대소문자 무시
        match = re.search(r'([\d,.]+[KMB]?)\s*shorts', body_text, re.IGNORECASE)
        if match:
            return parse_count_strict(match.group(1))
            
        return 0
    except:
        return 0

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
    
    # 로딩 대기
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
    
    is_shorts = "Shorts" in chart_name
    
    for row in rows:
        try:
            # 제목/아티스트
            title = row.find('div', class_='title').get_text(strip=True)
            artist_tag = row.find('span', class_='artistName')
            if not artist_tag: artist_tag = row.find('div', class_='subtitle')
            artist = artist_tag.get_text(strip=True) if artist_tag else ""
            
            # Video ID
            img = row.find('img')
            vid = ""
            if img and 'src' in img.attrs and '/vi/' in img['src']:
                vid = img['src'].split('/vi/')[1].split('/')[0]
            
            final_views = 0
            
            # -------------------------------------------------------
            # 전략 A: 쇼츠 차트 -> 나중에 딥다이브 할거임 (일단 0)
            # -------------------------------------------------------
            if is_shorts:
                pass 
                
            # -------------------------------------------------------
            # 전략 B: Trending / MV 차트 -> ID 있으면 API 쓸거임 (일단 0)
            # -------------------------------------------------------
            elif vid and ("Trending" in chart_name or "MV" in chart_name):
                pass 
                
            # -------------------------------------------------------
            # 전략 C: Songs 차트 (ID 없음) -> 화면 텍스트 파싱 (정밀)
            # -------------------------------------------------------
            else:
                # 여기서 1.17E+21 오류 원인 제거
                # 행 안의 모든 텍스트 중 "콤마가 있는 숫자" or "M/K/B가 붙은 숫자"만 찾음
                all_divs = row.find_all('div')
                found_text = ""
                
                for div in reversed(all_divs):
                    txt = div.get_text(strip=True)
                    
                    # 1. 콤마 숫자 (예: 4,842,974) -> Rank(1~100)나 Year(2025) 제외
                    # 길이가 4자 이상이고 콤마가 포함되어야 함
                    if re.match(r'^\d{1,3}(,\d{3})+$', txt):
                        found_text = txt
                        break
                        
                    # 2. 단축 숫자 (예: 1.5M)
                    if re.match(r'^[\d.]+[KMB]$', txt, re.IGNORECASE):
                        found_text = txt
                        break
                
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
            # 1. 기본 스크래핑
            chart_data = scrape_chart(driver, name, url)
            
            # 2. 데이터 보정 (Post-Processing)
            
            # [Case 1] 쇼츠 차트: Source 페이지 딥다이브
            if "Shorts" in name:
                print(f"  ↳ 🕵️‍♂️ Deep dive for {len(chart_data)} Shorts...")
                for item in chart_data:
                    if item["Video_ID"]:
                        cnt = get_shorts_count_deep(driver, item["Video_ID"])
                        item["Views"] = cnt
            
            # [Case 2] Trending / MV 차트: API 조회 (가장 정확)
            elif "Trending" in name or "MV" in name:
                ids = [d["Video_ID"] for d in chart_data if d["Video_ID"]]
                if ids:
                    api_stats = get_views_from_api(ids)
                    for item in chart_data:
                        if item["Video_ID"] in api_stats:
                            item["Views"] = api_stats[item["Video_ID"]]
            
            # [Case 3] Songs 차트는 이미 스크래핑 단계에서 텍스트 파싱 완료함
            
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
