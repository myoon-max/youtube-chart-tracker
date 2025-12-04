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
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ==========================================
# [PART 1] 설정 및 URL 정의
# ==========================================

# ★★★ [주의] 사용자가 입력한 주소입니다. ★★★
# 이 주소(.../output=csv)는 시트 '다운로드'용입니다. 
# 데이터가 안 들어오면 앱스 스크립트 배포 주소(.../exec)인지 꼭 확인하세요.
WEBHOOK_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRR9sg-5znnm3vm2rpUkfkKE4GeYJnUmtW76-5BzjFNeaYnHZ_jLQe2oSCvQLYc861AEgLUs_nqXJgx/pub?gid=0&single=true&output=csv"

YOUTUBE_API_KEY = "AIzaSyDFFZNYygA85qp5p99qUG2Mh8Kl5qoLip4"

# 1. 유튜브 차트 (Selenium)
TARGET_URLS = {
    "KR_Daily_Trending": "https://charts.youtube.com/charts/TrendingVideos/kr/RightNow",
    "US_Daily_Trending": "https://charts.youtube.com/charts/TrendingVideos/us/RightNow",
    "KR_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/kr/daily",
    "US_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/us/daily",
    "KR_Weekly_Top_MV": "https://charts.youtube.com/charts/TopVideos/kr/weekly",
    "US_Weekly_Top_MV": "https://charts.youtube.com/charts/TopVideos/us/weekly",
    "KR_Weekly_Top_Songs": "https://charts.youtube.com/charts/TopSongs/kr/weekly",
    "US_Weekly_Top_Songs": "https://charts.youtube.com/charts/TopSongs/us/weekly",
    "KR_Daily_Top_Shorts": "https://charts.youtube.com/charts/TopShortsSongs/kr/daily",
    "US_Daily_Top_Shorts": "https://charts.youtube.com/charts/TopShortsSongs/us/daily"
}

# 2. 빌보드 차트 (Official)
BILLBOARD_URLS = {
    "Billboard_Hot100": "https://www.billboard.com/charts/hot-100/",
    "Billboard_200": "https://www.billboard.com/charts/billboard-200/",
    "Billboard_Global200": "https://www.billboard.com/charts/billboard-global-200/"
}

# 3. 기타 플랫폼 (Requests & Kworb)
EXTRA_URLS = {
    "Melon_Daily_Top100": "https://www.melon.com/chart/day/index.htm",
    "Genie_Daily_Top200": "https://www.genie.co.kr/chart/top200",
    "Spotify_Global_Daily": "https://kworb.net/spotify/country/global_daily.html",
    "Spotify_US_Daily": "https://kworb.net/spotify/country/us_daily.html",
    "Spotify_KR_Daily": "https://kworb.net/spotify/country/kr_daily.html"
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

def clean_text(text):
    return re.sub(r'\s+', ' ', text).strip()

def get_driver():
    chrome_options = Options()
    # [수정] 눈으로 확인하기 위해 헤드리스 잠시 끔 (잘 되면 다시 켜세요)
    # chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--lang=en-US")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36")
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

# ================= Shorts & API (유튜브용) =================
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

# ================= [PART 2] 크롤러 함수 모음 =================

# 1. 유튜브 차트 크롤러
def scrape_youtube_chart(chart_name, url, driver):
    print(f"🚀 Scraping YouTube: {chart_name}...")
    driver.get(url)
    time.sleep(5)
    
    data_list = []
    today = datetime.now().strftime("%Y-%m-%d")
    
    is_trending = "Trending" in chart_name
    is_shorts = "Shorts" in chart_name
    is_daily_mv = "Daily_Top_MV" in chart_name
    is_weekly = "Weekly" in chart_name
    
    # Shorts 로직
    if is_shorts:
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
                match = re.search(r'watch\?v=([a-zA-Z0-9_-]{11})', row_html)
                if match: vid = match.group(1)
                
                shorts_count = 0
                if vid: shorts_count = get_shorts_creation_count(driver, vid)
                
                data_list.append({
                    "Date": today, "Chart": chart_name, "Rank": idx+1,
                    "Title": title, "Artist": artist, "Video_ID": vid, "Views": shorts_count
                })
            except: continue

    # MV/Songs 로직
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

# 2. [수정됨] 빌보드 3종 통합 크롤러 (안전한 ID/구조 기반)
def scrape_billboard_official(driver, chart_key, url):
    print(f"🇺🇸 Scraping {chart_key} (Official/Selenium)...")
    data = []
    today = datetime.now().strftime("%Y-%m-%d")

    try:
        driver.get(url)
        last_height = driver.execute_script("return document.body.scrollHeight")
        for i in range(1, 5):
            driver.execute_script(f"window.scrollTo(0, {i * 1000});")
            time.sleep(0.5)
        
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3) 

        try:
            wait = WebDriverWait(driver, 15)
            wait.until(EC.presence_of_element_located((By.CLASS_NAME, "o-chart-results-list-row-container")))
        except:
            print(f"⚠️ {chart_key}: Timeout or Page Blocked.")
            return []

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        rows = soup.select('div.o-chart-results-list-row-container')
        print(f"   -> Found {len(rows)} raw rows.")

        for idx, row in enumerate(rows):
            try:
                rank = idx + 1
                
                # 빌보드에서 변하지 않는 ID 사용
                title_tag = row.select_one('h3#title-of-a-story')
                title = title_tag.get_text(strip=True) if title_tag else "Unknown"
                
                # 제목 바로 뒤 span 찾기
                artist = "Unknown"
                if title_tag:
                    artist_span = title_tag.find_next('span', class_='c-label')
                    if artist_span:
                        artist = artist_span.get_text(strip=True)
                
                if title == "Unknown": continue

                data.append({
                    "Date": today, "Chart": chart_key, "Rank": rank,
                    "Title": title, "Artist": artist, "Video_ID": "", "Views": 0
                })
            except: continue
            
        print(f"✅ {chart_key}: {len(data)} rows captured.")
    except Exception as e:
        print(f"❌ Billboard Error ({chart_key}): {e}")
    return data

