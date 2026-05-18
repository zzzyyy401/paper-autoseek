import arxiv
from notion_client import Client
import os
import time
import requests
import json
import re
import random

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
# Prompt（最稳定：纯关键词，无格式）
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
你是一位深耕具身智能、VLA、世界模型与机器人学的研究者。

请根据论文摘要生成专业学术总结。

要求：
1. 问题与动机
2. 核心方法
3. 关键创新
4. 实验验证
5. 局限与启示

输出 Markdown。

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

def random_sleep(min_sec=3, max_sec=8):
    sleep_time = random.uniform(min_sec, max_sec)
    print(f"休眠 {sleep_time:.1f} 秒...")
    time.sleep(sleep_time)

# =========================================================
# 请求重试
# =========================================================
def build_request_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=5,
        backoff_factor=2,
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

    for retry in range(5):
        try:
            res = session.post(
                API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=60
            )
            res.raise_for_status()
            result = res.json()
            random_sleep(5, 10)
            return result["choices"][0]["message"]["content"]

        except Exception as e:
            wait = (retry + 1) * 10
            print(f"AI 调用失败，{wait} 秒后重试：{e}")
            time.sleep(wait)

    return None

# =========================================================
# 抓取论文
# =========================================================
def fetch_vla_papers():
    print("===== 开始抓取论文 =====")
    all_papers = []

    for retry in range(5):
        try:
            client = arxiv.Client(
                page_size=5,
                delay_seconds=10,
                num_retries=5
            )
            search = arxiv.Search(
                query='''
                cat:cs.RO AND (
                    abs:"vision language action"
                    OR abs:"embodied ai"
                    OR abs:"robot learning"
                    OR abs:"diffusion policy"
                    OR abs:"world model"
                )
                ''',
                max_results=5,
                sort_by=arxiv.SortCriterion.SubmittedDate
            )

            for idx, paper in enumerate(client.results(search)):
                print(f"[{idx+1}/5] {paper.title}")
                all_papers.append(paper)
                random_sleep(8, 15)

            print(f"抓取完成，共 {len(all_papers)} 篇")
            return all_papers

        except Exception as e:
            wait = (retry + 1) * 20
            print(f"抓取失败，{wait} 秒后重试：{e}")
            time.sleep(wait)

    print("arXiv 连续失败")
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
# 标签提取（100% 不崩溃）
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
            if 2 <= len(t) <= 50:
                valid.append({"name": t})

        return list({v["name"]: v for v in valid}.values())[:15]

    except:
        return []

# =========================================================
# 总结生成
# =========================================================
def get_academic_summary(abstract):
    res = call_ai_api(SUMMARY_ACADEMIC_PROMPT.format(abstract_content=abstract))
    return res[:1900] if res else "AI 总结生成失败"

# =========================================================
# 写入 Notion（稳定、不报错）
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

        MAX = 1900

        notion.pages.create(
            parent={"database_id": NOTION_DATABASE_ID},
            properties={
                "Name": {"title": [{"text": {"content": title[:200]}}]},
                "Authors": {"rich_text": [{"text": {"content": authors[:MAX]}}]},
                "Abstract": {"rich_text": [{"text": {"content": abstract[:MAX]}}]},
                "PDF Link": {"url": pdf_url},
                "Status": {"select": {"name": "To Read"}},
                "Tags": {"multi_select": tags if tags else []},
                "Summary": {"rich_text": [{"text": {"content": summary[:MAX]}}]}
            }
        )
        print(f"[完成] {title}")
        random_sleep(3, 6)

    except Exception as e:
        print(f"写入失败：{e}")

# =========================================================
# 生成日报（已修复：无中文符号报错）
# =========================================================
def create_daily_research_report(papers):
    print("===== 开始生成日报 =====")
    if not NOTION_REPORT_DB_ID:
        print("未配置日报数据库")
        return

    content = ""
    for idx, p in enumerate(papers):
        title = clean_text(p.title)
        abstract = clean_text(p.summary)
        content += f"\n[论文 {idx+1}]\n标题：{title}\n摘要：{abstract[:500]}\n"

    prompt = f"""
请基于最新论文总结：
1. 研究热点
2. 技术趋势
3. 创新方向
4. 未来发展

论文：{content}
"""

    report = call_ai_api(prompt) or "日报生成失败"
    report = report[:1900]

    try:
        notion.pages.create(
            parent={"database_id": NOTION_REPORT_DB_ID},
            properties={
                "Name": {"title": [{"text": {"content": f"VLA日报 {time.strftime('%Y-%m-%d')}"}}]},
                "date": {"date": {"start": time.strftime('%Y-%m-%d')}},
                "content": {"rich_text": [{"text": {"content": report}}}
            }
        )
        print("日报写入成功")
    except Exception as e:
        print(f"日报写入失败：{e}")

# =========================================================
# 主程序
# =========================================================
if __name__ == "__main__":
    print("===== VLA 学术助手启动 =====")
    random_sleep(2, 4)
    papers = fetch_vla_papers()

    if not papers:
        print("未获取到论文")
        exit()

    for paper in papers:
        write_paper_to_notion(paper)
        random_sleep(10, 15)

    create_daily_research_report(papers)
    print("===== 全部执行完成 =====")
