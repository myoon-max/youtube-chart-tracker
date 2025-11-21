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
    "KR_Daily_Trending": "https://charts.youtube.com/charts/TrendingVideos/kr/RightNow",
    "KR_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/kr/daily",
    "KR_Weekly_Top_MV": "https://charts.youtube.com/charts/TopVideos/kr/weekly",
    "KR_Weekly_Top_Songs": "https://charts.youtube.com/charts/TopSongs/kr/weekly",
    "US_Daily_Trending": "https://charts.youtube.com/charts/TrendingVideos/us/RightNow",
    "US_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/us/daily",
    "US_Weekly_Top_MV": "https://charts.youtube.com/charts/TopVideos/us/weekly",
    "US_Weekly_Top_Songs": "https://charts.youtube.com/charts/TopSongs/us/weekly",
    # 쇼츠 차트 (이제 여기서는 조회수 말고 '개수'를 캡니다)
    "KR_Daily_Top_Shorts": "https://charts.youtube.com/charts/TopShortsSongs/kr/daily",
    "US_Daily_Top_Shorts": "https://charts.youtube.com/charts/TopShortsSongs/us/daily"
}

# ================= 숫자 변환기 =================
def parse_count(text):
    if not text: return 0
    text = str(text).lower().replace('shorts', '').replace('videos', '').replace('조회수', '').strip()
    try:
        multiplier = 1
        if 'm' in text: multiplier = 1_000_000
        elif 'k' in text: multiplier = 1_000
        elif 'b' in text: multiplier = 1_000_000_000
        
        # 숫자와 점(.)만 남기고 변환 (콤마 제거)
        clean_text = re.sub(r'[^\d.]', '', text)
        if not clean_text: return 0
        
        return int(float(clean_text) * multiplier)
    except: return 0

# ================= [핵심] 쇼츠 생성 개수 크롤링 (Deep Dive) =================
def get_shorts_creation_count(driver, video_id):
    if not video_id: return 0
    
    # 지름길 URL (Source Page)
    target_url = f"https://www.youtube.com/source/{video_id}/shorts"
    
    try:
        driver.get(target_url)
        # 로딩 대기 (빠르게 훑기 위해 짧게)
        time.sleep(2) 
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # 패턴: "82K shorts", "1.5M videos", "321 shorts" 등을 찾음
        # 보통 헤더나 메타데이터 쪽에 있음. 전체 텍스트에서 패턴 검색이 가장 확실함.
        body_text = soup.get_text(separator=' ', strip=True)
        
        # 패턴 1: "82K shorts" 형태
        match = re.search(r'([\d,.]+[M|K|B]?)\s*shorts', body_text, re.IGNORECASE)
        if match:
            return parse_count(match.group(1))
            
        # 패턴 2: "123 videos" 형태 (가끔 이렇게 뜸)
        match2 = re.search(r'([\d,.]+[M|K|B]?)\s*videos', body_text, re.IGNORECASE)
        if match2:
            return parse_count(match2.group(1))

        return 0
    except:
        return 0

# ================= 크롤링 로직 =================
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--lang=en-US") 
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def scrape_chart(driver, chart_name, url):
    print(f"🚀 Scraping {chart_name}...")
    driver.get(url)
    time.sleep(10)
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(5)
    
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    rows = soup.find_all('ytmc-entry-row')
    
    # 재시도
    if not rows:
        time.sleep(5)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        rows = soup.find_all('ytmc-entry-row')
    
    data = []
    today = datetime.now().strftime("%Y-%m-%d")
    rank = 1
    
    # 쇼츠 차트인지 확인 (쇼츠 차트면 '개수' 캐러 가야 함)
    is_shorts_chart = "Shorts" in chart_name
    
    for row in rows:
        try:
            title = row.find('div', class_='title').get_text(strip=True)
            
            artist_tag = row.find('span', class_='artistName')
            if not artist_tag: artist_tag = row.find('div', class_='subtitle')
            artist = artist_tag.get_text(strip=True) if artist_tag else ""
            
            # Video ID 추출 (썸네일에서)
            img = row.find('img')
            vid = ""
            if img and 'src' in img.attrs and '/vi/' in img['src']:
                vid = img['src'].split('/vi/')[1].split('/')[0]
            
            final_value = 0
            
            # ==========================================
            # CASE 1: 쇼츠 차트다? -> Source Page로 잠입
            # ==========================================
            if is_shorts_chart and vid:
                # 여기서 바로 이동하면 루프가 깨지니까, 일단 ID만 저장하고 나중에 한꺼번에 돔
                # 하지만 코드 단순화를 위해 일단 여기서 저장해두고 메인 루프에서 처리 권장.
                # 여기서는 0으로 두고, vid를 확실히 챙김.
                pass 

            # ==========================================
            # CASE 2: 일반/Top Songs 차트다? -> 콤마 숫자 사냥
            # ==========================================
            else:
                all_divs = row.find_all('div')
                views_text = ""
                
                # 뒤에서부터 훑으면서 "4,842,974" 같은 패턴 찾기
                for div in reversed(all_divs):
                    txt = div.get_text(strip=True)
                    # 콤마가 포함된 숫자 (예: 1,234 / 1,234,567)
                    # 랭크(1~100)나 주간(1~500)과 구분하기 위해 '콤마' 필수 조건
                    if re.match(r'^\d{1,3}(,\d{3})+$', txt):
                        views_text = txt
                        break
                    # 혹시 1.5M 같은거일수도 있으니
                    if re.search(r'\d+(\.\d+)?[MKB]', txt, re.IGNORECASE):
                        views_text = txt
                        # 우선순위 낮음 (break 안함)
                
                final_value = parse_count(views_text)

            data.append({
                "Date": today,
                "Chart": chart_name,
                "Rank": rank,
                "Title": title,
                "Artist": artist,
                "Video_ID": vid,
                "Views": final_value # 쇼츠는 나중에 업데이트
            })
            rank += 1
        except: continue
        
    return data

# ================= 메인 실행 =================
if __name__ == "__main__":
    driver = get_driver()
    final_data = []
    
    for name, url in TARGET_URLS.items():
        try:
            # 1. 1차 수집 (목록 확보)
            chart_data = scrape_chart(driver, name, url)
            
            # 2. [심화] 쇼츠 차트면 -> 각 ID마다 소스 페이지 방문 (S급 미션 수행)
            if "Shorts" in name:
                print(f"  ↳ 🕵️‍♂️ Entering Deep Dive for {len(chart_data)} Shorts...")
                for item in chart_data:
                    if item["Video_ID"]:
                        # 각 영상마다 페이지 이동 (시간 좀 걸림)
                        count = get_shorts_creation_count(driver, item["Video_ID"])
                        item["Views"] = count # 조회수 대신 '개수' 저장
                        # print(f"    - {item['Title']}: {count} Shorts") # 로그 너무 많으면 주석
            
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
