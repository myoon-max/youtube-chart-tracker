"""ytmc-v2-app Shadow DOM 파싱 회귀 테스트.

`scrape_youtube_chart`가 Selenium execute_script로 뽑는 payload(4개 차트 유형의 실제 DOM 값)를
`yt_payload_to_rows`에 그대로 넣어, 기존 출력 스키마(Date/Chart/Rank/Title/Artist/Video_ID/Views)로
정확히 변환되는지 확인한다. 브라우저/Selenium 없이 돈다.

    python tests/test_ytmc_v2_parse.py        (또는 python -m unittest)
"""
import json
import os
import sys
import unittest
from unittest import mock

# main.py는 selenium/bs4를 top-level에서 import한다. 이 환경에 없어도 테스트가 돌도록 stub을 채운다.
for _mod in (
    "selenium",
    "selenium.webdriver",
    "selenium.webdriver.chrome",
    "selenium.webdriver.chrome.options",
    "selenium.webdriver.chrome.service",
    "selenium.webdriver.common",
    "selenium.webdriver.common.by",
    "selenium.webdriver.support",
    "selenium.webdriver.support.ui",
    "selenium.webdriver.support.expected_conditions",
    "webdriver_manager",
    "webdriver_manager.chrome",
    "bs4",
    "requests",
):
    try:
        __import__(_mod)
    except ImportError:
        sys.modules[_mod] = mock.MagicMock()

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import main  # noqa: E402

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load_fixture(name):
    with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8") as fp:
        return json.load(fp)


class ParseCountTest(unittest.TestCase):
    def test_plain_and_grouped_numbers(self):
        self.assertEqual(main.parse_count_strict("739,305"), 739305)
        self.assertEqual(main.parse_count_strict("10,546,503"), 10546503)
        self.assertEqual(main.parse_count_strict(" 1,425,843 "), 1425843)

    def test_display_bounds_and_units(self):
        # YouTube가 '1만 미만'을 '<10K'로 표기 → 표시된 경계값으로 계산
        self.assertEqual(main.parse_count_strict("<10K"), 10000)
        self.assertEqual(main.parse_count_strict("1.5K"), 1500)
        self.assertEqual(main.parse_count_strict("2.4M"), 2400000)
        # 한국어 단위 (Shorts 생성 수 표기)
        self.assertEqual(main.parse_count_strict("3.9만"), 39000)
        self.assertEqual(main.parse_count_strict("3.9만개"), 39000)
        self.assertEqual(main.parse_count_strict("1.2천"), 1200)

    def test_empty_and_placeholder(self):
        self.assertEqual(main.parse_count_strict(""), 0)
        self.assertEqual(main.parse_count_strict(None), 0)
        self.assertEqual(main.parse_count_strict("-"), 0)
        self.assertEqual(main.parse_count_strict("New"), 0)


