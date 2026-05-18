import arxiv
from notion_client import Client
import os
import time
import requests
import json
import re
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# =========================================================
# 全局配置
# =========================================================

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
NOTION_REPORT_DB_ID = os.getenv("NOTION_REPORT_DB_ID")

# 建议改名，不要再叫 DASHSCOPE_API_KEY
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
你是一位专注于具身智能（Embodied AI）、视觉-语言-动作模型（VLA）、世界模型（World Models）及机器人学领域的资深学术分析师。

请仔细阅读以下论文摘要，并从中系统性地提炼关键词。

输出要求：
仅输出 JSON，不允许任何解释。

格式：
{
  "核心任务": [],
  "方法范式": [],
  "关键模块/机制": [],
  "实验场景/平台": [],
  "评价维度": []
}

论文摘要：
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
# 工具函数
# =========================================================

def clean_text(text):
    """
    清洗文本，避免特殊字符影响 API
    """

    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def build_request_session():
    """
    构建带 retry 的 requests session
    """

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
# DeepSeek API
# =========================================================

def call_ai_api(prompt_text):

    if not DEEPSEEK_API_KEY:
        print("缺少 DEEPSEEK_API_KEY")
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

    try:

        response = session.post(
            API_URL,
            headers=HEADERS,
            json=payload,
            timeout=60
        )

        response.raise_for_status()

        result = response.json()

        return result["choices"][0]["message"]["content"]

    except Exception as e:

        print(f"AI 调用失败: {e}")

        return None

# =========================================================
# arXiv 抓取
# =========================================================

def fetch_vla_papers():

    print("===== 开始抓取最新 VLA / Embodied AI 论文 =====")

    # 工业级 retry
    for retry in range(5):

        try:

            client = arxiv.Client(
                page_size=10,
                delay_seconds=3,
                num_retries=5
            )

            # 更合理的 query
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
                max_results=10,
                sort_by=arxiv.SortCriterion.SubmittedDate
            )

            papers = list(client.results(search))

            print(f"===== 成功获取 {len(papers)} 篇论文 =====")

            return papers

        except Exception as e:

            print(f"第 {retry+1} 次 arXiv 抓取失败: {e}")

            time.sleep(10)

    print("===== arXiv 连续失败 =====")

    return []

# =========================================================
# Notion 工具
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
# AI 标签提取
# =========================================================

def extract_ai_tags(abstract):

    prompt = TAG_EXTRACT_PROMPT.format(
        abstract_content=abstract
    )

    result = call_ai_api(prompt)

    if not result:
        return []

    try:

        result = result.strip()

        # 防止 AI 输出 markdown
        result = result.replace("```json", "")
        result = result.replace("```", "")

        data = json.loads(result)

        all_tags = []

        for value in data.values():

            if isinstance(value, list):

                all_tags.extend(value)

        # 去重
        all_tags = list(set(all_tags))

        return [
            {"name": tag[:100]}
            for tag in all_tags
            if tag.strip()
        ]

    except Exception as e:

        print(f"标签解析失败: {e}")

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
# 写入论文
# =========================================================

def write_paper_to_notion(paper):

    try:

        title = clean_text(paper.title)

        authors = ", ".join(
            [author.name for author in paper.authors]
        )

        abstract = clean_text(paper.summary)

        pdf_url = paper.pdf_url

        # 去重
        if check_paper_exists(title):

            print(f"[跳过] 已存在: {title}")

            return

        print(f"[处理中] {title}")

        # AI
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
        time.sleep(2)

    except Exception as e:

        print(f"写入论文失败: {e}")

# =========================================================
# 生成日报
# =========================================================

def create_daily_research_report(papers):

    print("===== 开始生成每日学术日报 =====")

    total_content = ""

    for idx, paper in enumerate(papers):

        title = clean_text(paper.title)

        abstract = clean_text(paper.summary)

        total_content += f"""
【论文 {idx+1}】
标题：{title}

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

    report = report[:1800]

    try:

        notion.pages.create(

            parent={
                "database_id": NOTION_REPORT_DB_ID
            },

            properties={

                # 这里必须与你数据库列名完全一致
                "Name": {
                    "title": [
                        {
                            "text": {
                                "content": f"VLA 学术日报 {time.strftime('%Y-%m-%d')}"
                            }
                        }
                    ]
                },

                # 注意字段名
                "Date": {
                    "date": {
                        "start": time.strftime("%Y-%m-%d")
                    }
                },

                # 注意字段名
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

        print("===== 学术日报写入成功 =====")

    except Exception as e:

        print(f"日报写入失败: {e}")

# =========================================================
# 主入口
# =========================================================

if __name__ == "__main__":

    print("===== VLA 学术助手启动 =====")

    papers = fetch_vla_papers()

    if not papers:

        print("未获取到论文")

        exit()

    for paper in papers:

        write_paper_to_notion(paper)

    create_daily_research_report(papers)

    print("===== 全部执行完成 =====")
