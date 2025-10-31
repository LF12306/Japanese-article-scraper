import os
import json
import time
import requests
import feedparser
import schedule
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from dateutil.parser import isoparse
import random

# 引入Selenium相关模块
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

# --- 配置区 ---

# 代理服务器设置
PROXY_HOST = "127.0.0.1"
PROXY_PORT = 7897
PROXY_STRING = f"{PROXY_HOST}:{PROXY_PORT}"

# 数据和调试文件目录
DATA_DIR = 'data'
DEBUG_DIR = 'debug_html'

# 已抓取链接的记录文件
SCRAPED_LINKS_FILE = 'scraped_links.json'

# RSS源和URL
NHK_RSS_URLS = [
    'https://news.web.nhk/n-data/conf/na/rss/cat0.xml',
    'https://news.web.nhk/n-data/conf/na/rss/cat1.xml',
    'https://news.web.nhk/n-data/conf/na/rss/cat2.xml',
    'https://news.web.nhk/n-data/conf/na/rss/cat5.xml',
]
JST_RSS_URL = 'https://www.jst.go.jp/rss/press.xml'
HATENA_BASE_URL = 'https://hatena.blog/staff_picks'

# --- 核心功能函数 ---
def setup_directories():
    os.makedirs(os.path.join(DATA_DIR, 'NHK'), exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, 'JST'), exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, 'Hatena-Blog'), exist_ok=True)
    os.makedirs(DEBUG_DIR, exist_ok=True)
    print("数据和调试目录已准备就绪。")

def save_failed_html(source, link, content):
    try:
        filename = f"{source}_failed_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        filepath = os.path.join(DEBUG_DIR, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  [DEBUG] 无法提取内容。原始HTML已保存到: {filepath}")
    except Exception as e:
        print(f"  [DEBUG] 保存HTML文件失败: {e}")

def load_scraped_links():
    try:
        with open(SCRAPED_LINKS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    
    thirty_days_ago = datetime.now() - timedelta(days=30)
    cleaned_data = {
        url: timestamp for url, timestamp in data.items()
        if datetime.fromisoformat(timestamp) > thirty_days_ago
    }
    
    if len(data) != len(cleaned_data):
        save_scraped_links(cleaned_data)
    return cleaned_data

def save_scraped_links(scraped_links):
    with open(SCRAPED_LINKS_FILE, 'w', encoding='utf-8') as f:
        json.dump(scraped_links, f, indent=4, ensure_ascii=False)

def get_session():
    session = requests.Session()
    session.proxies = {'http': f'http://{PROXY_STRING}', 'https': f'http://{PROXY_STRING}'}
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    })
    return session

def write_to_file(source, date_str, title, content):
    # 修改：采用新的文件名规则 "来源-年-月-日.txt"
    file_name = f"{source}-{date_str}.txt"
    # 路径仍然包含 source 子目录
    file_path = os.path.join(DATA_DIR, source, file_name)
    with open(file_path, 'a', encoding='utf-8') as f:
        f.write(f"--- {title} ---\n\n")
        f.write(content.strip() + '\n\n')

# --- 各网站抓取器 ---

