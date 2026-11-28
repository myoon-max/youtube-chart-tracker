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
# [PART 1] 설정 (서버용 최적화)
# ==========================================

# 1. 데이터 보낼 주소 (대표님 CSV 주소)
WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbyFm0Xu2BY3T_JcNgQqQssOhY1hJ-UH1A-GW2hhRLT-jDkgevFL74Bl1iEXUFPW1pleBw/exec"

# 2. 유튜브 API 키
YOUTUBE_API_KEY = "AIzaSyDFFZNYygA85qp5p99qUG2Mh8Kl5qoLip4"

# 3. 브라우저/재시도 설정
PAGE_LOAD_TIMEOUT_SECONDS = 60   # 한 페이지 로드에 걸 수 있는 최대 시간(무한 대기 방지)
YT_ROW_WAIT_SECONDS = 35        # 한 번의 시도에서 차트 테이블(ytmc-entry-row)을 기다리는 시간 (reCAPTCHA 검증 후 렌더링 여유)
YT_MAX_ATTEMPTS = 2             # 최초 1회 + 같은 세션으로 재접속 1회 (드라이버 재시작은 '죽었을 때'만)
YT_DEFAULT_TITLE = "YouTube Music Charts"   # 차트 SPA가 안 그려졌을 때의 기본 타이틀

# headless 크롬은 UA에 'HeadlessChrome/...'을 남긴다. charts.youtube.com은 이를
# 봇 신호로 보고 reCAPTCHA 챌린지를 띄워 차트 데이터를 주지 않으므로 'Chrome/...'으로 바꾼다.
# (버전은 항상 실행 중인 실제 크롬을 그대로 따른다. CDP를 못 쓰는 환경의 대체 UA만 고정)
FALLBACK_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
ACCEPT_LANGUAGE = "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"

# navigator.webdriver=true 도 자동화 신호라서 지운다.
WEBDRIVER_HIDE_JS = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"

# 4. 크롤링 대상 URL
TARGET_URLS = {
    "KR_Daily_Trending": "https://charts.youtube.com/charts/TrendingVideos/kr/RightNow",
    "US_Daily_Trending": "https://charts.youtube.com/charts/TrendingVideos/us/RightNow",
    "KR_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/kr/daily",
    "US_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/us/daily",
    "EG_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/eg/daily",
    "SA_Daily_Top_MV": "https://charts.youtube.com/charts/TopVideos/sa/daily",
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
    """차트 표기를 정수로 변환한다.

    '739,305' / '10,546,503' / '3.9만' / '1.2천' / '<10K' / '1.5M' 형태를 모두 처리한다.
    '<10K' 처럼 상한만 표시된 값은 표시된 경계값(10000)으로 계산한다.
    """
    if not text: return 0
    t = str(text).lower().strip().replace(',', '').replace(' ', '')
    t = re.sub(r'^[<>≈~]+', '', t)

    multiplier = 1
    # 한국어 단위 → 영문 단위 순서로 확인 (긴 단위 우선)
    for token, multi in (('조', 10**12), ('억', 10**8), ('만', 10**4), ('천', 10**3),
                         ('b', 10**9), ('m', 10**6), ('k', 10**3)):
        if token in t:
            multiplier = multi
            t = t.replace(token, '')
            break

    clean = re.sub(r'[^\d.]', '', t)
    if not clean: return 0
    try:
        val = float(clean)
        return int(val * multiplier)
    except: return 0

def clean_text(text):
    return re.sub(r'\s+', ' ', text).strip()

def clean_user_agent(ua):
    """headless 크롬 UA에서 봇 신호('HeadlessChrome')를 지운다.

    'Mozilla/5.0 ... HeadlessChrome/131.0.6778.85 Safari/537.36'
    → 'Mozilla/5.0 ... Chrome/131.0.6778.85 Safari/537.36'
    버전은 건드리지 않으므로 실행 중인 실제 크롬과 항상 일치한다.
    """
    if not ua:
        return ""
    return re.sub(r'HeadlessChrome/', 'Chrome/', str(ua))


def apply_stealth(driver):
    """드라이버에 스텔스 설정을 적용한다 (UA 정리 + webdriver 플래그 숨김).

    적용한 UA 문자열을 돌려주고, UA 오버라이드까지 실패하면 None을 돌려준다.
    (호출한 쪽이 fallback UA로 드라이버를 다시 띄우는 판단을 할 수 있게 한다)
    """
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument",
                               {"source": WEBDRIVER_HIDE_JS})
    except Exception as e:
        print(f"   ⚠️ webdriver 플래그 숨김 실패(계속 진행): {e}")

    try:
        current_ua = driver.execute_script("return navigator.userAgent;")
    except Exception:
        current_ua = ""

    ua = clean_user_agent(current_ua)
    if not ua:
        ua = FALLBACK_USER_AGENT
        print("   ⚠️ 브라우저 UA를 읽지 못해 fallback UA를 사용")

    try:
        driver.execute_cdp_cmd("Network.setUserAgentOverride",
                               {"userAgent": ua, "acceptLanguage": ACCEPT_LANGUAGE})
    except Exception as e:
        print(f"   ⚠️ UA 오버라이드 실패: {e}")
        return None

    print(f"   🕶️ UA 적용: {ua}")
    return ua