class ChartFixtureTest(unittest.TestCase):
    """4개 차트 유형 실제 DOM payload → 기존 출력 스키마."""

    def check_schema(self, item):
        self.assertEqual(
            sorted(item.keys()),
            sorted(["Date", "Chart", "Rank", "Title", "Artist", "Video_ID", "Views"]),
        )
        self.assertEqual(len(item["Date"]), 10)  # YYYY-MM-DD
        self.assertIsInstance(item["Rank"], int)
        self.assertIsInstance(item["Views"], int)
        self.assertTrue(item["Title"])

    def test_topvideos_daily_kr(self):
        fixture = load_fixture("ytmc_v2_topvideos_kr_daily.json")
        rows = main.yt_payload_to_rows(fixture["chart"], fixture["payload"])

        self.assertEqual(len(rows), 4)
        for item in rows:
            self.check_schema(item)

        top = rows[0]
        self.assertEqual(top["Chart"], "KR_Daily_Top_MV")
        self.assertEqual(top["Rank"], 1)
        self.assertEqual(top["Title"], "꿈꾸던 어른이 되었나요?")
        self.assertEqual(top["Artist"], "머무르")
        self.assertEqual(top["Video_ID"], "GxChUrrY4bc")
        self.assertEqual(top["Views"], 739305)  # 이전 파서가 놓쳤던 값

        # 여러 아티스트는 ', '로 합쳐진다.
        self.assertEqual(rows[3]["Artist"], "A2O LITE, A2O")
        self.assertEqual(rows[3]["Views"], 147908)

    def test_topsongs_weekly_kr(self):
        fixture = load_fixture("ytmc_v2_topsongs_kr_weekly.json")
        rows = main.yt_payload_to_rows(fixture["chart"], fixture["payload"])

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["Views"], 10546503)
        self.assertEqual(rows[1]["Views"], 6065034)

        # 곡 앨범아트가 아닌 entity-title endpoint에서도 Video ID를 얻는다.
        self.assertEqual(rows[2]["Video_ID"], "Mmw-PpWhKFg")
        self.assertEqual(rows[2]["Artist"], "K/DA, League of Legends, i-dle (아이들), Mimi Webb")
        self.assertEqual(rows[2]["Views"], 1425843)

    def test_trending_rightnow_kr(self):
        # 헤더 가운데 두 칸이 빈 문자열이어도 '주간 조회수' 위치(3)를 찾아 매핑해야 한다.
        fixture = load_fixture("ytmc_v2_trending_kr_rightnow.json")
        rows = main.yt_payload_to_rows(fixture["chart"], fixture["payload"])

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["Title"], "기립 (GiiiRIP)")
        self.assertEqual(rows[0]["Video_ID"], "IQI2qaqHFlg")
        # '<10K'는 경계값 10000으로 계산된다(실제 조회수는 1만 미만).
        self.assertEqual(rows[0]["Views"], 10000)
        self.assertEqual([r["Rank"] for r in rows], [1, 2, 30])

    def test_topshorts_daily_kr(self):
        fixture = load_fixture("ytmc_v2_topshorts_kr_daily.json")
        rows = main.yt_payload_to_rows(fixture["chart"], fixture["payload"])

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["Views"], 10000)  # DOM은 '<10K' 상한만 제공
        self.assertEqual(rows[0]["Video_ID"], "GxChUrrY4bc")
        self.assertEqual(rows[2]["Title"], "CHOP!")


class RobustnessTest(unittest.TestCase):
    def test_skips_rows_without_title(self):
        payload = {
            "header": ["발매일", "주간 조회수"],
            "rows": [
                {"rank": "", "title": "", "artist": "x", "video_id": "", "metrics": ["-", "1,000"]},
                {"rank": "", "title": "살아있는 행", "artist": "y", "video_id": "abcdefghijk",
                 "metrics": ["-", "2,000"]},
            ],
        }
        rows = main.yt_payload_to_rows("TEST", payload)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Title"], "살아있는 행")
        self.assertEqual(rows[0]["Rank"], 1)  # 순위 텍스트가 없으면 순서로 채운다
        self.assertEqual(rows[0]["Views"], 2000)

    def test_views_header_missing_falls_back_to_last_metric(self):
        payload = {
            "header": [],
            "rows": [
                {"rank": "1", "title": "곡", "artist": "가수", "video_id": "",
                 "metrics": ["2026년 1월 1일", "3", "4,321"]},
            ],
        }
        rows = main.yt_payload_to_rows("TEST", payload)
        self.assertEqual(rows[0]["Views"], 4321)

    def test_empty_payload(self):
        self.assertEqual(main.yt_payload_to_rows("TEST", None), [])
        self.assertEqual(main.yt_payload_to_rows("TEST", {}), [])


