import arxiv
from notion_client import Client
import os
import time
import requests
import json
import re
import random
from datetime import datetime

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# =========================================================
# 全局配置
# =========================================================
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
NOTION_REPORT_DB_ID = os.getenv("NOTION_REPORT_DB_ID")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

API_URL = "https://api.deepseek.com/v1/chat/completions"
MODEL_NAME = "deepseek-chat"

notion = Client(auth=NOTION_TOKEN)

# =========================================================
# Prompt（超级精简版）
# =========================================================
TAG_EXTRACT_PROMPT = """
你现在只能输出关键词。
不要任何标点符号。
不要任何引号。
不要任何解释。
不要任何格式。
不要换行。
只输出5-15个关键词，用空格分隔。

从以下论文摘要中提取最核心的学术关键词：
{abstract_content}
"""

SUMMARY_ACADEMIC_PROMPT = """
请用极简方式总结论文，控制在3句话以内：
论文解决什么问题 → 用了什么方法 → 结论是什么

论文摘要：
{abstract_content}
"""

# =========================================================
# 工具函数
# =========================================================
def clean_text(text):
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def random_sleep(min_sec=3, max_sec=6):
    sleep_time = random.uniform(min_sec, max_sec)
    print(f"休眠 {sleep_time:.1f} 秒...")
    time.sleep(sleep_time)

# =========================================================
# 请求重试
# =========================================================
def build_request_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    return session

session = build_request_session()

# =========================================================
# AI 调用
# =========================================================
def call_ai_api(prompt_text):
    api_key = DEEPSEEK_API_KEY or os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        print("缺少 API Key")
        return None

    payload = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": prompt_text}],
        "temperature": 0.1
    }

    for retry in range(3):
        try:
            res = session.post(
                API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=30
            )
            res.raise_for_status()
            result = res.json()
            random_sleep(2, 4)
            return result["choices"][0]["message"]["content"]

        except Exception as e:
            wait = (retry + 1) * 5
            print(f"AI 调用失败，{wait} 秒后重试：{e}")
            time.sleep(wait)

    return None

# =========================================================
# 每天抓取不同论文（核心修复）
# =========================================================
def fetch_vla_papers():
    print("===== 开始抓取每日最新 5 篇论文 =====")
    target = 5
    new_papers = []

    try:
        client = arxiv.Client(
            page_size=50,
            delay_seconds=3,
            num_retries=2
        )

        # 只查最新的 100 篇（足够找到 5 篇新的了）
        search = arxiv.Search(
            query='cat:cs.RO AND (vision language action OR embodied ai OR robot learning OR world model)',
            max_results=100,  # 只扫描最新100篇，绝对安全
            sort_by=arxiv.SortCriterion.SubmittedDate
        )

        # 从最新开始检查，找到 5 篇新的就停
        for paper in client.results(search):
            title = clean_text(paper.title)
            
            if not check_paper_exists(title):
                new_papers.append(paper)
                print(f"[{len(new_papers)}/{target}] 新论文：{title}")

                if len(new_papers) >= target:
                    break

        print(f"\n今日获取完成：共 {len(new_papers)} 篇全新最新论文")
        return new_papers

    except Exception as e:
        print(f"抓取失败：{e}")
        return []

# =========================================================
# Notion 去重
# =========================================================
def check_paper_exists(title):
    try:
        res = notion.databases.query(
            database_id=NOTION_DATABASE_ID,
            filter={"property": "Name", "title": {"equals": title}}
        )
        return len(res["results"]) > 0
    except:
        return False

# =========================================================
# 标签提取
# =========================================================
def extract_ai_tags(abstract):
    try:
        result = call_ai_api(TAG_EXTRACT_PROMPT.format(abstract_content=abstract))
        if not result:
            return []

        cleaned = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9\s]", "", result)
        tags = cleaned.split()
        valid = []

        for t in tags:
            t = t.strip()
            if 2 <= len(t) <= 40:
                valid.append({"name": t})

        return list({v["name"]: v for v in valid}.values())[:10]

    except:
        return []

# =========================================================
# 极简总结
# =========================================================
def get_academic_summary(abstract):
    res = call_ai_api(SUMMARY_ACADEMIC_PROMPT.format(abstract_content=abstract))
    return res[:500] if res else "总结失败"

# =========================================================
# 写入 Notion
# =========================================================
def write_paper_to_notion(paper):
    try:
        title = clean_text(paper.title)
        authors = ", ".join([a.name for a in paper.authors])
        abstract = clean_text(paper.summary)
        pdf_url = paper.pdf_url

        if check_paper_exists(title):
            print(f"[跳过] 已存在：{title}")
            return

        print(f"处理论文：{title}")
        tags = extract_ai_tags(abstract)
        summary = get_academic_summary(abstract)

        MAX = 800

        notion.pages.create(
            parent={"database_id": NOTION_DATABASE_ID},
            properties={
                "Name": {"title": [{"text": {"content": title[:200]}}]},
                "Authors": {"rich_text": [{"text": {"content": authors[:MAX]}}]},
                "Abstract": {"rich_text": [{"text": {"content": abstract[:MAX]}}]},
                "PDF Link": {"url": pdf_url},
                "Status": {"select": {"name": "To Read"}},
                "Tags": {"multi_select": tags if tags else []},
                "Summary": {"rich_text": [{"text": {"content": summary[:500]}}]}
            }
        )
        print(f"[完成] {title}")
        random_sleep(2, 4)

    except Exception as e:
        print(f"写入失败：{e}")

# =========================================================
# 生成极简日报（超级短）
# =========================================================
def create_daily_research_report(papers):
    print("===== 生成极简日报 =====")
    if not NOTION_REPORT_DB_ID:
        print("未配置日报数据库")
        return

    content = ""
    for idx, p in enumerate(papers):
        title = clean_text(p.title)
        content += f"[{idx+1}] {title}\n"

    prompt = f"""
今天论文列表：
{content}

请用100字内极简总结今日主题与趋势。
"""

    report = call_ai_api(prompt) or "日报生成失败"
    report = report[:300]

    try:
        notion.pages.create(
            parent={"database_id": NOTION_REPORT_DB_ID},
            properties={
                "Name": {"title": [{"text": {"content": f"VLA日报 {time.strftime('%Y-%m-%d')}"}}]},
                "Date": {"date": {"start": time.strftime('%Y-%m-%d')}},
                "Content": {"rich_text": [{"text": {"content": report}}]}
            }
        )
        print("日报写入成功")
    except Exception as e:
        print(f"日报写入失败：{e}")

# =========================================================
# 主程序
# =========================================================
if __name__ == "__main__":
    print("===== VLA 每日论文助手 =====")
    papers = fetch_vla_papers()

    if not papers:
        print("未获取到论文")
        exit()

    for paper in papers:
        write_paper_to_notion(paper)
        random_sleep(5, 8)

    create_daily_research_report(papers)
    print("===== 执行完成 =====")