def chrome_options(user_agent=None):
    """크롬 실행 옵션. user_agent를 주면 커맨드라인 옵션으로 UA를 고정한다(CDP fallback용)."""
    options = Options()

    # Github Actions에서는 무조건 headless 켜야 함
    options.add_argument("--headless=new")

    # 유튜브 봇 탐지 우회 옵션
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=en-US")
    # 자동화 제어 메시지 제거 (봇 탐지 회피)
    options.add_argument("--disable-blink-features=AutomationControlled")
    if user_agent:
        options.add_argument(f"--user-agent={user_agent}")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    return options


def get_driver():
    # User-Agent는 옵션으로 고정하지 않는다. 구형 Chrome/115.0.0.0으로 고정하면 실제
    # 브라우저 버전과 어긋나 봇 신호가 되고, 반대로 아무것도 하지 않으면 --headless=new의
    # UA에 'HeadlessChrome/...'이 그대로 노출된다. 둘 다 charts.youtube.com의 reCAPTCHA
    # 챌린지를 부르므로, 드라이버를 띄운 뒤 apply_stealth()에서 실제 UA를 읽어
    # 'HeadlessChrome'만 지우고 CDP로 덮어쓴다.
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options())
    # chromedriver가 응답 없이 120초씩 매달리는 경우가 있어 페이지 로드에 상한을 둔다.
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT_SECONDS)

    if apply_stealth(driver) is None:
        # CDP 호출이 막힌 환경: 커맨드라인 옵션으로 fallback UA를 넣어 한 번 더 띄운다.
        try:
            driver.quit()
        except Exception:
            pass
        print("   ⚠️ CDP UA 적용 실패 → 고정 Chrome UA로 드라이버를 다시 띄운다")
        driver = webdriver.Chrome(service=service, options=chrome_options(FALLBACK_USER_AGENT))
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT_SECONDS)
        apply_stealth(driver)

    return driver

# ================= 유튜브 API & 파싱 =================

# charts.youtube.com은 2026년 11월 `ytmc-v2-app`으로 개편되면서
# 차트 테이블(ytmc-entry-row)과 그 안의 순위/제목/아티스트/조회수가
# 전부 중첩 Shadow DOM 안으로 들어갔다.
# driver.page_source(=document.documentElement.outerHTML)에는 Shadow DOM 내부가
# 직렬화되지 않아 BeautifulSoup로는 행도 값도 읽을 수 없다.
# → Selenium execute_script로 document의 모든 shadowRoot를 재귀 순회해 직접 뽑는다.

