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
    
    # 4. Shorts (JS Shadow DOM 침투 방식으로 수정됨)
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

# ================= [수정됨] Shorts ID 추출 (JS 침투 방식) =================
def extract_shorts_ids_via_js(driver):
    # 1. 확실한 스크롤 (Lazy Loading 해결)
    last_height = driver.execute_script("return document.body.scrollHeight")
    for _ in range(30):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(0.5)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height
    time.sleep(2)

    # 2. 자바스크립트로 Shadow DOM 내부 강제 추출
    # (이 부분이 핵심 변경 사항입니다. 외부에서 못 보니까 내부에서 실행시킵니다.)
    script = """
    const rows = document.querySelectorAll('ytmc-entry-row');
    const ids = [];
    rows.forEach(row => {
        try {
            // Shadow DOM 내부에 있는 ytmc-video-lockup 찾기
            const lockup = row.querySelector('ytmc-video-lockup');
            if (lockup && lockup.shadowRoot) {
                // Shadow Root 내부의 링크(a#video-title-link) 찾기
                const link = lockup.shadowRoot.querySelector('a#video-title-link');
                if (link && link.href) {
                    // href에서 ID만 추출 (regex)
                    const match = link.href.match(/v=([a-zA-Z0-9_-]{11})/);
                    if (match && match[1]) {
                        ids.push(match[1]);
                    } else {
                        ids.push(""); // 매칭 실패시 빈값 유지 (순서 보존)
                    }
                } else {
                    ids.push("");
                }
            } else {
                ids.push("");
            }
        } catch (e) {
            ids.push("");
        }
    });
    return ids;
    """
    
    try:
        video_ids = driver.execute_script(script)
        # 빈 리스트가 올 경우를 대비해 필터링은 나중에 함
        return video_ids
    except Exception as e:
        print(f"JS extraction error: {e}")
        return []

# ================= Shorts 딥다이브 =================
def get_shorts_count_deep(driver, video_id):
    if not video_id: return 0
    url = f"https://www.youtube.com/source/{video_id}/shorts"
    try:
        driver.get(url)
        time.sleep(1.0) # 속도 최적화
        
        body_text = driver.page_source
        match = re.search(r'([\d,.]+[KMB]?)\s*(shorts|videos)', body_text, re.IGNORECASE)
        if match:
            return parse_count_strict(match.group(1))
            
        body_text_simple = driver.find_element(By.TAG_NAME, "body").text
        match2 = re.search(r'([\d,.]+[KMB]?)\s*(shorts|videos)', body_text_simple, re.IGNORECASE)
        if match2:
            return parse_count_strict(match2.group(1))
            
        return 0
    except: return 0

# ================= API 조회 (Trending) =================
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
    # CASE 1: Shorts (JS 침투 방식 적용)
    # ---------------------------------------------------------
    if is_shorts:
        print("  ↳ Shorts Mode: Extracting IDs via JS Injection...")
        video_ids = extract_shorts_ids_via_js(driver)
        
        # BS4로 껍데기 파싱
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        rows = soup.find_all('ytmc-entry-row')
        
        # ID 개수와 행 개수가 다를 경우 안전장치
        if not video_ids:
            print("  ⚠️ Warning: No IDs returned from JS. Trying fallback regex...")
            # 비상용: 페이지 소스 전체에서 ID 패턴 긁기 (순서 보장 안될 수 있지만 비상용)
            matches = re.findall(r'/watch\?v=([a-zA-Z0-9_-]{11})', driver.page_source)
            if len(matches) >= len(rows):
                video_ids = matches[:len(rows)]
        
        for idx, row in enumerate(rows):
            try:
                title = row.find('div', class_='title').get_text(strip=True)
                artist_tag = row.find('span', class_='artistName') or row.find('div', class_='subtitle')
                artist = artist_tag.get_text(strip=True) if artist_tag else ""
                
                vid = video_ids[idx] if (video_ids and idx < len(video_ids)) else ""
                
                data_list.append({
                    "Date": today, "Chart": chart_name, "Rank": idx+1,
                    "Title": title, "Artist": artist, "Video_ID": vid, "Views": 0
                })
            except: continue

    # ---------------------------------------------------------
    # CASE 2: MV / Songs / Trending (기존 완벽한 코드 유지)
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

# ================= 메인 실행 =================
if __name__ == "__main__":
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
                            
            elif "Shorts" in name:
                print(f"  ↳ Deep diving {len(chart_data)} shorts...")
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
        print("No webhook or data.")