class ShortsParserTest(unittest.TestCase):
    """Shorts 생성 수 표기(로케일별) 파싱."""

    def test_korean_label(self):
        body = "꿈꾸던 어른이 되었나요?\n@meomuru_official\n•\nShorts 동영상 3.9만개\n조회수 194만회"
        self.assertEqual(main.parse_shorts_creation_count(body), 39000)

    def test_english_label(self):
        body = "Some title\n39K Shorts\n"
        self.assertEqual(main.parse_shorts_creation_count(body), 39000)

    def test_missing_label(self):
        self.assertEqual(main.parse_shorts_creation_count(""), 0)
        self.assertEqual(main.parse_shorts_creation_count("그냥 영상 페이지"), 0)


class FakeDriver:
    """Selenium 드라이버 대신 execute_script 결과만 돌려주는 테스트용 객체.

    row_counts를 주면 페이지를 열 때마다(get) 그 순서대로 행 수가 바뀐다.
    (예: [0, 100] = 첫 로드 0행, 재접속 후 100행)
    dead_on_loads에 로드 번호를 넣으면 그 로드에서 드라이버가 죽은 것처럼 예외를 낸다.
    """

    def __init__(self, payload, row_count=100, row_counts=None, dead_on_loads=()):
        self.payload = payload
        self.row_count = row_count
        self.row_counts = list(row_counts or [])
        self.dead_on_loads = set(dead_on_loads)
        self.dead = False
        self._title = "YouTube Music Charts"
        self.current_url = "https://charts.youtube.com/..."
        self.scripts = []
        self.loads = 0
        self.quit_called = False

    @property
    def title(self):
        if self.dead:
            raise RuntimeError("invalid session id")
        return self._title

    def _advance_rows(self):
        if self.row_counts:
            self.row_count = self.row_counts.pop(0)

    def get(self, url):
        self.loads += 1
        self.current_url = url
        if self.loads in self.dead_on_loads:
            self.dead = True
            raise RuntimeError("invalid session id")
        self._advance_rows()

    def quit(self):
        self.quit_called = True

    def execute_script(self, script, *args):
        self.scripts.append(script)
        if script is main.YT_ROW_COUNT_JS:
            return self.row_count
        if script is main.YT_CHART_EXTRACT_JS:
            return self.payload
        return None

    def find_element(self, *args, **kwargs):
        raise RuntimeError("no element in fake driver")


class FakeSession:
    """DriverSession 대신 쓰는 테스트용 세션. 재시작 횟수를 기록한다.

    fresh를 주면 재시작 시 그 드라이버로 갈아탄다(죽은 드라이버 → 산 드라이버).
    """

    def __init__(self, driver, fresh=None):
        self.driver = driver
        self.fresh = fresh
        self.restarts = 0
        self.started = 0

    def start(self):
        self.started += 1
        return self.driver

    def restart(self):
        self.restarts += 1
        if self.fresh is not None:
            self.driver = self.fresh
        return self.driver

    def close(self):
        self.driver = None