# 조회수 컬럼 헤더 이름 (한국어 '주간 조회수', 영어 'Weekly views'/'Views' 등)
VIEWS_HEADER_PATTERN = re.compile(r'조회수|\bviews?\b', re.IGNORECASE)

# 모든 shadowRoot를 순회하며 ytmc-entry-row 개수만 센다 (렌더링/스크롤 대기용)
YT_ROW_COUNT_JS = """
return (function () {
  var count = 0;
  var walk = function (root) {
    if (!root.querySelectorAll) return;
    count += root.querySelectorAll('ytmc-entry-row').length;
    var all = root.querySelectorAll('*');
    for (var i = 0; i < all.length; i++) {
      if (all[i].shadowRoot) walk(all[i].shadowRoot);
    }
  };
  walk(document);
  return count;
})();
"""

# 차트 테이블 헤더(컬럼명)와 행 데이터를 통째로 뽑아 JSON으로 돌려준다.
# 반환: {row_count: int, header: [컬럼명...], rows: [{rank, title, artist, video_id, metrics:[...]}]}
# metrics는 header와 같은 순서/개수로 대응된다 (예: 발매일, 어제, 차트에 머문 기간, 주간 조회수).
YT_CHART_EXTRACT_JS = """
var collectRows = function (root) {
  var rows = [];
  var walk = function (el) {
    if (!el.querySelectorAll) return;
    var found = el.querySelectorAll('ytmc-entry-row');
    for (var i = 0; i < found.length; i++) rows.push(found[i]);
    var all = el.querySelectorAll('*');
    for (var j = 0; j < all.length; j++) {
      if (all[j].shadowRoot) walk(all[j].shadowRoot);
    }
  };
  walk(root);
  return rows;
};

var findHeaderMetrics = function (root) {
  var result = null;
  var walk = function (el) {
    if (result || !el.querySelectorAll) return;
    var hs = el.querySelectorAll('.table-header-metric');
    if (hs.length) {
      result = [];
      for (var i = 0; i < hs.length; i++) result.push(hs[i].textContent.trim());
      return;
    }
    var all = el.querySelectorAll('*');
    for (var j = 0; j < all.length; j++) {
      if (all[j].shadowRoot) {
        walk(all[j].shadowRoot);
        if (result) return;
      }
    }
  };
  walk(root);
  return result || [];
};

var videoIdOf = function (root) {
  var candidates = [
    root.querySelector('#entity-title'),
    root.querySelector('img#thumbnail'),
    root.querySelector('img.tracks-thumbnail')
  ];
  for (var i = 0; i < candidates.length; i++) {
    var el = candidates[i];
    if (!el) continue;
    var ep = el.getAttribute('endpoint');
    if (ep) {
      try {
        var j = JSON.parse(ep);
        var url = (j.urlEndpoint && j.urlEndpoint.url) || '';
        var m = url.match(/[?&]v=([A-Za-z0-9_-]{11})/);
        if (m) return m[1];
      } catch (e) {}
    }
    var src = el.getAttribute('src');
    if (src) {
      var m2 = src.match(/[/]vi(?:_webp)?[/]([A-Za-z0-9_-]{11})/);
      if (m2) return m2[1];
    }
  }
  var m3 = root.innerHTML.match(/[?&]v=([A-Za-z0-9_-]{11})/);
  return m3 ? m3[1] : '';
};

return (function () {
  var rows = collectRows(document);
  var header = findHeaderMetrics(document);
  var out = [];
  for (var i = 0; i < rows.length; i++) {
    var light = rows[i];
    var root = light.shadowRoot || light;
    var titleEl = root.querySelector('#entity-title') || root.querySelector('.title');
    var rankEl = root.querySelector('#rank');

    var artists = [];
    var artistEls = root.querySelectorAll('span.artistName');
    for (var a = 0; a < artistEls.length; a++) artists.push(artistEls[a].textContent.trim());
    if (!artists.length) {
      var sub = root.querySelector('#artist-names') || root.querySelector('.subtitle');
      if (sub) artists.push(sub.textContent.trim());
    }

    var metrics = [];
    var metricEls = root.querySelectorAll('.metric');
    for (var k = 0; k < metricEls.length; k++) metrics.push(metricEls[k].textContent.trim());

    out.push({
      rank: rankEl ? rankEl.textContent.trim() : '',
      title: titleEl ? titleEl.textContent.trim() : '',
      artist: artists.filter(function (x) { return x; }).join(', '),
      video_id: videoIdOf(root),
      metrics: metrics
    });
  }
  return { row_count: rows.length, header: header, rows: out };
})();
"""

