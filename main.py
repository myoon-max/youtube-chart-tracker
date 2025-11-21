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

# ================= 설정 =================
# 수집할 차트 리스트
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

# ================= 크롤링 로직 =================
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def scrape_chart(driver, chart_name, url):
    print(f"Scraping {chart_name}...")
    driver.get(url)
    time.sleep(5) 
    
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(3)
    
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    rows = soup.find_all('ytmc-entry-row')
    
    data = []
    today = datetime.now().strftime("%Y-%m-%d")
    rank = 1
    
    for row in rows:
        try:
            title = row.find('div', class_='title').get_text(strip=True)
            artist = row.find('span', class_='artistName')
            if not artist: artist = row.find('div', class_='subtitle')
            artist_text = artist.get_text(strip=True) if artist else ""
            
            views_div = row.find('div', class_='views')
            views_text = views_div.get_text(strip=True) if views_div else "0"
            
            img = row.find('img')
            vid = ""
            if img and 'src' in img.attrs and '/vi/' in img['src']:
                vid = img['src'].split('/vi/')[1].split('/')[0]
                
            data.append({
                "Date": today,
                "Chart": chart_name,
                "Rank": rank,
                "Title": title,
                "Artist": artist_text,
                "Video_ID": vid,
                "Views": views_text
            })
            rank += 1
        except: continue
    return data

# ================= 실행 및 전송 =================
if __name__ == "__main__":
    driver = get_driver()
    all_data = []
    
    for name, url in TARGET_URLS.items():
        try:
            chart_data = scrape_chart(driver, name, url)
            all_data.extend(chart_data)
        except Exception as e:
            print(f"Error on {name}: {e}")
            
    driver.quit()
    
    # 깃허브 Secrets에서 웹훅 주소 가져오기
    webhook_url = os.environ.get("APPS_SCRIPT_WEBHOOK")
    
    if all_data and webhook_url:
        print(f"Total {len(all_data)} rows collected. Sending to Google Sheets...")
        try:
            response = requests.post(webhook_url, json=all_data)
            print(f"Done! Server Response: {response.text}")
        except Exception as e:
            print(f"Failed to send data: {e}")
    else:
        print("Error: No data collected OR APPS_SCRIPT_WEBHOOK is missing.")
        print(f"Data count: {len(all_data)}")
        print(f"Webhook URL exists: {bool(webhook_url)}")