class FastTime:
    """대기 루프를 실제로 기다리지 않도록 시간을 빠르게 흐르는 대체 모듈."""

    def __init__(self):
        self.now = 0.0

    def time(self):
        self.now += 1.0
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class ScrapeYoutubeChartTest(unittest.TestCase):
    """브라우저 대신 FakeDriver로 scrape_youtube_chart 오케스트레이션을 검증한다."""

    def run_chart(self, chart_name, fixture_name, row_counts=None, session=None, **kwargs):
        fixture = load_fixture(fixture_name)
        driver = FakeDriver(fixture["payload"], row_counts=row_counts, **kwargs)
        session = session or FakeSession(driver)
        with mock.patch.object(main, "time", FastTime()):
            return main.scrape_youtube_chart(chart_name, "https://charts.youtube.com/x", session)

    def test_daily_mv_end_to_end(self):
        rows = self.run_chart("KR_Daily_Top_MV", "ytmc_v2_topvideos_kr_daily.json")
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["Views"], 739305)
        self.assertEqual(rows[0]["Chart"], "KR_Daily_Top_MV")

    def test_weekly_songs_end_to_end(self):
        rows = self.run_chart("KR_Weekly_Top_Songs", "ytmc_v2_topsongs_kr_weekly.json")
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["Views"], 10546503)

    def test_shorts_chart_prefers_creation_count(self):
        # 영상 페이지 조회를 실제로 하지 않도록 생성 수 함수만 대체한다.
        with mock.patch.object(main, "get_shorts_creation_count", lambda driver, vid: 39000):
            rows = self.run_chart("KR_Daily_Top_Shorts", "ytmc_v2_topshorts_kr_daily.json")
        self.assertEqual(len(rows), 3)
        self.assertEqual([r["Views"] for r in rows], [39000, 39000, 39000])

    def test_shorts_falls_back_to_dom_views_when_lookup_fails(self):
        with mock.patch.object(main, "get_shorts_creation_count", lambda driver, vid: 0):
            rows = self.run_chart("KR_Daily_Top_Shorts", "ytmc_v2_topshorts_kr_daily.json")
        self.assertEqual(rows[0]["Views"], 10000)  # DOM의 '<10K'

    def test_zero_rows_returns_empty(self):
        rows = self.run_chart("KR_Daily_Top_MV", "ytmc_v2_topvideos_kr_daily.json", row_count=0)
        self.assertEqual(rows, [])


class ViewsHeaderTest(unittest.TestCase):
    """조회수 컬럼 헤더를 한국어('조회수')·영어('Views'/'Weekly views') 모두 인식한다."""

    def test_column_index(self):
        self.assertEqual(main.views_column_index(["발매일", "어제", "차트에 머문 기간", "주간 조회수"]), 3)
        self.assertEqual(
            main.views_column_index(["Release date", "Last week", "Weeks on chart", "Weekly views"]), 3
        )
        self.assertEqual(main.views_column_index(["Views", "Release date"]), 0)
        # 'Weeks on chart'를 조회수로 오인하면 안 된다.
        self.assertEqual(main.views_column_index(["Weeks on chart", "Last week"]), -1)
        self.assertEqual(main.views_column_index([]), -1)
        self.assertEqual(main.views_column_index(None), -1)

    def test_english_weekly_views_header(self):
        payload = {
            "header": ["Release date", "Last week", "Weeks on chart", "Weekly views"],
            "rows": [
                {"rank": "1", "title": "Dai Dai", "artist": "Shakira", "video_id": "fcnDmrtj6Sk",
                 "metrics": ["2026-11-20", "3", "12", "2,547,365"]},
                {"rank": "2", "title": "Song", "artist": "Artist", "video_id": "",
                 "metrics": ["2026-11-18", "-", "4", "1.5M"]},
            ],
        }
        rows = main.yt_payload_to_rows("US_Weekly_Top_MV", payload)
        self.assertEqual([r["Views"] for r in rows], [2547365, 1500000])

    def test_english_views_column_not_last(self):
        # 조회수가 마지막 컬럼이 아니여도 헤더 위치를 보고 고른다.
        payload = {
            "header": ["Views", "Release date", "Weeks on chart"],
            "rows": [
                {"rank": "1", "title": "Song", "artist": "Artist", "video_id": "",
                 "metrics": ["987,654", "2026-11-20", "8"]},
            ],
        }
        self.assertEqual(main.yt_payload_to_rows("TEST", payload)[0]["Views"], 987654)

    def test_korean_header_still_works(self):
        payload = {
            "header": ["발매일", "어제", "차트에 머문 기간", "주간 조회수"],
            "rows": [
                {"rank": "1", "title": "곡", "artist": "가수", "video_id": "",
                 "metrics": ["2026-11-20", "1", "122", "773,660"]},
            ],
        }
        self.assertEqual(main.yt_payload_to_rows("KR_Daily_Top_MV", payload)[0]["Views"], 773660)


