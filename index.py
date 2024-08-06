from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from urllib.parse import urljoin, urlparse, urlunparse
import time
import random
import pprint
from googleapiclient.discovery import build
import gspread
import os
import itertools
from dotenv import load_dotenv
import os
import requests

load_dotenv()


SEARCH_ENGINE_ID = os.getenv("SEARCH_ENGINE_ID")
API_KEY = os.getenv("GOOGLE_API_KEY")
CLIENT_ID = os.getenv("CLIENT_ID")
SPREAD_SHEET_ID = os.getenv("SPREAD_SHEET_ID")


# 作業フォルダの取得
dir_path = os.path.dirname(__file__)

# gspreadの認証エラー例 (2024年 8月6日)
# 参照: https://mori-memo.hateblo.jp/entry/2023/05/06/152208
# 1. google cloud console から client_secret.json を取得する。
# 2. authorized_user.json(出力ファイル) の名前を別の名前に更新して、実行後に認証を行う。
gc = gspread.oauth(
    credentials_filename=os.path.join(dir_path, "client_secret.json"), # 認証用のJSONファイル
    authorized_user_filename=os.path.join(dir_path, "authorized_user.json") # 証明書の出力ファイル
)
# スプレッドシートを開く
spreadsheet = gc.open_by_key(SPREAD_SHEET_ID)

# シート名から取得
spreadSheet_wb = spreadsheet.worksheet("タスクシート")
spreadSheet_rb = spreadsheet.worksheet("検索クエリ設定")


# # 検索クエリを2行目から最後まで取得
data_queries = [row[0].replace('\u3000', ' ') for row in spreadSheet_rb.get_all_values()[1:]]
print(data_queries)
global counter

# 設定済みのdriverを用いて aタグ のhref要素を調べる
def get_all_links(driver):
    print(driver)
    links = driver.find_elements(By.CSS_SELECTOR, "a[href]")
    if not links:
        links = driver.find_elements(By.XPATH, "//a[@href]")

    link_urls = []
    for link in links:
        href = link.get_attribute('href')
        if href:
            link_urls.append(href)

    return link_urls

# 重複するクエリを削除してURLの正規化を行う
def normalize_url(url):
    parsed_url = urlparse(url)
    normalized_url = urlunparse((parsed_url.scheme, parsed_url.netloc, parsed_url.path, '', '', ''))
    return normalized_url

# 指定したurlから、メールアドレスが存在するかどうか、遷移先のURLを取得
def check_mail_in_page(url, visited, base_url, counter, max_depth=3):
    normalized_url = normalize_url(url)
    if normalized_url in visited:
        return False

    counter += 1
    if counter > 50 or max_depth == 0:
        return True
    visited.add(normalized_url)

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")

    # ダウンロードを無効にする設定
    prefs = {
        "download.prompt_for_download": False,
        "download.default_directory": "/dev/null",  # ダウンロード先を無効なディレクトリに設定
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        "safebrowsing.disable_download_protection": True,
        "plugins.always_open_pdf_externally": True  # PDFをブラウザ内で表示せず、外部プラグインで開く
    }
    chrome_options.add_experimental_option("prefs", prefs)

    # service = Service(ChromeDriverManager(version="latest", os_type="mac64").install())
    # service = Service(ChromeDriverManager().install())
    # driver = webdriver.Chrome(service=service, options=chrome_options)


    # 俺のPCの環境に依存しすぎる、とりあえず治したけどなんだこれ・・・。
    # webdriver_pathに存在する THIRD_PARTY_NOTICES.chromedriver を優先的に返してしまう
    # みたいで、正しいのはchromedriver本体だからそっちに強引にpathを変更した。なんでこうなるんだ。
    webdriver_path = ChromeDriverManager().install()
    if os.path.splitext(webdriver_path)[1] != '.exe':
        webdriver_dir_path = os.path.dirname(webdriver_path)
        webdriver_path = os.path.join(webdriver_dir_path, 'chromedriver')
    chrome_service = Service(executable_path=webdriver_path)
    driver = webdriver.Chrome(service=chrome_service, options=chrome_options)

    
    try:
        driver.set_page_load_timeout(5) 
        driver.get(url)
        print("searching:", url)
        
        time.sleep(0.5)
        
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        
        page_text = driver.find_element(By.TAG_NAME, 'body').text
        
        if "Mail" in page_text or "mail" in page_text or "contact" in page_text or "コンタクト" in page_text or  "問い合わせ" in page_text or "form" in page_text or  "フォーム" in page_text or "メール" in page_text or "address" in page_text or "mail" in page_text or "@" in page_text:
            search_urls[base_url].append(url)
            print("メールアドレスやお問い合わせフォームに関わる単語を見つけました。", url)
            if len(search_urls[base_url]) > 2:
                return True
        
        links = get_all_links(driver)
        for link in links:
            full_url = urljoin(base_url, link)
            if urlparse(full_url).netloc == urlparse(base_url).netloc:  # 同じドメイン内のリンクのみ追跡
                if check_mail_in_page(full_url, visited, base_url, counter, max_depth - 1):
                    return True
    
    except Exception as e:
        print(f"Error fetching {url}: {e}")
    
    finally:
        driver.quit()
    
    return False

# google api を用いて50件の
def google_search(query, api_key, cse_id, num_results=30):
    service = build("customsearch", "v1", developerKey=api_key)
    results = []
    for start_index in range(1, num_results, 10):  # start_indexを1, 11, 21, 31, 41に設定
        res = service.cse().list(q=query, cx=cse_id, num=10, start=start_index).execute()
        results.extend(res.get('items', []))
    return results


for query in data_queries:
    results = google_search(query, API_KEY, SEARCH_ENGINE_ID)
    urls = [item['link'] for item in results]
    # urls = ["https://www.re-idea.jp",]
    search_urls = {url: [] for url in urls}

    # 各URLをチェック
    visited_links = set()
    for url in list(search_urls.keys()):
        counter = 0
        print(f"\n--- Checking {url} start ---")
        check_mail_in_page(url, visited_links, url, counter)

        result = [query, url]
        for output in search_urls[url]:
            result.append(output)
        print(result)
        spreadSheet_wb.append_row(result)

    print("\n\n検索クエリ:", query)
    pprint.pprint(search_urls)



