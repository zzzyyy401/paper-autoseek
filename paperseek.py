import arxiv
from notion_client import Client
import os

# ====================== 【只需要改这2个参数】 ======================
NOTION_TOKEN = os.getenv("ntn_b68428829798UcYIW1WiKnjIKew43U6rMEkq8umPx7I5xQ")
NOTION_DATABASE_ID = os.getenv("364197de1ba38070b0d5fb513ac70ec2")
# ==================================================================

# 连接 Notion
notion = Client(auth=NOTION_TOKEN)

# 搜索 arXiv 论文
def get_latest_papers():
    print("开始爬取最新 VLA 论文...")
    search = arxiv.Search(
        query="cat:cs.RO AND (Vision-Language-Action OR VLA)",
        max_results=5,
        sort_by=arxiv.SortCriterion.SubmittedDate
    )
    return list(search.results())

# 判断论文是否已经存在
def is_paper_exist(title):
    try:
        response = notion.databases.query(
            database_id=NOTION_DATABASE_ID,
            filter={"property": "Name", "title": {"equals": title}}
        )
        return len(response["results"]) > 0
    except:
        return False

# 写入 Notion
def add_to_notion(paper):
    title = paper.title
    authors = ", ".join([a.name for a in paper.authors])
    abstract = paper.summary.replace("\n", " ")
    url = paper.pdf_url

    if is_paper_exist(title):
        print(f"已存在：{title}")
        return

    print(f"添加论文：{title}")

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