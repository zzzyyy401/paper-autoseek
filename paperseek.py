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

# DeepSeek API
API_URL = "https://api.deepseek.com/v1/chat/completions"

HEADERS = {
    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
    "Content-Type": "application/json"
}

MODEL_NAME = "deepseek-chat"

# 初始化 Notion
notion = Client(auth=NOTION_TOKEN)

# =========================================================
# Prompt
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
你是一位深耕具身智能（Embodied AI）、VLA、世界模型与机器人学的研究者。

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
# 通用工具
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
# Requests Retry Session
# =========================================================

def build_request_session():

    session = requests.Session()

    retry_strategy = Retry(

        total=5,

        backoff_factor=2,

        status_forcelist=[
            429,
            500,
            502,
            503,
            504
        ],

        allowed_methods=["POST"]
    )

    adapter = HTTPAdapter(
        max_retries=retry_strategy
    )

    session.mount("https://", adapter)

    return session


session = build_request_session()

# =========================================================
# DeepSeek API（已修复：兼容 DASHSCOPE_API_KEY）
# =========================================================

def call_ai_api(prompt_text):
    # 同时支持两个环境变量名，兼容旧配置
    api_key = DEEPSEEK_API_KEY or os.getenv("DASHSCOPE_API_KEY")

    if not api_key:
        print("缺少 DEEPSEEK_API_KEY 或 DASHSCOPE_API_KEY")
        return None

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "user",
                "content": prompt_text
            }
        ],
        "temperature": 0.1
    }

    for retry in range(5):
        try:
            response = session.post(
                API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=60
            )

            response.raise_for_status()
            result = response.json()

            # DeepSeek 限流保护
            random_sleep(5, 10)

            return result["choices"][0]["message"]["content"]

        except Exception as e:
            wait_time = (retry + 1) * 10
            print(f"""
AI 调用失败:
{e}

{wait_time} 秒后重试...
""")
            time.sleep(wait_time)

    return None

# =========================================================
# arXiv 抓取
# =========================================================

def fetch_vla_papers():

    print("===== 开始抓取最新 VLA / Embodied AI 论文 =====")

    all_papers = []

    for retry in range(5):

        try:

            # 官方建议：
            # 不要高频请求
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

            # 不要 list(results)
            for idx, paper in enumerate(client.results(search)):

                try:

                    print(f"""
==================================================
[{idx+1}/10]

标题:
{paper.title}
==================================================
""")

                    all_papers.append(paper)

                    # 核心限流
                    random_sleep(8, 15)

                except Exception as e:

                    print(f"单篇论文处理失败: {e}")

                    continue

            print(f"""
===== 抓取完成 =====
成功获取 {len(all_papers)} 篇论文
""")

            return all_papers

        except Exception as e:

            wait_time = (retry + 1) * 20

            print(f"""
===== arXiv 抓取失败 =====

错误:
{e}

{wait_time} 秒后重试...
""")

            time.sleep(wait_time)

    print("===== arXiv 连续失败 =====")

    return []

# =========================================================
# Notion 去重
# =========================================================

def check_paper_exists(title):

    try:

        result = notion.databases.query(

            database_id=NOTION_DATABASE_ID,

            filter={
                "property": "Name",
                "title": {
                    "equals": title
                }
            }
        )

        return len(result["results"]) > 0

    except Exception as e:

        print(f"Notion 去重失败: {e}")

        return False

# =========================================================
# AI 标签提取（已修复：处理所有格式问题）
# =========================================================

def extract_ai_tags(abstract):
    try:
        prompt = TAG_EXTRACT_PROMPT.format(
            abstract_content=abstract
        )

        result = call_ai_api(prompt)

        if not result:
            return []

        print(f"AI返回的关键词: {repr(result)}")

        # 终极清理：去掉所有非中文、非英文、非数字的字符
        cleaned = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9\s]", "", result)
        
        # 按空格分割
        tags = cleaned.split()
        
        valid_tags = []
        for tag in tags:
            tag = tag.strip()
            # 过滤掉太短和太长的标签
            if len(tag) < 2 or len(tag) > 50:
                continue
            valid_tags.append({"name": tag})
        
        # 去重并返回前15个
        return list({v["name"]: v for v in valid_tags}.values())[:15]

    except Exception as e:
        print(f"标签提取跳过：{e}")
        return []
# =========================================================
# AI 总结
# =========================================================

def get_academic_summary(abstract):

    prompt = SUMMARY_ACADEMIC_PROMPT.format(
        abstract_content=abstract
    )

    result = call_ai_api(prompt)

    if not result:

        return "AI 总结生成失败"

    return result[:1800]

# =========================================================
# 写入论文到 Notion
# =========================================================