def scrape_nhk(scraped_links):
    """抓取NHK新闻 (处理弹窗，智能等待，并即时保存链接)"""
    print("\n--- 开始抓取 NHK 新闻 ---")
    new_articles_count = 0
    
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument(f'--proxy-server={PROXY_STRING}')
    chrome_options.add_argument("user-agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36'")
    chrome_options.add_argument('--log-level=3')

    webdriver_service = Service("./chromedriver.exe") 
    driver = None

    try:
        driver = webdriver.Chrome(service=webdriver_service, options=chrome_options)
        print("  [DEBUG] [Selenium] WebDriver 启动成功。")
        
        for url in NHK_RSS_URLS:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries:
                    link = entry.link
                    if link in scraped_links:
                        continue


                    # 【修改】在发现新文章的日志中加入链接
                    print(f"发现新NHK文章: {entry.title} ({link})")
                    
                    try:
                        driver.get(link)
                        
                        try:
                            popup_wait = WebDriverWait(driver, 5)
                            confirm_button_xpath = "//button[contains(text(), '確認しました')]"
                            confirm_button = popup_wait.until(EC.element_to_be_clickable((By.XPATH, confirm_button_xpath)))
                            confirm_button.click()
                            time.sleep(1)
                        except TimeoutException:
                            pass # 没有弹窗则忽略
                        
                        content_selector = "p._1i1d7sh2"
                        
                        # --- 修改开始 ---
                        # 步骤1: 等待至少一个内容元素出现，确认页面加载
                        try:
                            WebDriverWait(driver, 15).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, content_selector))
                            )
                        except TimeoutException:
                            # 如果连一个内容元素都找不到，说明是视频或空页面
                            print(f"  [INFO] 未找到主要内容（可能是视频），标记为已读并跳过: {entry.title}")
                            scraped_links[link] = datetime.now().isoformat()
                            save_scraped_links(scraped_links)
                            save_failed_html('NHK_NoContent', link, driver.page_source)
                            continue # 继续处理下一篇文章

                        # 步骤2 & 3: 获取所有段落，如果数量<=1，则为简报，标记后跳过
                        page_html = driver.page_source
                        soup = BeautifulSoup(page_html, 'lxml')
                        paragraphs = soup.select(content_selector)

                        if len(paragraphs) <= 1:
                            print(f"  [INFO] 检测到简报文章 (段落数 <= 1)，标记为已读并跳过: {entry.title}")
                            scraped_links[link] = datetime.now().isoformat()
                            save_scraped_links(scraped_links)
                            continue # 继续处理下一篇文章
                        
                        # 步骤4: 如果段落 > 1，正常处理
                        content = '\n'.join([p.get_text(strip=True) for p in paragraphs])
                        # --- 修改结束 ---

                        if not content.strip():
                            print(f"  [WARNING] 在 {link} 提取内容为空，标记为已读并跳过。")
                            scraped_links[link] = datetime.now().isoformat()
                            save_scraped_links(scraped_links)
                            save_failed_html('NHK_Empty', link, page_html)
                            continue

                        pub_date = datetime(*entry.published_parsed[:6]).strftime('%Y-%m-%d')
                        file_name = f"NHK-{pub_date}.txt"
                        write_to_file('NHK', pub_date, entry.title, content)
                        
                        scraped_links[link] = datetime.now().isoformat()
                        save_scraped_links(scraped_links)
                        print(f"  [SUCCESS] 已成功抓取并保存链接: {entry.title}")
                        
                        new_articles_count += 1
                        time.sleep(2)

                    except Exception as e:
                        print(f"  [ERROR] [Selenium] 处理NHK文章时发生未知错误: {link}, 错误: {e}")
                        try:
                           save_failed_html('NHK_UnknownError', link, driver.page_source)
                        except Exception as save_e:
                           print(f"  [DEBUG] 保存HTML调试文件失败: {save_e}")
                    
            except Exception as e:
                print(f"  [ERROR] 解析NHK RSS源失败: {url}, 错误: {e}")
    
    finally:
        if driver:
            driver.quit()
            print("  [DEBUG] [Selenium] WebDriver已关闭。")

    print(f"--- NHK 新闻抓取完成，新增 {new_articles_count} 篇文章。 ---")


def scrape_jst(session, scraped_links):
    """抓取JST新闻，并即时保存链接"""
    print("\n--- 开始抓取 JST 新闻公告 ---")
    new_articles_count = 0
    try:
        feed = feedparser.parse(JST_RSS_URL)
        for entry in feed.entries:
            link = entry.link

            # --- 修改开始 ---
            # 检查是否为总览页链接，如果是则直接跳过
            if link == 'https://www.jst.go.jp/pr/':
                print(f"  [INFO] 跳过JST新闻总览页: {link}")
                continue
            # --- 修改结束 ---

            if link in scraped_links:
                continue
            
            # 【修改】在日志中加入链接
            print(f"发现新JST文章: {entry.title} ({link})")

            try:
                response = session.get(link, timeout=15)
                response.raise_for_status()
                soup = BeautifulSoup(response.content, 'lxml')
                content_section = soup.find('section', class_='inr')
                if not content_section:
                    print(f"  [WARNING] 在 {link} 未找到 'inr' 内容区域，跳过。")
                    save_failed_html('JST', link, response.text)
                    continue
                
                unwanted_div = content_section.find('div', class_='pr_boxDesign1 border-dashed')
                if unwanted_div:
                    unwanted_div.decompose()

                content = content_section.get_text(strip=True, separator='\n')
                
                if not content.strip():
                    print(f"  [WARNING] 在 {link} 提取内容为空，跳过。")
                    save_failed_html('JST', link, response.text)
                    continue
                
                pub_date = datetime(*entry.published_parsed[:6]).strftime('%Y-%m-%d')
                write_to_file('JST', pub_date, entry.title, content)
                
                scraped_links[link] = datetime.now().isoformat()
                save_scraped_links(scraped_links)
                # 【修改】在日志中加入链接
                print(f"  [SUCCESS] 已成功抓取并保存链接: {entry.title} ({link})")

                new_articles_count += 1
            except requests.RequestException as e:
                print(f"  [ERROR] 抓取JST文章失败: {link}, 错误: {e}")
            except Exception as e:
                print(f"  [ERROR] 处理JST文章时发生未知错误: {link}, 错误: {e}")
            time.sleep(1)

    except Exception as e:
        print(f"  [ERROR] 解析JST RSS源失败: {JST_RSS_URL}, 错误: {e}")
    print(f"--- JST 新闻公告抓取完成，新增 {new_articles_count} 篇文章。 ---")
    