class RetryTest(unittest.TestCase):
    """0행일 때 드라이버를 갈아치우지 않고 같은 세션(쿠키)으로 한 번 더 시도한다."""

    FIXTURE = "ytmc_v2_topvideos_kr_daily.json"

    def run_scrape(self, row_counts, session=None):
        payload = load_fixture(self.FIXTURE)["payload"]
        driver = FakeDriver(payload, row_counts=row_counts)
        session = session or FakeSession(driver)
        with mock.patch.object(main, "time", FastTime()):
            rows = main.scrape_youtube_chart("KR_Daily_Top_MV", "https://charts.youtube.com/x", session)
        return rows, driver, session

    def test_retries_with_same_session(self):
        rows, driver, session = self.run_scrape([0, 100])
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["Views"], 739305)
        # 두 번 째 시도는 재시작이 아니라 같은 드라이버로 URL을 다시 여는 것
        self.assertEqual((driver.loads, session.restarts), (2, 0))

    def test_no_driver_restart_when_rows_never_appear(self):
        rows, driver, session = self.run_scrape([0, 0])
        self.assertEqual(rows, [])
        self.assertEqual((driver.loads, session.restarts), (2, 0))

    def test_restarts_only_when_driver_is_dead(self):
        payload = load_fixture(self.FIXTURE)["payload"]
        dead = FakeDriver(payload, dead_on_loads={1})
        fresh = FakeDriver(payload, row_counts=[100])
        session = FakeSession(dead, fresh=fresh)
        with mock.patch.object(main, "time", FastTime()):
            rows = main.scrape_youtube_chart("KR_Daily_Top_MV", "https://charts.youtube.com/x", session)
        self.assertEqual(len(rows), 4)
        self.assertEqual((dead.loads, fresh.loads, session.restarts), (1, 1, 1))
        self.assertIs(session.driver, fresh)

    def test_gives_up_when_driver_keeps_dying(self):
        payload = load_fixture(self.FIXTURE)["payload"]
        dead = FakeDriver(payload, dead_on_loads={1})
        dead_again = FakeDriver(payload, dead_on_loads={1})
        session = FakeSession(dead, fresh=dead_again)
        with mock.patch.object(main, "time", FastTime()):
            rows = main.scrape_youtube_chart("KR_Daily_Top_MV", "https://charts.youtube.com/x", session)
        self.assertEqual(rows, [])
        self.assertEqual(session.restarts, 1)


class StealthTest(unittest.TestCase):
    """HeadlessChrome 노출 제거·webdriver 플래그 숨김 로직."""

    def test_clean_user_agent_strips_headless_marker(self):
        ua = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "HeadlessChrome/131.0.6778.85 Safari/537.36")
        cleaned = main.clean_user_agent(ua)
        self.assertNotIn("HeadlessChrome", cleaned)
        self.assertIn("Chrome/131.0.6778.85", cleaned)
        self.assertEqual(cleaned, ua.replace("HeadlessChrome/", "Chrome/"))

    def test_clean_user_agent_leaves_normal_ua_alone(self):
        ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/131.0.0.0 Safari/537.36")
        self.assertEqual(main.clean_user_agent(ua), ua)

    def test_clean_user_agent_handles_empty(self):
        self.assertEqual(main.clean_user_agent(""), "")
        self.assertEqual(main.clean_user_agent(None), "")

    def test_constants_match_tuning(self):
        # reCAPTCHA 검증 후 렌더링을 기다리는 시간, 재시도 횟수
        self.assertEqual(main.YT_ROW_WAIT_SECONDS, 35)
        self.assertEqual(main.YT_MAX_ATTEMPTS, 2)

    def test_recaptcha_challenge_detection(self):
        class ChallengeDriver:
            def __init__(self, value):
                self.value = value

            def execute_script(self, script, *args):
                return self.value

        self.assertTrue(main._recaptcha_challenge_present(ChallengeDriver(True)))
        self.assertFalse(main._recaptcha_challenge_present(ChallengeDriver(False)))

        class BrokenDriver:
            def execute_script(self, script, *args):
                raise RuntimeError("session deleted")

        self.assertFalse(main._recaptcha_challenge_present(BrokenDriver()))


