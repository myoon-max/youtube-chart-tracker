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
TARGET_URLS = {
    "KR_Daily_Trending": "https://charts.youtube.com/charts/Trending/kr/global",
    "KR_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/kr/daily",
    "KR_Weekly_Top_MV": "https://charts.youtube.com/charts/TopVideos/kr/weekly",
    "KR_Weekly_Top_Songs": "https://charts.youtube.com/charts/TopSongs/kr/weekly",
    "US_Daily_Trending": "https://charts.youtube.com/charts/Trending/us/global",
    "US_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/us/daily",
    "US_Weekly_Top_MV": "https://charts.youtube.com/charts/TopVideos/us/weekly",
    "US_Weekly_Top_Songs": "https://charts.youtube.com/charts/TopSongs/us/weekly"
}

# ================= 숫자 변환기 (강력해짐) =================
def parse_view_count(text):
    if not text: return 0
    # 텍스트 정제 (1.5M views -> 1.5M)
    clean_text = text.lower().replace('views', '').replace('조회수', '').strip()
    
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
            
        # 쉼표 제거 후 숫자 변환
        return int(float(clean_text.replace(',', '')) * multiplier)
    except:
        return 0

# ================= 크롤링 로직 =================
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    # 화면을 크게 띄워야 데이터가 안 숨겨짐
    chrome_options.add_argument("--window-size=1920,1080") 
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def scrape_chart(driver, chart_name, url):
    print(f"Scraping {chart_name}...")
    driver.get(url)
    
    # [수정] 인급동(Trending)은 로딩이 느리므로 더 오래 대기
    wait_time = 15 if "Trending" in chart_name else 8
    time.sleep(wait_time)
    
    # 스크롤 내리기 (데이터 로딩 유도)
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(3)
    
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    rows = soup.find_all('ytmc-entry-row')
    
    # 만약 ytmc-entry-row를 못 찾았으면 한 번 더 대기 (Trending 대비)
    if not rows:
        print(f"⚠️ No rows found immediately for {chart_name}. Waiting more...")
        time.sleep(5)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        rows = soup.find_all('ytmc-entry-row')
    
    data = []
    today = datetime.now().strftime("%Y-%m-%d")
    rank = 1
    
    for row in rows:
        try:
            # 제목
            title_div = row.find('div', class_='title')
            title = title_div.get_text(strip=True) if title_div else "Unknown"
            
            # 아티스트
            artist_span = row.find('span', class_='artistName')
            if not artist_span: artist_span = row.find('div', class_='subtitle')
            artist = artist_span.get_text(strip=True) if artist_span else ""
            
            # [핵심 수정] 조회수 찾기 (정규식 사용)
            # div class='views'가 없을 수도 있으니, 행 전체 텍스트에서 패턴을 찾음
            row_text = row.get_text(separator=' ', strip=True)
            
            # 패턴: 숫자 + (점 + 숫자) + (M/K/B 또는 쉼표 포함 숫자)
            # 예: 1.5M, 300K, 1,234,567
            # 단, 순위(1, 2...)는 제외해야 함. 보통 조회수는 M/K가 붙거나 숫자가 큼.
            
            # 1. 우선 class='views'나 'metric' 시도
            views_text = ""
            views_div = row.find('div', class_='views')
            if not views_div: views_div = row.find('div', class_='metric')
            
            if views_div:
                views_text = views_div.get_text(strip=True)
            else:
                # 2. 없으면 텍스트 패턴 검색 (M, K, B가 붙은 숫자 찾기)
                match = re.search(r'([\d,.]+[M|K|B])', row_text, re.IGNORECASE)
                if match:
                    views_text = match.group(1)
                else:
                    # 3. 그것도 없으면 그냥 숫자 중에서 가장 긴 것(보통 조회수) 찾기
                    # (위험하지만 최후의 수단)
                    pass 
            
            views_num = parse_view_count(views_text)
            
            # 썸네일 ID
            img = row.find('img')
            vid = ""
            if img and 'src' in img.attrs and '/vi/' in img['src']:
                vid = img['src'].split('/vi/')[1].split('/')[0]
                
            data.append({
                "Date": today,
                "Chart": chart_name,
                "Rank": rank,
                "Title": title,
                "Artist": artist,
                "Video_ID": vid,
                "Views": views_num
            })
            rank += 1
        except Exception as e: continue
            
    return data

# ================= 실행 및 전송 =================
if __name__ == "__main__":
    driver = get_driver()
    all_data = []
    
    for name, url in TARGET_URLS.items():
        try:
            chart_data = scrape_chart(driver, name, url)
            print(f"✅ {name}: {len(chart_data)} rows") # 로그 확인용
            all_data.extend(chart_data)
        except Exception as e:
            print(f"Error on {name}: {e}")
            
    driver.quit()
    
    webhook_url = os.environ.get("APPS_SCRIPT_WEBHOOK")
    
    if all_data and webhook_url:
        print(f"Total {len(all_data)} rows collected. Sending to Google Sheets...")
        try:
            response = requests.post(webhook_url, json=all_data)
            print(f"Done! Response: {response.text}")
        except Exception as e:
            print(f"Failed to send: {e}")
    else:
        print(f"Error: Data count {len(all_data)}, Webhook set: {bool(webhook_url)}")