# 3. 멜론 크롤러
def scrape_melon():
    print("🍈 Scraping Melon Daily...")
    url = EXTRA_URLS["Melon_Daily_Top100"]
    headers = {'User-Agent': 'Mozilla/5.0'}
    data = []
    today = datetime.now().strftime("%Y-%m-%d")

    try:
        res = requests.get(url, headers=headers)
        soup = BeautifulSoup(res.text, 'html.parser')
        rows = soup.select('tr.lst50, tr.lst100')
        for row in rows:
            try:
                rank = int(row.select_one('span.rank').text)
                title = row.select_one('div.ellipsis.rank01 > span > a').text.strip()
                artist = row.select_one('div.ellipsis.rank02 > a').text.strip()
                data.append({
                    "Date": today, "Chart": "Melon_Daily_Top100", "Rank": rank,
                    "Title": title, "Artist": artist, "Video_ID": "", "Views": 0
                })
            except: continue
        print(f"✅ Melon: {len(data)} rows")
    except Exception as e: print(f"❌ Melon Error: {e}")
    return data

# 4. 지니 크롤러
def scrape_genie():
    print("🧞 Scraping Genie Daily...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    data = []
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        for page in range(1, 3):
            res = requests.get(f"{EXTRA_URLS['Genie_Daily_Top200']}?pg={page}", headers=headers)
            soup = BeautifulSoup(res.text, 'html.parser')
            rows = soup.select('tbody > tr.list')
            for row in rows:
                try:
                    rank = int(row.select_one('td.number').text.split()[0])
                    title = row.select_one('a.title').text.strip()
                    artist = row.select_one('a.artist').text.strip()
                    data.append({
                        "Date": today, "Chart": "Genie_Daily_Top200", "Rank": rank,
                        "Title": title, "Artist": artist, "Video_ID": "", "Views": 0
                    })
                except: continue
        print(f"✅ Genie: {len(data)} rows")
    except Exception as e: print(f"❌ Genie Error: {e}")
    return data

# 5. Kworb Spotify 크롤러
def scrape_kworb(chart_key, url):
    print(f"🟢 Scraping {chart_key} via Kworb...")
    data = []
    chart_date = datetime.now().strftime("%Y-%m-%d")
    TARGET_HEADER_KEYWORD = "Streams"

    try:
        res = requests.get(url)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        title_span = soup.select_one('span.pagetitle')
        if title_span:
            title_text = title_span.get_text()
            date_match = re.search(r'(\d{4})/(\d{2})/(\d{2})', title_text)
            if date_match:
                chart_date = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
                print(f"   -> Date: {chart_date}")

        table = soup.find('table')
        if not table: return []

        headers = []
        thead = table.find('thead')
        if thead:
            headers = [th.get_text(strip=True) for th in thead.find_all('th')]
        else:
            first_row = table.find('tr')
            headers = [td.get_text(strip=True) for td in first_row.find_all(['td', 'th'])]

        target_idx = -1
        title_idx = -1
        for i, h in enumerate(headers):
            if "Artist" in h or "Title" in h: title_idx = i
            if TARGET_HEADER_KEYWORD in h and "+" not in h:
                target_idx = i
                break
        
        if target_idx == -1: target_idx = 6 
        if title_idx == -1: title_idx = 2

        rows = soup.select('tbody > tr')
        for row in rows:
            cols = row.find_all('td')
            if not cols: continue
            try:
                rank_txt = cols[0].get_text(strip=True)
                if not rank_txt.isdigit(): continue
                rank = int(rank_txt)

                full_text = clean_text(cols[title_idx].get_text())
                if " - " in full_text:
                    parts = full_text.split(" - ", 1)
                    artist = parts[0].strip()
                    title = parts[1].strip()
                else:
                    artist = "Unknown"
                    title = full_text

                val_raw = cols[target_idx].get_text(strip=True)
                val_clean = re.sub(r'[^\d]', '', val_raw)
                final_val = int(val_clean) if val_clean else 0

                data.append({
                    "Date": chart_date, "Chart": chart_key, "Rank": rank,
                    "Title": title, "Artist": artist, "Video_ID": "", "Views": final_val
                })
            except: continue
        print(f"✅ {chart_key}: {len(data)} rows")
    except Exception as e: print(f"❌ Kworb Error ({chart_key}): {e}")
    return data

# ==========================================
# [PART 3] 메인 실행 (Debug Mode)
# ==========================================
if __name__ == "__main__":
    driver = None
    final_data = [] 

    try:
        print("=== [Start] MusicDeal Crawler (Final) ===")
        
        # 1. Selenium (YouTube/Billboard)
        try:
            driver = get_driver()
            
            # YouTube
            for name, url in TARGET_URLS.items():
                print(f"▶️ YouTube: {name}")
                chart_data = scrape_youtube_chart(name, url, driver)
                # 조회수 보정
                if "Trending" in name:
                    ids = [d["Video_ID"] for d in chart_data if d["Video_ID"]]
                    if ids:
                        api_stats = get_views_from_api(ids)
                        for item in chart_data:
                            if item["Video_ID"] in api_stats:
                                item["Views"] = api_stats[item["Video_ID"]]
                final_data.extend(chart_data)
            
            # Billboard
            print("\n▶️ Billboard...")
            for b_name, b_url in BILLBOARD_URLS.items():
                b_data = scrape_billboard_official(driver, b_name, b_url)
                final_data.extend(b_data)

        except Exception as sel_e:
            print(f"🔥 Selenium Error: {sel_e}")
        finally:
            if driver: driver.quit()

        # 2. Requests (Melon/Genie/Kworb)
        print("\n▶️ Domestic & Kworb...")
        final_data.extend(scrape_melon())
        final_data.extend(scrape_genie())
        for key, url in EXTRA_URLS.items():
            final_data.extend(scrape_kworb(key, url))

        # 3. 데이터 전송 (강제 전송 모드)
        print(f"\n📊 Total Data: {len(final_data)} rows")
        
        if len(final_data) > 0:
            print(f"🚀 Sending to: {WEBHOOK_URL[:40]}...")
            
            # 청크 단위 전송
            chunk_size = 3000
            for i in range(0, len(final_data), chunk_size):
                chunk = final_data[i:i+chunk_size]
                try:
                    response = requests.post(https://script.google.com/macros/s/AKfycbyFm0Xu2BY3T_JcNgQqQssOhY1hJ-UH1A-GW2hhRLT-jDkgevFL74Bl1iEXUFPW1pleBw/exec, json=chunk)
                    print(f"   -> Chunk {i//chunk_size + 1}: Code {response.status_code}")
                    print(f"      Response: {response.text[:100]}") # 에러 메시지 확인용
                except Exception as e:
                    print(f"❌ Send Error: {e}")
                time.sleep(1)
            print("✨ Done.")
        else:
            print("⚠️ 0 rows collected.")

    except Exception as main_e:
        print("🔥 Fatal Error.")
        print(traceback.format_exc())
