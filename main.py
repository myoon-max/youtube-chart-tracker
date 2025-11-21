import os
import re
import time
import json
import requests
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
    # 1. Trending (API 유지 - 건드리지 않음)
    "KR_Daily_Trending": "https://charts.youtube.com/charts/TrendingVideos/kr/RightNow",
    "US_Daily_Trending": "https://charts.youtube.com/charts/TrendingVideos/us/RightNow",
    
    # 2. Daily MV (Hidden Div 타격 - 건드리지 않음)
    "KR_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/kr/daily",
    "US_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/us/daily",

    # 3. Weekly (Visible Metric 타격 - 건드리지 않음)
    "KR_Weekly_Top_MV": "https://charts.youtube.com/charts/TopVideos/kr/weekly",
    "US_Weekly_Top_MV": "https://charts.youtube.com/charts/TopVideos/us/weekly",
    "KR_Weekly_Top_Songs": "https://charts.youtube.com/charts/TopSongs/kr/weekly",
    "US_Weekly_Top_Songs": "https://charts.youtube.com/charts/TopSongs/us/weekly",
    
    # 4. Shorts (Endpoint로 ID 추출 -> 페이지 접속해서 "82K Shorts" 텍스트 긁기)
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

def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--lang=en-US") 
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

# ================= Shorts ID 추출 (Endpoint 속성 사용) =================
def extract_shorts_ids_simple(driver):
    # 1. 스크롤 (데이터 로딩)
    last_height = driver.execute_script("return document.body.scrollHeight")
    for _ in range(30):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(0.5)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height
    time.sleep(2)

    # 2. 님께서 발견한 Endpoint 속성에서 ID 추출
    script = """
    const rows = document.querySelectorAll('ytmc-entry-row');
    const ids = [];
    rows.forEach(row => {
        if (row.offsetParent === null) return; // 보이는 행만

        const titleDiv = row.querySelector('#entity-title');
        let foundId = "";
        if (titleDiv) {
            const endpoint = titleDiv.getAttribute('endpoint');
            if (endpoint) {
                const match = endpoint.match(/watch\\?v=([a-zA-Z0-9_-]{11})/);
                if (match && match[1]) {
                    foundId = match[1];
                }
            }
        }
        ids.push(foundId);
    });
    return ids;
    """
    try:
        return driver.execute_script(script)
    except:
        return []

# ================= Shorts 딥다이브 (82K Shorts 긁기) =================
def get_shorts_creation_count(driver, video_id):
    if not video_id: return 0
    
    # 여기가 핵심: 해당 소스 페이지로 직접 이동
    url = f"https://www.youtube.com/source/{video_id}/shorts"
    try:
        driver.get(url)
        time.sleep(1.5) # 페이지 로딩 대기
        
        # 페이지 전체 텍스트에서 "82K Shorts" 같은 패턴 찾기
        body_text = driver.find_element(By.TAG_NAME, "body").text
        
        # Regex: 숫자(1.2K, 82K 등) + 공백 + Shorts (대소문자 무시)
        match = re.search(r'([\d,.]+[KMB]?)\s*Shorts', body_text, re.IGNORECASE)
        
        if match:
            return parse_count_strict(match.group(1))
            
        return 0
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
    
    # ---------------------------------------------------------
    # CASE 1: Shorts (Endpoint ID 추출 -> 개별 페이지 접속 후 "82K" 긁기)
    # ---------------------------------------------------------
    if is_shorts:
        print("  ↳ Shorts Mode: Extracting IDs & Diving for Creation Count...")
        video_ids = extract_shorts_ids_simple(driver)
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        rows = soup.find_all('ytmc-entry-row')
        
        for idx, row in enumerate(rows):
            try:
                title = row.find('div', class_='title').get_text(strip=True)
                artist_tag = row.find('span', class_='artistName') or row.find('div', class_='subtitle')
                artist = artist_tag.get_text(strip=True) if artist_tag else ""
                
                vid = video_ids[idx] if (video_ids and idx < len(video_ids)) else ""
                
                # [핵심] 여기서 바로 딥다이브 실행해서 "Shorts 개수"를 가져옴
                shorts_count = 0
                if vid:
                    # API 아님. 직접 접속해서 화면 숫자 긁어옴.
                    shorts_count = get_shorts_creation_count(driver, vid)
                
                data_list.append({
                    "Date": today, "Chart": chart_name, "Rank": idx+1,
                    "Title": title, "Artist": artist, "Video_ID": vid, "Views": shorts_count
                })
            except: continue

    # ---------------------------------------------------------
    # CASE 2: MV / Songs / Trending (기존 유지)
    # ---------------------------------------------------------
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
                    pass # API 후처리
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

# ================= 메인 실행 =================
if __name__ == "__main__":
    driver = get_driver()
    final_data = []
    
    for name, url in TARGET_URLS.items():
        try:
            chart_data = scrape_chart(name, url, driver)
            
            # [Trending만] API로 조회수 채우기 (Shorts는 위에서 이미 82K 긁었음)
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
        print("No webhook or data.")
