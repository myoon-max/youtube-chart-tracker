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

# ================= 숫자 변환기 (1.2M -> 1200000) =================
def parse_view_count(text):
    if not text: return 0
    # "1.5M views" -> "1.5M"
    text = text.lower().replace('views', '').replace('조회수', '').strip()
    try:
        if 'm' in text:
            return int(float(text.replace('m', '')) * 1_000_000)
        elif 'k' in text:
            return int(float(text.replace('k', '')) * 1_000)
        elif 'b' in text: # Billion
            return int(float(text.replace('b', '')) * 1_000_000_000)
        else:
            # 쉼표 제거 후 정수 변환
            return int(text.replace(',', ''))
    except:
        return 0

# ================= 크롤링 로직 =================
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    # 브라우저 크기를 키워야 데이터가 잘 보임
    chrome_options.add_argument("--window-size=1920,1080") 
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def scrape_chart(driver, chart_name, url):
    print(f"Scraping {chart_name}...")
    driver.get(url)
    time.sleep(7) # 로딩 시간 넉넉히
    
    # 스크롤 끝까지 내리기 (데이터 로딩 유도)
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(3)
    
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    rows = soup.find_all('ytmc-entry-row')
    
    data = []
    today = datetime.now().strftime("%Y-%m-%d")
    rank = 1
    
    for row in rows:
        try:
            title_div = row.find('div', class_='title')
            title = title_div.get_text(strip=True) if title_div else "Unknown"
            
            artist_span = row.find('span', class_='artistName')
            if not artist_span: artist_span = row.find('div', class_='subtitle')
            artist = artist_span.get_text(strip=True) if artist_span else ""
            
            # [수정] 조회수 태그 찾는 법 강화
            # class="views" 또는 class="metric" 등 여러 가능성 열어둠
            views_div = row.find('div', class_='views')
            if not views_div:
                 # 만약 views 클래스가 없으면 entry-row 안의 마지막 div를 의심해봄
                 divs = row.find_all('div')
                 if divs: views_div = divs[-1]
            
            views_text = views_div.get_text(strip=True) if views_div else "0"
            
            # 숫자 변환 함수 적용
            views_num = parse_view_count(views_text)
            
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
                "Views": views_num # 숫자형으로 저장
            })
            rank += 1
        except Exception as e: 
            print(f"Row Error: {e}")
            continue
            
    return data

# ================= 실행 및 전송 =================
if __name__ == "__main__":
    driver = get_driver()
    all_data = []
    
    for name, url in TARGET_URLS.items():
        try:
            chart_data = scrape_chart(driver, name, url)
            all_data.extend(chart_data)
            print(f"✅ {name}: {len(chart_data)} rows")
        except Exception as e:
            print(f"Error on {name}: {e}")
            
    driver.quit()
    
    webhook_url = os.environ.get("APPS_SCRIPT_WEBHOOK")
    
    if all_data and webhook_url:
        print(f"Total {len(all_data)} rows collected. Sending to Google Sheets...")
        try:
            # 데이터가 많으면 잘릴 수 있으니 2번 나눠서 보낼 수도 있음 (일단은 한방에)
            response = requests.post(webhook_url, json=all_data)
            print(f"Done! Response: {response.text}")
        except Exception as e:
            print(f"Failed to send: {e}")
    else:
        print("Error: No data or Webhook URL missing.")
