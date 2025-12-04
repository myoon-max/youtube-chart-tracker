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
# [PART 1] 설정 (건드리지 마세요)
# ==========================================

# 1. 데이터 보낼 주소 (대표님이 주신 주소 적용됨)
# ※ 주의: 이 주소가 '.../exec'로 끝나는 앱스스크립트 주소가 아니면 데이터가 안 쌓일 수 있습니다.
# 일단 주신 주소 그대로 넣었습니다.
WEBHOOK_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRR9sg-5znnm3vm2rpUkfkKE4GeYJnUmtW76-5BzjFNeaYnHZ_jLQe2oSCvQLYc861AEgLUs_nqXJgx/pub?gid=0&single=true&output=csv"

# 2. 유튜브 API 키
YOUTUBE_API_KEY = "AIzaSyDFFZNYygA85qp5p99qUG2Mh8Kl5qoLip4"

# 3. 크롤링 대상 URL 모음
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

BILLBOARD_URLS = {
    "Billboard_Hot100": "https://www.billboard.com/charts/hot-100/",
    "Billboard_200": "https://www.billboard.com/charts/billboard-200/",
    "Billboard_Global200": "https://www.billboard.com/charts/billboard-global-200/"
}

EXTRA_URLS = {
    "Melon_Daily_Top100": "https://www.melon.com/chart/day/index.htm",
    "Genie_Daily_Top200": "https://www.genie.co.kr/chart/top200",
    "Spotify_Global_Daily": "https://kworb.net/spotify/country/global_daily.html",
    "Spotify_US_Daily": "https://kworb.net/spotify/country/us_daily.html",
    "Spotify_KR_Daily": "https://kworb.net/spotify/country/kr_daily.html"
}

# ================= 유틸리티 함수 =================
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
    # 화면 안 뜨게 하려면 아래 줄 주석 해제 (지금은 에러 확인용으로 띄움)
    # chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--lang=en-US")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36")
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

# ================= 유튜브 관련 함수 =================
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

# ================= [핵심] 크롤러 함수들 =================

# 1. 유튜브 크롤러
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

# 2. [최종 수정] 빌보드 안전장치 강화 크롤러 (안 되면 3번 찌르는 로직)
def scrape_billboard_official(driver, chart_key, url):
    print(f"🇺🇸 [SafeMode] Scraping {chart_key}...")
    max_retries = 2
    for attempt in range(max_retries):
        try:
            driver.get(url)
            print(f"   -> Loading (Attempt {attempt+1})...")
            
            # 천천히 스크롤 내려서 데이터 로딩 유도
            for i in range(1, 11):
                driver.execute_script(f"window.scrollTo(0, document.body.scrollHeight * {i/10});")
                time.sleep(0.5)
            time.sleep(3)

            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "o-chart-results-list-row-container"))
                )
            except:
                print("   ⚠️ Timeout: Container not found. Retrying...")
                if attempt < max_retries - 1: continue
                return []

            soup = BeautifulSoup(driver.page_source, 'html.parser')
            rows = soup.select('div.o-chart-results-list-row-container')
            print(f"   -> Found {len(rows)} row containers.")

            if len(rows) == 0:
                print("   ⚠️ 0 rows. Refreshing page...")
                continue 

            data = []
            today = datetime.now().strftime("%Y-%m-%d")

            for idx, row in enumerate(rows):
                try:
                    # 1. 순위
                    rank = idx + 1
                    try:
                        rank_tag = row.select_one('span.c-label.a-font-primary-bold-l')
                        if rank_tag and rank_tag.text.strip().isdigit():
                            rank = int(rank_tag.text.strip())
                    except: pass

                    # 2. 제목 (3중 안전장치)
                    title = "Unknown"
                    title_tag = row.select_one('h3.c-title') # 1순위: 클래스
                    if not title_tag: title_tag = row.select_one('h3#title-of-a-story') # 2순위: ID
                    if not title_tag: title_tag = row.select_one('h3') # 3순위: 그냥 태그
                    
                    if title_tag:
                        title = title_tag.get_text(strip=True)

                    # 3. 가수 (구조 기반 검색)
                    artist = "Unknown"
                    if title_tag:
                        parent_li = title_tag.find_parent('li')
                        if parent_li:
                            artist_tag = parent_li.select_one('span.c-label.a-no-trucate')
                            if artist_tag:
                                artist = artist_tag.get_text(strip=True)
                            else:
                                full_text = parent_li.get_text(strip=True)
                                if title in full_text:
                                    remain = full_text.replace(title, "").strip()
                                    if len(remain) > 1: artist = remain

                    if title == "Unknown": continue

                    data.append({
                        "Date": today, "Chart": chart_key, "Rank": rank,
                        "Title": title, "Artist": artist, "Video_ID": "", "Views": 0
                    })
                except: continue
            
            if len(data) > 0:
                print(f"✅ {chart_key}: Captured {len(data)} rows.")
                return data

        except Exception as e:
            print(f"❌ Error on attempt {attempt+1}: {e}")
            time.sleep(3)

    return []

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

