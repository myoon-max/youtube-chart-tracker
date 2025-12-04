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

# 2. 빌보드 차트 (Selenium - Official)
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
    chrome_options.add_argument("--headless=new") # 헤드리스 모드 유지
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--lang=en-US")
    # 차단 방지를 위한 User-Agent 설정
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

# 2. [수정됨] 빌보드 3종 통합 크롤러 (Selenium + 스크린샷 기반 클래스 수정)
def scrape_billboard_official(driver, chart_key, url):
    print(f"🇺🇸 Scraping {chart_key} (Official/Selenium)...")
    data = []
    today = datetime.now().strftime("%Y-%m-%d")

    try:
        driver.get(url)
        # [중요] 스크롤 로직 추가 (빌보드는 스크롤 안하면 데이터 로딩 안됨)
        last_height = driver.execute_script("return document.body.scrollHeight")
        # 조금씩 내리면서 로딩 유도
        for i in range(1, 5):
            driver.execute_script(f"window.scrollTo(0, {i * 1000});")
            time.sleep(1)
        
        # 마지막으로 맨 아래로
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3) 

        # 차트 행 컨테이너 대기
        try:
            wait = WebDriverWait(driver, 15)
            wait.until(EC.presence_of_element_located((By.CLASS_NAME, "o-chart-results-list-row-container")))
        except:
            print(f"⚠️ {chart_key}: Timeout or Page Blocked.")
            return []

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # [수정] 스크린샷 1번의 컨테이너 클래스 사용
        rows = soup.select('div.o-chart-results-list-row-container')
        
        print(f"   -> Found {len(rows)} raw rows.")

        for idx, row in enumerate(rows):
            try:
                # 1. 순위 (Rank)
                # 스크린샷 1번: 1등 '2'는 span.c-label.a-font-primary-bold-l 안에 있음
                rank_elem = row.select_one('span.c-label.a-font-primary-bold-l')
                if rank_elem:
                    rank_text = rank_elem.get_text(strip=True)
                    rank = int(rank_text) if rank_text.isdigit() else (idx + 1)
                else:
                    rank = idx + 1
                
                # 2. 제목 (Title) 
                # 스크린샷 4번: h3 태그에 'c-title' 클래스 확인됨 (ID 대신 클래스 사용)
                title_tag = row.select_one('h3.c-title')
                title = title_tag.get_text(strip=True) if title_tag else "Unknown"
                
                # 3. 가수 (Artist)
                # 스크린샷 4번: h3 바로 아래 span.c-label.a-no-trucate 가 아티스트임
                artist = "Unknown"
                if title_tag:
                    # h3 바로 다음에 오는 형제 요소 찾기 (혹은 같은 li 안의 span 찾기)
                    # 구조상: li > h3 ... span
                    # title_tag의 부모 li를 찾고 그 안에서 c-label.a-no-trucate 찾기
                    parent_li = title_tag.find_parent('li')
                    if parent_li:
                        # a-no-trucate 클래스가 아티스트명에 붙어있음 (스크린샷 4)
                        artist_span = parent_li.select_one('span.c-label.a-no-trucate')
                        if artist_span:
                            artist = artist_span.get_text(strip=True)

                data.append({
                    "Date": today, "Chart": chart_key, "Rank": rank,
                    "Title": title, "Artist": artist, "Video_ID": "", "Views": 0
                })
            except: continue
            
        print(f"✅ {chart_key}: {len(data)} rows captured.")
    except Exception as e:
        print(f"❌ Billboard Error ({chart_key}): {e}")
    return data

# 3. 멜론 크롤러 (Requests)
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

# 4. 지니 크롤러 (Requests)
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

