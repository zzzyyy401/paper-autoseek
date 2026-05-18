import arxiv
from notion_client import Client
import os
import time

# ====================== 配置 ======================
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
# ==================================================

notion = Client(auth=NOTION_TOKEN)

# 获取最新论文（修复 429 + 新版写法）
def get_latest_papers():
    print("开始爬取最新 VLA 论文...")
    
    client = arxiv.Client()
    search = arxiv.Search(
        query="Vision-Language-Action OR VLA",
        max_results=3,
        sort_by=arxiv.SortCriterion.SubmittedDate
    )

    # 新版调用方式，不会触发 429
    results = list(client.results(search))
    time.sleep(1)
    return results

# 判断论文是否已存在 Notion
def is_paper_exist(title):
    try:
        res = notion.databases.query(
            database_id=NOTION_DATABASE_ID,
            filter={"property": "Name", "title": {"equals": title}}
        )
        return len(res["results"]) > 0
    except:
        return False

# 写入 Notion
def add_to_notion(paper):
    title = paper.title
    authors = ", ".join([a.name for a in paper.authors])
    abstract = paper.summary.replace("\n", " ")
    url = paper.pdf_url

    if is_paper_exist(title):
        print(f"✅ 已存在：{title}")
        return

    print(f"📝 添加论文：{title}")

    notion.pages.create(
        parent={"database_id": NOTION_DATABASE_ID},
        properties={
            "Name": {"title": [{"text": {"content": title}}]},
            "Authors": {"rich_text": [{"text": {"content": authors}}]},
            "Abstract": {"rich_text": [{"text": {"content": abstract}}]},
            "PDF Link": {"url": url},
            "Status": {"select": {"name": "To Read"}},
        }
    )

# 主程序
if __name__ == "__main__":
    papers = get_latest_papers()
    for p in papers:
        add_to_notion(p)