# 5. Kworb 크롤러 (날짜 강제 Today)
def scrape_kworb(chart_key, url):
    print(f"🟢 Scraping {chart_key}...")
    data = []
    # 대표님 요청: 무조건 오늘 날짜로 고정
    chart_date = datetime.now().strftime("%Y-%m-%d")
    TARGET_HEADER_KEYWORD = "Streams"

    try:
        res = requests.get(url)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
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
                    "Date": chart_date, # 오늘 날짜 강제
                    "Chart": chart_key,
                    "Rank": rank,
                    "Title": title,
                    "Artist": artist,
                    "Video_ID": "",
                    "Views": final_val
                })
            except: continue
        print(f"✅ {chart_key}: {len(data)} rows")
    except Exception as e: print(f"❌ Kworb Error ({chart_key}): {e}")
    return data

# ==========================================
# [PART 3] 실행 (여기서부터 돕니다)
# ==========================================
if __name__ == "__main__":
    driver = None
    final_data = [] 

    try:
        print("=== [MusicDeal] 통합 크롤러 시작 (빌보드 수정판) ===")
        
        # 1. 브라우저 켜서 유튜브/빌보드 수집
        try:
            driver = get_driver()
            
            # YouTube
            for name, url in TARGET_URLS.items():
                chart_data = scrape_youtube_chart(name, url, driver)
                # 조회수 API 보정
                if "Trending" in name:
                    ids = [d["Video_ID"] for d in chart_data if d["Video_ID"]]
                    if ids:
                        api_stats = get_views_from_api(ids)
                        for item in chart_data:
                            if item["Video_ID"] in api_stats:
                                item["Views"] = api_stats[item["Video_ID"]]
                final_data.extend(chart_data)
            
            # Billboard (안전장치 적용됨)
            print("\n>>> 빌보드 차트 수집 시작...")
            for b_name, b_url in BILLBOARD_URLS.items():
                b_data = scrape_billboard_official(driver, b_name, b_url)
                final_data.extend(b_data)

        except Exception as sel_e:
            print(f"🔥 브라우저 에러: {sel_e}")
        finally:
            if driver: driver.quit()

        # 2. 국내 차트 및 Kworb (Requests 방식)
        print("\n>>> 국내 및 기타 차트 수집...")
        final_data.extend(scrape_melon())
        final_data.extend(scrape_genie())
        for key, url in EXTRA_URLS.items():
            final_data.extend(scrape_kworb(key, url))

        # 3. 데이터 전송 (웹훅)
        print(f"\n📊 총 수집된 데이터: {len(final_data)} 줄")
        
        if len(final_data) > 0:
            print(f"🚀 데이터 전송 시작: {WEBHOOK_URL[:40]}...")
            
            chunk_size = 3000
            for i in range(0, len(final_data), chunk_size):
                chunk = final_data[i:i+chunk_size]
                try:
                    # [주의] 여기서 에러나면 주소가 'exec'가 맞는지 확인 필요
                    response = requests.post(WEBHOOK_URL, json=chunk)
                    print(f"   -> 묶음 {i//chunk_size + 1} 전송결과: {response.status_code}")
                    if response.status_code not in [200, 201]:
                        print(f"      [경고] 전송 실패 가능성 있음. 응답: {response.text[:100]}")
                except Exception as e:
                    print(f"❌ 전송 중 에러: {e}")
                time.sleep(1)
            print("✨ 모든 작업 완료.")
        else:
            print("⚠️ 수집된 데이터가 없습니다.")

    except Exception as main_e:
        print("🔥 치명적 오류 발생.")
        print(traceback.format_exc())