def _yt_row_count(driver):
    try:
        return int(driver.execute_script(YT_ROW_COUNT_JS) or 0)
    except Exception:
        return 0

def _wait_for_yt_rows(driver, timeout=YT_ROW_WAIT_SECONDS):
    """차트 테이블(Shadow DOM 안의 ytmc-entry-row)이 렌더링될 때까지 기다린다."""
    end = time.time() + timeout
    while time.time() < end:
        count = _yt_row_count(driver)
        if count:
            return count
        time.sleep(0.5)
    return 0

def _scroll_yt_chart(driver, max_rounds=12, pause=0.4):
    """행이 지연 렌더링되는 경우를 대비해 아래로 내리며 행 수가 늘어나는지 확인한다."""
    last = _yt_row_count(driver)
    for _ in range(max_rounds):
        driver.execute_script("window.scrollBy(0, Math.floor(window.innerHeight * 0.9));")
        time.sleep(pause)
        current = _yt_row_count(driver)
        at_bottom = driver.execute_script(
            "return (window.innerHeight + window.pageYOffset) >= (document.body.scrollHeight - 5);"
        )
        if at_bottom and current == last:
            break
        last = current
    driver.execute_script("window.scrollTo(0, 0);")

class DriverSession:
    """Selenium 드라이버 한 개를 들고 있다가, 죽었을 때만 새로 띄운다.

    차트 로딩은 0행이어도 같은 드라이버(=같은 쿠키/reCAPTCHA 세션)로 재시도한다.
    재시작은 드라이버가 응답하지 않을 때뿐이고, 재시작하면 참조가 바뀌므로
    각 차트는 항상 session.driver에서 현재 드라이버를 얻어 쓴다.
    """

    def __init__(self, driver_factory=None):
        self._factory = driver_factory or get_driver
        self.driver = None

    def start(self):
        self.close()
        self.driver = self._factory()
        return self.driver

    def restart(self):
        print("   ♻️ 드라이버 재시작")
        return self.start()

    def close(self):
        driver, self.driver = self.driver, None
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


def _open_page(driver, url):
    """페이지를 연다. 페이지 로드 타임아웃/드라이버 오류는 다음 시도로 넘긴다."""
    try:
        driver.get(url)
        return True
    except Exception as e:
        print(f"   ⚠️ 페이지 열기 실패: {e}")
        return False


def _driver_title(driver):
    """드라이버가 아직 응답하는지 확인하며 타이틀을 읽는다. 응답이 없으면 None."""
    try:
        return driver.title
    except Exception:
        return None


def _recaptcha_challenge_present(driver):
    """차트 대신 reCAPTCHA 챌린지 패널이 떠 있는지 확인한다(로그용).

    charts.youtube.com은 봇으로 판단하면 차트 대신 reCAPTCHA Enterprise 챌린지를
    띄우고 데이터 요청 자체를 하지 않는다. 0행 로그만 보면 UA 문제인지 챌린지인지
    구분할 수 없어서, 실패 원인을 남기기 위해 확인만 한다(동작에는 영향 없음).
    """
    script = (
        "var fs = document.querySelectorAll('iframe[src*=\"recaptcha\"]');"
        "for (var i = 0; i < fs.length; i++) {"
        "  var s = fs[i].getAttribute('src') || '';"
        "  if (s.indexOf('bframe') >= 0 && (fs[i].offsetWidth || fs[i].offsetHeight)) return true;"
        "}"
        "return false;"
    )
    try:
        return bool(driver.execute_script(script))
    except Exception:
        return False