def scrape_hatena(session, scraped_links):
    """抓取Hatena Blog，并即时保存链接（包含随机延迟与指数退避重试以减速爬取）"""
    print("\n--- 开始抓取 Hatena Blog 精选文章 ---")
    new_articles_count = 0
    now = datetime.now()
    list_url = f"{HATENA_BASE_URL}/{now.year}/{now.month:02d}"

    # 减速与重试参数
    MIN_DELAY = 3.5        # 每次请求最小等待（秒）
    MAX_DELAY = 10.0        # 每次请求最大等待（秒）
    MAX_RETRIES = 4        # 最大重试次数
    BACKOFF_FACTOR = 2.0   # 指数退避因子

    def fetch_with_backoff(url, timeout=20):
        delay = MIN_DELAY
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = session.get(url, timeout=timeout)
                # 如果遇到 429 或 5xx，触发重试
                if resp.status_code == 429 or 500 <= resp.status_code < 600:
                    wait = delay * (BACKOFF_FACTOR ** (attempt - 1)) + random.uniform(0, 0.5)
                    print(f"  [WARN] {url} 返回 {resp.status_code}，第{attempt}次重试，将等待 {wait:.1f}s")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp
            except requests.RequestException as e:
                # 网络或超时等错误也进行退避重试
                if attempt == MAX_RETRIES:
                    raise
                wait = delay * (BACKOFF_FACTOR ** (attempt - 1)) + random.uniform(0, 0.5)
                print(f"  [WARN] 请求失败 ({e})，第{attempt}次重试，将等待 {wait:.1f}s")
                time.sleep(wait)
        raise requests.RequestException(f"无法获取：{url}（重试耗尽）")

    try:
        list_response = fetch_with_backoff(list_url, timeout=20)
        list_soup = BeautifulSoup(list_response.content, 'lxml')
        articles = list_soup.find_all('div', class_='gtm-click-measurement-target')

        for article in articles:
            link_tag = article.find('a', class_='entry-link')
            title_tag = article.find('h3', class_='entry-title')
            if not link_tag or not title_tag or not link_tag.get('href'): continue

            link = link_tag['href']
            title = title_tag.get_text(strip=True)
            if link in scraped_links: continue

            print(f"发现新Hatena文章: {title}")

            # 在每篇文章请求前加入随机延迟以减速
            sleep_time = random.uniform(MIN_DELAY, MAX_DELAY)
            print(f"  [DELAY] 等待 {sleep_time:.1f}s 后请求文章页面...")
            time.sleep(sleep_time)

            try:
                response = fetch_with_backoff(link, timeout=15)
                soup = BeautifulSoup(response.content, 'lxml')
                content_div = soup.find('div', class_='entry-content')
                if not content_div:
                    print(f"  [WARNING] 在 {link} 未找到 'entry-content'，跳过。")
                    save_failed_html('Hatena', link, response.text)
                    continue

                content = content_div.get_text(strip=True, separator='\n')

                if not content.strip():
                    print(f"  [WARNING] 在 {link} 提取内容为空，跳过。")
                    save_failed_html('Hatena', link, response.text)
                    continue

                date_tag = soup.find('time', attrs={'datetime': True})
                if date_tag:
                    pub_date = isoparse(date_tag['datetime']).strftime('%Y-%m-%d')
                else:
                    pub_date = now.strftime('%Y-%m-%d')

                write_to_file('Hatena-Blog', pub_date, title, content)

                # 【即时保存】
                scraped_links[link] = datetime.now().isoformat()
                save_scraped_links(scraped_links)
                print(f"  [SUCCESS] 已成功抓取并保存链接: {title}")

                new_articles_count += 1
            except requests.RequestException as e:
                print(f"  [ERROR] 抓取Hatena文章失败: {link}, 错误: {e}")
            except Exception as e:
                print(f"  [ERROR] 处理Hatena文章时发生未知错误: {link}, 错误: {e}")
            # 额外短延迟，避免密集请求
            time.sleep(random.uniform(0.5, 1.2))

    except requests.RequestException as e:
        print(f"  [ERROR] 访问Hatena文章列表失败: {list_url}, 错误: {e}")
    except Exception as e:
        print(f"  [ERROR] 处理Hatena文章列表时发生未知错误: {list_url}, 错误: {e}")
    print(f"--- Hatena Blog 抓取完成，新增 {new_articles_count} 篇文章。 ---")


def run_scraper():
    """主执行函数，协调所有抓取任务"""
    print(f"\n{'='*50}")
    print(f"开始新一轮抓取任务 @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")

    scraped_links = load_scraped_links()
    session = get_session()
    
    scrape_nhk(scraped_links) 
    scrape_jst(session, scraped_links)
    scrape_hatena(session, scraped_links)
    
    # 【已移除】不再需要在这里统一保存
    # save_scraped_links(scraped_links)

    print(f"\n{'='*50}")
    print("本轮抓取任务完成。")
    print(f"下次任务将在30分钟后运行...")
    print(f"{'='*50}\n")


# --- 程序入口和调度 ---
if __name__ == "__main__":
    setup_directories()
    run_scraper() 
    schedule.every(30).minutes.do(run_scraper)
    print("调度器已启动，每30分钟执行一次抓取任务。按 Ctrl+C 退出。")
    while True:
        schedule.run_pending()
        time.sleep(1)