def write_paper_to_notion(paper):
    try:
        title = clean_text(paper.title)
        authors = ", ".join([
            author.name
            for author in paper.authors
        ])
        abstract = clean_text(paper.summary)
        pdf_url = paper.pdf_url

        # 去重
        if check_paper_exists(title):
            print(f"[跳过] 已存在: {title}")
            return

        print(f"""
==================================================
开始处理论文:

{title}
==================================================
""")

        # AI 分析
        tags = extract_ai_tags(abstract)
        summary = get_academic_summary(abstract)

        # 严格遵守Notion长度限制（留100字符余量）
        MAX_RICH_TEXT_LENGTH = 1900

        # 写入 Notion
        notion.pages.create(
            parent={
                "database_id": NOTION_DATABASE_ID
            },
            properties={
                "Name": {
                    "title": [
                        {
                            "text": {
                                "content": title[:200]  # 标题最多200字符
                            }
                        }
                    ]
                },
                "Authors": {
                    "rich_text": [
                        {
                            "text": {
                                "content": authors[:MAX_RICH_TEXT_LENGTH]
                            }
                        }
                    ]
                },
                "Abstract": {
                    "rich_text": [
                        {
                            "text": {
                                "content": abstract[:MAX_RICH_TEXT_LENGTH]
                            }
                        }
                    ]
                },
                "PDF Link": {
                    "url": pdf_url
                },
                "Status": {
                    "select": {
                        "name": "To Read"
                    }
                },
                "Tags": {
                    "multi_select": tags if tags else []
                },
                "Summary": {
                    "rich_text": [
                        {
                            "text": {
                                "content": summary[:MAX_RICH_TEXT_LENGTH]
                            }
                        }
                    ]
                }
            }
        )

        print(f"[完成] {title}")
        print(f"提取到的标签: {[t['name'] for t in tags]}")

        # Notion 限流保护
        random_sleep(3, 6)

    except Exception as e:
        print(f"""
写入论文失败:

{e}
""")
        # 即使写入失败，也继续处理下一篇
        return
==================================================
开始处理论文:

{title}
==================================================
""")

        # AI 分析
        tags = extract_ai_tags(abstract)

        summary = get_academic_summary(abstract)

        # 写入 Notion
        notion.pages.create(

            parent={
                "database_id": NOTION_DATABASE_ID
            },

            properties={

                "Name": {
                    "title": [
                        {
                            "text": {
                                "content": title[:200]
                            }
                        }
                    ]
                },

                "Authors": {
                    "rich_text": [
                        {
                            "text": {
                                "content": authors[:1800]
                            }
                        }
                    ]
                },

                "Abstract": {
                    "rich_text": [
                        {
                            "text": {
                                "content": abstract[:1800]
                            }
                        }
                    ]
                },

                "PDF Link": {
                    "url": pdf_url
                },

                "Status": {
                    "select": {
                        "name": "To Read"
                    }
                },

                "Tags": {
                    "multi_select": tags[:20]
                },

                "Summary": {
                    "rich_text": [
                        {
                            "text": {
                                "content": summary[:1800]
                            }
                        }
                    ]
                }
            }
        )

        print(f"[完成] {title}")

        # Notion 限流保护
        random_sleep(3, 6)

    except Exception as e:

        print(f"""
写入论文失败:

{e}
""")

# =========================================================
# 生成日报
# =========================================================

def create_daily_research_report(papers):

    print("""
==================================================
开始生成每日学术日报
==================================================
""")

    total_content = ""

    for idx, paper in enumerate(papers):

        title = clean_text(paper.title)

        abstract = clean_text(paper.summary)

        total_content += f"""
【论文 {idx+1}】

标题：
{title}

摘要：
{abstract[:500]}

"""

    report_prompt = f"""
请基于以下最新具身智能/VLA/机器人论文摘要：

1. 总结今日研究热点
2. 总结主流技术趋势
3. 总结重要创新方向
4. 分析未来发展趋势

要求：
- 学术化
- 简洁
- Markdown 输出

论文集合：
{total_content}
"""

    report = call_ai_api(report_prompt)

    if not report:

        report = "今日日报生成失败"

    report = report[:1900]

    try:

        notion.pages.create(

            parent={
                "database_id": NOTION_REPORT_DB_ID
            },

            properties={

                # 必须与你数据库字段名一致
                "Name": {
                    "title": [
                        {
                            "text": {
                                "content": f"VLA 学术日报 {time.strftime('%Y-%m-%d')}"
                            }
                        }
                    ]
                },

                "Date": {
                    "date": {
                        "start": time.strftime("%Y-%m-%d")
                    }
                },

                "Content": {
                    "rich_text": [
                        {
                            "text": {
                                "content": report
                            }
                        }
                    ]
                }
            }
        )

        print("""
==================================================
学术日报写入成功
==================================================
""")

    except Exception as e:

        print(f"""
日报写入失败:

{e}
""")

# =========================================================
# 主入口
# =========================================================

if __name__ == "__main__":

    print("""
==================================================
VLA 学术助手启动
==================================================
""")

    # 启动前缓冲
    random_sleep(5, 10)

    papers = fetch_vla_papers()

    if not papers:

        print("未获取到论文")

        exit()

    # 每篇论文处理
    for idx, paper in enumerate(papers):

        print(f"""
==================================================
开始处理第 {idx+1} 篇论文
==================================================
""")

        write_paper_to_notion(paper)

        # 每篇论文之间额外限流
        random_sleep(10, 20)

    # 生成日报
    create_daily_research_report(papers)

    print("""
==================================================
全部执行完成
==================================================
""")