def _load_yt_chart(chart_name, url, session, attempts=YT_MAX_ATTEMPTS):
    """차트 페이지를 열고 ytmc-entry-row가 그려질 때까지 기다린다.

    charts.youtube.com은 reCAPTCHA 검증 뒤에 데이터가 붙어서 35초 안에 테이블이
    그려지지 않는 경우가 있다. 그래서 (1) 첫 시도에서 35초 기다리고,
    (2) 실패하면 같은 세션으로 URL을 한 번 더 열어 35초 더 기다린다.

    실패할 때마다 드라이버를 새로 띄우면 어렵게 통과한 reCAPTCHA 쿠키/세션까지
    날아가고 실행 시간만 늘어나므로, 드라이버가 실제로 죽은 경우에만 1회 재시작한다.

    반환: (사용한 driver, row_count). row_count가 0이면 끝까지 실패한 것이다.
    """
    if session.driver is None:
        try:
            session.start()
        except Exception as e:
            print(f"   ❌ 드라이버 생성 실패: {e}")
            return None, 0

    driver = session.driver
    restarted = False

    for attempt in range(1, attempts + 1):
        opened = _open_page(driver, url)
        if not opened and _driver_title(driver) is None:
            # 페이지 열기도, 타이틀 조회도 안 되면 드라이버가 죽은 것으로 본다.
            if restarted:
                return driver, 0
            try:
                driver = session.restart()
                restarted = True
            except Exception as e:
                print(f"   ❌ 드라이버 재시작 실패: {e}")
                return driver, 0
            if not _open_page(driver, url):
                return driver, 0

        row_count = _wait_for_yt_rows(driver)
        if row_count:
            if attempt > 1:
                print(f"   ✅ 재시도 {attempt - 1}회 후 로드: rows={row_count}")
            return driver, row_count

        title = _driver_title(driver)
        challenge = " · reCAPTCHA 챌린지 표시됨" if _recaptcha_challenge_present(driver) else ""
        # 기본 타이틀에 머물러 있으면 차트 SPA가 아직 안 그려진 것이다.
        if str(title).strip() == YT_DEFAULT_TITLE:
            print(f"   ⚠️ 시도 {attempt}/{attempts}: 차트 테이블 0개 · 기본 타이틀 유지('{title}'){challenge} / URL: {url}")
        else:
            print(f"   ⚠️ 시도 {attempt}/{attempts}: 차트 테이블 0개. Page Title: {title}{challenge} / URL: {url}")
        if attempt < attempts:
            print(f"   🔄 재시도 {attempt}: 같은 세션으로 URL 다시 열기")

    return driver, 0


def views_column_index(header):
    """헤더에서 조회수 컬럼 위치를 찾는다.

    GitHub Actions(영어 로케일)에서는 'Weekly views'/'Views', 국내 로케일에서는
    '주간 조회수'처럼 찍히므로 둘 다 같은 컬럼으로 인식한다. 없으면 -1.
    """
    for i, name in enumerate(header or []):
        if VIEWS_HEADER_PATTERN.search(str(name)):
            return i
    return -1