# 5. [수정됨] Kworb Spotify 크롤러 (실제 날짜 파싱 적용)
def scrape_kworb(chart_key, url):
    print(f"🟢 Scraping {chart_key} via Kworb (Parsing real date)...")
    data = []
    
    # 기본값은 오늘 (파싱 실패 대비)
    chart_date = datetime.now().strftime("%Y-%m-%d")
    TARGET_HEADER_KEYWORD = "Streams"

    try:
        res = requests.get(url)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # [핵심 수정] 페이지 상단의 날짜(2025/12/02) 파싱
        # 스크린샷에 있던 <span class="pagetitle"> 타겟팅
        title_span = soup.select_one('span.pagetitle')
        if title_span:
            title_text = title_span.get_text()
            # YYYY/MM/DD 형식 추출
            date_match = re.search(r'(\d{4})/(\d{2})/(\d{2})', title_text)
            if date_match:
                chart_date = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
                print(f"   -> Detected Chart Date: {chart_date}")
            else:
                print(f"   -> ⚠️ Date parsing failed, using today: {chart_date}")

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
        
        if target_idx == -1: 
            target_idx = 6 
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
                    "Date": chart_date, # [수정] 실제 파싱된 날짜 사용
                    "Chart": chart_key,
                    "Rank": rank,
                    "Title": title,
                    "Artist": artist,
                    "Video_ID": "",
                    "Views": final_val
                })
            except: continue
        print(f"✅ {chart_key}: {len(data)} rows (Date: {chart_date})")
    except Exception as e: print(f"❌ Kworb Error ({chart_key}): {e}")
    return data

# ==========================================
# [PART 3] 메인 실행 (Main Execution)
# ==========================================
if __name__ == "__main__":
    driver = None
    final_data = [] 

    try:
        print("=== [Start] MusicDeal Crawler ===")
        
        # 1. Selenium 기반 크롤링 (YouTube + Billboard)
        try:
            driver = get_driver()
            
            # (1) YouTube Scraping
            for name, url in TARGET_URLS.items():
                try:
                    chart_data = scrape_youtube_chart(name, url, driver)
                    if "Trending" in name:
                        ids = [d["Video_ID"] for d in chart_data if d["Video_ID"]]
                        if ids:
                            api_stats = get_views_from_api(ids)
                            for item in chart_data:
                                if item["Video_ID"] in api_stats:
                                    item["Views"] = api_stats[item["Video_ID"]]
                    final_data.extend(chart_data)
                except Exception as e:
                    print(f"⚠️ Error on YouTube {name}: {e}")
            
            # (2) Billboard Scraping (Official)
            print("\n>>> Starting Billboard Charts...")
            for b_name, b_url in BILLBOARD_URLS.items():
                final_data.extend(scrape_billboard_official(driver, b_name, b_url))

        except Exception as sel_e:
            print(f"🔥 Selenium Process Error: {sel_e}")
            print(traceback.format_exc())
        finally:
            if driver: driver.quit()

        # 2. Requests 기반 크롤링 (Melon, Genie, Spotify/Kworb)
        print("\n=== [Domestic & Spotify Charts] ===")
        final_data.extend(scrape_melon())
        final_data.extend(scrape_genie())
        
        for key, url in EXTRA_URLS.items():
            final_data.extend(scrape_kworb(key, url))

        # 3. 데이터 전송
        print(f"\n=== [Sending Data] Total {len(final_data)} rows ===")
        # Apps Script 웹훅 URL 환경변수 (또는 직접 입력)
        webhook = os.environ.get("APPS_SCRIPT_WEBHOOK")
        
        if final_data and webhook:
            chunk_size = 4000
            for i in range(0, len(final_data), chunk_size):
                chunk = final_data[i:i+chunk_size]
                try:
                    requests.post(webhook, json=chunk)
                    print(f"  -> Chunk {i//chunk_size + 1} sent.")
                    time.sleep(1)
                except Exception as e:
                    print(f"❌ Send Error: {e}")
            print("✨ All Scrapers Completed Successfully!")
        else:
            print("⚠️ No webhook URL found or empty data. Check 'APPS_SCRIPT_WEBHOOK' env var.")

    except Exception as main_e:
        print("🔥 FATAL ERROR: Script crashed.")
        print(traceback.format_exc())