class DriverOptionsTest(unittest.TestCase):
    """구형 UA 고정 없이, 실제 UA에서 HeadlessChrome만 지워 CDP로 적용한다."""

    def run_get_driver(self, navigator_ua, cdp_error=None):
        captured = {"drivers": [], "options": []}

        class FakeOptions:
            def __init__(self):
                self.arguments = []
                self.experimental = {}
                captured["options"].append(self)

            def add_argument(self, arg):
                self.arguments.append(arg)

            def add_experimental_option(self, key, value):
                self.experimental[key] = value

        class FakeWebDriver:
            def __init__(self):
                self.timeout = None
                self.cdp = []
                self.quit_called = False
                captured["drivers"].append(self)

            def set_page_load_timeout(self, seconds):
                self.timeout = seconds

            def execute_script(self, script, *args):
                if "navigator.userAgent" in script:
                    if navigator_ua is None:
                        raise RuntimeError("no ua")
                    return navigator_ua
                return None

            def execute_cdp_cmd(self, cmd, params):
                self.cdp.append((cmd, params))
                if cdp_error and cmd == "Network.setUserAgentOverride":
                    raise RuntimeError(cdp_error)

            def quit(self):
                self.quit_called = True

        with mock.patch.object(main, "Options", FakeOptions), \
                mock.patch.object(main, "Service", lambda *a, **k: None), \
                mock.patch.object(main, "ChromeDriverManager",
                                  lambda *a, **k: mock.Mock(install=lambda: "chromedriver")), \
                mock.patch.object(main.webdriver, "Chrome", lambda service=None, options=None: FakeWebDriver()):
            driver = main.get_driver()

        return driver, captured

    def ua_override(self, driver):
        for cmd, params in driver.cdp:
            if cmd == "Network.setUserAgentOverride":
                return params
        return None

    def test_applies_clean_user_agent_over_cdp(self):
        ua = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "HeadlessChrome/131.0.6778.85 Safari/537.36")
        driver, captured = self.run_get_driver(ua)

        params = self.ua_override(driver)
        self.assertIsNotNone(params)
        self.assertNotIn("HeadlessChrome", params["userAgent"])
        self.assertIn("Chrome/131.0.6778.85", params["userAgent"])
        self.assertEqual(params["acceptLanguage"], main.ACCEPT_LANGUAGE)

        # webdriver 플래그도 페이지 로드 전에 숨긴다.
        self.assertIn("Page.addScriptToEvaluateOnNewDocument", [c for c, _ in driver.cdp])
        self.assertEqual(driver.timeout, main.PAGE_LOAD_TIMEOUT_SECONDS)

        # 정상 경로에서는 UA를 커맨드라인 옵션으로 고정하지 않는다.
        args = captured["options"][0].arguments
        self.assertEqual([a for a in args if "user-agent" in a.lower()], [])
        self.assertIn("--headless=new", args)

    def test_falls_back_to_fixed_ua_when_navigator_ua_unavailable(self):
        driver, _ = self.run_get_driver(None)
        params = self.ua_override(driver)
        self.assertEqual(params["userAgent"], main.FALLBACK_USER_AGENT)
        self.assertNotIn("HeadlessChrome", params["userAgent"])

    def test_recreates_driver_with_ua_option_when_cdp_blocked(self):
        driver, captured = self.run_get_driver("Mozilla/5.0 HeadlessChrome/131.0.6778.85", cdp_error="not implemented")
        self.assertEqual(len(captured["drivers"]), 2)
        self.assertTrue(captured["drivers"][0].quit_called)
        second_args = captured["options"][1].arguments
        self.assertIn(f"--user-agent={main.FALLBACK_USER_AGENT}", second_args)
        self.assertIs(driver, captured["drivers"][1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