def yt_payload_to_rows(chart_name, payload):
    """execute_script로 뽑은 ytmc-v2-app payload를 기존 출력 스키마로 변환한다.

    출력 스키마는 기존과 동일: Date, Chart, Rank, Title, Artist, Video_ID, Views.
    조회수는 헤더에서 '조회수'(예: 주간 조회수) 또는 영어 'Views'(예: Weekly views)
    컬럼 위치를 찾아 그 위치의 metric을 쓴다.
    브라우저 없이 payload만으로 동작하므로 단위 테스트 대상이다.
    """
    payload = payload or {}
    rows = payload.get("rows") or []
    header = payload.get("header") or []
    views_idx = views_column_index(header)

    today = datetime.now().strftime("%Y-%m-%d")
    data_list = []

    for row in rows:
        title = clean_text(row.get("title") or "")
        if not title:
            continue

        metrics = [clean_text(m) for m in (row.get("metrics") or [])]
        if 0 <= views_idx < len(metrics):
            views_raw = metrics[views_idx]
        elif metrics:
            views_raw = metrics[-1]
        else:
            views_raw = ""

        rank_txt = str(row.get("rank") or "").strip()
        data_list.append({
            "Date": today,
            "Chart": chart_name,
            "Rank": int(rank_txt) if rank_txt.isdigit() else len(data_list) + 1,
            "Title": title,
            "Artist": clean_text(row.get("artist") or ""),
            "Video_ID": row.get("video_id") or "",
            "Views": parse_count_strict(views_raw)
        })

    return data_list

# 영상 페이지의 'Shorts 생성 수' 표기 (로케일별)
SHORTS_KO_PATTERN = re.compile(r'Shorts\s*동영상\s*([\d.,]+)\s*(만|천|억|조)?')
SHORTS_EN_PATTERN = re.compile(r'([\d.,]+)\s*([KMB])\s*Shorts', re.IGNORECASE)
SHORTS_LOOSE_PATTERN = re.compile(r'Shorts\s*([\d.,]+)\s*(만|천|억|조|K|M|B)?', re.IGNORECASE)

def parse_shorts_creation_count(body_text):
    """영상 페이지 텍스트에서 Shorts 생성 수를 뽑는다.

    'Shorts 동영상 3.9만개'(ko) / '39K Shorts'(en) 둘 다 처리한다. 못 찾으면 0.
    """
    if not body_text:
        return 0
    match = SHORTS_KO_PATTERN.search(body_text)
    if match:
        return parse_count_strict(match.group(1) + (match.group(2) or ""))
    match = SHORTS_EN_PATTERN.search(body_text)
    if match:
        return parse_count_strict(match.group(1) + match.group(2))
    match = SHORTS_LOOSE_PATTERN.search(body_text)
    if match:
        return parse_count_strict(match.group(1) + (match.group(2) or ""))
    return 0

def get_shorts_creation_count(driver, video_id):
    """Shorts 차트용 'Shorts 생성 수'를 영상의 source 페이지에서 읽는다."""
    if not video_id: return 0
    url = f"https://www.youtube.com/source/{video_id}/shorts"
    try:
        driver.get(url)

        # 생성 수 문구가 그려질 때까지 짧게 기다린다 (최대 8초)
        body_text = ""
        end = time.time() + 8
        while time.time() < end:
            try:
                body_text = driver.find_element(By.TAG_NAME, "body").text
            except Exception:
                body_text = ""
            if (SHORTS_KO_PATTERN.search(body_text)
                    or SHORTS_EN_PATTERN.search(body_text)
                    or SHORTS_LOOSE_PATTERN.search(body_text)):
                break
            time.sleep(0.5)

        return parse_shorts_creation_count(body_text)
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

# ================= 크롤러 메인 로직 =================

# 1. 유튜브 차트 크롤러 (ytmc-v2-app Shadow DOM 대응)
def scrape_youtube_chart(chart_name, url, session):
    print(f"🚀 Scraping YouTube: {chart_name}...")
    try:
        driver, row_count = _load_yt_chart(chart_name, url, session)
        if row_count == 0:
            print(f"   ❌ {chart_name}: {YT_MAX_ATTEMPTS}회 시도 후에도 차트 테이블이 없어 건너뜀")
            return []

        _scroll_yt_chart(driver)
        payload = driver.execute_script(YT_CHART_EXTRACT_JS) or {}
        rows = payload.get("rows") or []
        header = payload.get("header") or []
        print(f"   -> DOM rows: {len(rows)} / columns: {header}")

        data_list = yt_payload_to_rows(chart_name, payload)
        if data_list:
            sample = data_list[0]
            print(f"   -> 예시: #{sample['Rank']} {sample['Title'][:40]} / {sample['Artist'][:20]} / {sample['Video_ID']} / Views={sample['Views']}")

        views_idx = views_column_index(header)
        if header and views_idx < 0:
            print("   ⚠️ 조회수 컬럼을 찾지 못해 마지막 컬럼을 조회수로 사용")

        # '<10K' 처럼 상한만 표시된 조회수는 경계값으로 계산된다는 점을 로그로 남긴다.
        if views_idx >= 0:
            bounded = sum(
                1 for row in rows
                if views_idx < len(row.get('metrics') or []) and '<' in str(row['metrics'][views_idx])
            )
            if bounded:
                print(f"   -> 상한 표기('<10K') 행: {bounded}개 → 표시된 경계값으로 계산")

        # Shorts 차트는 기존과 동일하게 'Shorts 생성 수'를 우선 사용한다.
        # (실패하면 DOM의 주간 조회수 값이 그대로 남는다)
        if "Shorts" in chart_name:
            filled = 0
            for item in data_list:
                creations = get_shorts_creation_count(driver, item["Video_ID"])
                if creations:
                    item["Views"] = creations
                    filled += 1
            print(f"   -> Shorts 생성 수 확보: {filled}/{len(data_list)}")

        print(f"   -> Captured {len(data_list)} items.")
        return data_list

    except Exception as e:
        print(f"❌ YouTube Error ({chart_name}): {e}")
        print(traceback.format_exc())
        return []

# 2. 빌보드 크롤러 (안전장치 강화판 + 날짜는 오늘 날짜로 원상복구)
def scrape_billboard_official(driver, chart_key, url):
    print(f"🇺🇸 [SafeMode] Scraping {chart_key}...")
    max_retries = 2
    for attempt in range(max_retries):
        try:
            driver.get(url)
            # 천천히 스크롤 (빌보드 필수)
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
            
            # [원상복구] 빌보드는 그냥 오늘 날짜로 저장
            today = datetime.now().strftime("%Y-%m-%d")

            rows = soup.select('div.o-chart-results-list-row-container')
            print(f"   -> Found {len(rows)} row containers.")

            if len(rows) == 0:
                print("   ⚠️ 0 rows. Refreshing page...")
                continue 

            data = []
            
            for idx, row in enumerate(rows):
                try:
                    rank = idx + 1
                    try:
                        rank_tag = row.select_one('span.c-label.a-font-primary-bold-l')
                        if rank_tag and rank_tag.text.strip().isdigit():
                            rank = int(rank_tag.text.strip())
                    except: pass

                    title = "Unknown"
                    title_tag = row.select_one('h3.c-title') 
                    if not title_tag: title_tag = row.select_one('h3#title-of-a-story') 
                    if not title_tag: title_tag = row.select_one('h3') 
                    
                    if title_tag: title = title_tag.get_text(strip=True)

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
                print(f"✅ {chart_key}: Captured {len(data)} rows ({today}).")
                return data

        except Exception as e:
            print(f"❌ Error on attempt {attempt+1}: {e}")
            time.sleep(3)

    return []

# 3. 멜론
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

# 4. 지니
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


# 5. Kworb (HTML 날짜 파싱 유지 - 스크린샷 요청 반영)
def scrape_kworb(chart_key, url):
    print(f"🟢 Scraping {chart_key}...")
    data = []
    
    # 기본값은 오늘이지만, HTML에서 날짜를 찾으면 덮어씌움
    chart_date = datetime.now().strftime("%Y-%m-%d")
    TARGET_HEADER_KEYWORD = "Streams"

    try:
        res = requests.get(url)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # --- [날짜 추출 로직 유지] ---
        try:
            # 스크린샷에 있는 .pagetitle 클래스 탐색
            pagetitle = soup.select_one('.pagetitle')
            if pagetitle:
                title_text = pagetitle.get_text()
                # 예: "Spotify Daily Chart - Global - 2025/12/03 |" 에서 날짜 추출
                match = re.search(r'(\d{4})/(\d{2})/(\d{2})', title_text)
                if match:
                    # YYYY/MM/DD -> YYYY-MM-DD 변환
                    chart_date = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
                    print(f"   📅 Detected Date from HTML: {chart_date}")
        except Exception as de:
            print(f"   ⚠️ Date parse failed: {de}")
        # ---------------------------

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
                    "Date": chart_date, # 추출한 날짜 사용
                    "Chart": chart_key,
                    "Rank": rank,
                    "Title": title,
                    "Artist": artist,
                    "Video_ID": "",
                    "Views": final_val
                })
            except: continue
        print(f"✅ {chart_key}: {len(data)} rows ({chart_date})")
    except Exception as e: print(f"❌ Kworb Error ({chart_key}): {e}")
    return data

# ================= 메인 실행 =================
if __name__ == "__main__":
    session = DriverSession(get_driver)
    final_data = [] 

    try:
        print("=== [MusicDeal] Github Actions Crawler ===")
        
        # 1. 브라우저 크롤링 (YouTube / Billboard)
        try:
            session.start()
            
            # YouTube
            for name, url in TARGET_URLS.items():
                chart_data = scrape_youtube_chart(name, url, session)
                # Trending 보정: API 키가 만료(API key expired) 상태라 DOM 조회수를 우선하고,
                # DOM에서 값을 못 얻은 경우(Views=0)에만 API 값을 보충으로 쓴다.
                if "Trending" in name:
                    ids = [d["Video_ID"] for d in chart_data if d["Video_ID"]]
                    if ids:
                        api_stats = get_views_from_api(ids)
                        for item in chart_data:
                            if not item["Views"] and item["Video_ID"] in api_stats:
                                item["Views"] = api_stats[item["Video_ID"]]
                final_data.extend(chart_data)
            
            # Billboard (차트 로딩 중 드라이버가 재시작됐을 수 있어 session.driver를 쓴다)
            print("\n>>> Billboard...")
            for b_name, b_url in BILLBOARD_URLS.items():
                b_data = scrape_billboard_official(session.driver, b_name, b_url)
                final_data.extend(b_data)

        except Exception as sel_e:
            print(f"🔥 Selenium Fatal Error: {sel_e}")
            print(traceback.format_exc())
        finally:
            session.close()

        # 2. Requests 크롤링
        print("\n>>> Domestic & Kworb...")
        final_data.extend(scrape_melon())
        final_data.extend(scrape_genie())
        for key, url in EXTRA_URLS.items():
            final_data.extend(scrape_kworb(key, url))

        # 3. 데이터 전송
        print(f"\n📊 Total Data: {len(final_data)} rows")
        
        if len(final_data) > 0:
            print(f"🚀 Sending to: {WEBHOOK_URL[:40]}...")
            chunk_size = 3000
            for i in range(0, len(final_data), chunk_size):
                chunk = final_data[i:i+chunk_size]
                try:
                    response = requests.post(WEBHOOK_URL, json=chunk)
                    print(f"   -> Chunk {i//chunk_size + 1}: {response.status_code}")
                except Exception as e:
                    print(f"❌ Send Error: {e}")
                time.sleep(1)
            print("✨ Success.")
        else:
            print("⚠️ 0 rows collected. Check logs above.")

    except Exception as main_e:
        print("🔥 Fatal Script Error.")
        print(traceback.format_exc())


