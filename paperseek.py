import arxiv
from notion_client import Client
import os
import time
import requests
import json

# ====================== 全局配置 ======================
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
NOTION_REPORT_DB_ID = os.getenv("NOTION_REPORT_DB_ID")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

# AI接口基础配置
API_URL = "https://api.deepseek.com/v1/chat/completions"
HEADERS = {
    "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
    "Content-Type": "application/json"
}
MODEL_NAME = "deepseek-v4-flash"

# ====================== 自定义学术Prompt ======================
# 1. 五维关键词提取Prompt
TAG_EXTRACT_PROMPT = """
你是一位专注于具身智能（Embodied AI）、视觉-语言-动作模型（VLA）、世界模型（World Models）及机器人学领域的资深学术分析师。
请仔细阅读以下论文摘要，并从中系统性地提炼关键词。要求如下：
### 1. 关键词分类体系（必须覆盖）
请按以下五个维度提取关键词，每个维度提取 1-5 个最核心、最具代表性的术语：
- **核心任务（Task）**：论文解决的具体任务（如：机器人抓取、导航、操作、推理、规划、多模态指令跟随等）
- **方法范式（Method）**：主要技术路线或模型架构（如：VLA、Diffusion Policy、强化学习、模仿学习、世界模型、NeRF/3DGS、LLM/VLM 等）
- **关键模块/机制（Module）**：具体提出的创新组件（如：注意力机制、动作分词、视觉编码器、策略网络、动力学模型等）
- **实验场景/平台（Environment）**：验证所用的仿真环境或真实平台（如：ALFRED、Habitat、SAPIEN、Isaac Sim、真实机械臂、人形机器人等）
- **评价维度（Metric/Concept）**：核心评价指标或贯穿论文的关键概念（如：样本效率、泛化性、长程规划、零样本迁移、sim-to-real、安全性、可解释性等）
### 2. 输出格式
仅以纯结构化JSON形式输出，禁止多余解释、多余文字，便于程序直接解析：
{{"核心任务":[],"方法范式":[],"关键模块/机制":[],"实验场景/平台":[],"评价维度":[]}}

论文摘要内容：{abstract_content}
"""

# 2. 五段式学术论文总结Prompt
SUMMARY_ACADEMIC_PROMPT = """
你是一位深耕具身智能（Embodied AI）、视觉-语言-动作模型（VLA）、世界模型（World Models）与机器人学领域的资深研究者。请对以下论文摘要进行高度凝练的学术总结。
### 总结框架（严格按以下五段式输出，每段 1-3 句话，总字数控制在 250-350 字）
**1. 问题与动机（Motivation）**
- 论文针对具身智能中的什么核心痛点或任务缺口？
- 现有方法（VLA/世界模型/传统控制）在此存在什么瓶颈？

**2. 核心方法（Method）**
- 提出什么新框架、新范式或关键模块？
- 输入输出接口是什么（如：视觉+语言指令 → 末端执行器动作/关节角/路径点）？
- 训练范式（模仿学习/强化学习/预训练+微调/零样本提示）？

**3. 关键创新（Key Contribution）**
- 与同期 VLA 或世界模型工作相比，最本质的差异化设计是什么？
- 是否引入新的状态表征、动作 tokenization 方式、推演机制或 sim-to-real 策略？

**4. 实验验证（Validation）**
- 在什么环境/平台（仿真/真实机器人/人形机器人/多场景）验证？
- 核心性能提升或泛化能力表现（定量结论一句话概括）？

**5. 局限与启示（Limitation & Impact）**
- 方法的主要约束（计算成本、场景假设、动作空间限制）？
- 对领域发展的潜在启发（是否推动 VLA 规模化、世界模型可交互性、或机器人通用化）？

### 领域专属标注要求
- **若涉及 VLA**：标注动作空间类型（离散/连续/混合）、是否端到端、是否利用预训练 VLM
- **若涉及世界模型**：标注推演时长/范围、状态表征形式（像素/隐变量/语义）、是否支持交互编辑
- **若涉及机器人硬件**：标注平台类型（机械臂/人形/轮式/四足）及 sim-to-real 迁移方式

### 输出格式
使用 Markdown 结构化输出，禁止大段连续文本。语言与摘要保持一致。

论文摘要：{abstract_content}
"""

# 初始化Notion客户端
notion = Client(auth=NOTION_TOKEN)

# ====================== 核心功能函数 ======================
# 1. 安全爬取论文 10篇 多层延时防429
def fetch_vla_papers():
    print("=== 开始批量抓取10篇VLA领域论文 ===")
    client = arxiv.Client()
    search_rule = arxiv.Search(
        query="cat:cs.RO AND (Vision-Language-Action OR VLA)",
        max_results=10,
        sort_by=arxiv.SortCriterion.SubmittedDate
    )
    # 全局前置延时
    time.sleep(5)
    paper_list = []
    for paper in client.results(search_rule):
        paper_list.append(paper)
        # 单篇间隔2秒，压低请求频率
        time.sleep(2)
    print(f"=== 抓取完成，共获取{len(paper_list)}篇论文 ===")
    return paper_list

# 2. 论文去重判断
def check_paper_exists(title):
    try:
        res = notion.databases.query(
            database_id=NOTION_DATABASE_ID,
            filter={"property": "Name", "title": {"equals": title}}
        )
        return len(res["results"]) > 0
    except Exception as e:
        print(f"去重查询异常：{e}")
        return False

# 3. AI调用通用函数
def call_ai_api(prompt_text):
    if not DASHSCOPE_API_KEY:
        return None
    post_data = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": prompt_text}],
        "temperature": 0.1
    }
    try:
        response = requests.post(API_URL, headers=HEADERS, json=post_data, timeout=30)
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"AI调用失败：{e}")
        return None

# 4. AI提取五维结构化关键词
def extract_ai_tags(abstract):
    fill_prompt = TAG_EXTRACT_PROMPT.format(abstract_content=abstract)
    ai_json_str = call_ai_api(fill_prompt)
    if not ai_json_str:
        return []
    try:
        tag_data = json.loads(ai_json_str)
        all_tags = []
        for cate_list in tag_data.values():
            all_tags.extend(cate_list)
        # 去重并适配Notion多选格式
        final_tags = [{"name": tag.strip()} for tag in list(set(all_tags)) if tag.strip()]
        return final_tags
    except:
        return []

# 5. AI生成专业五段式论文总结
def get_academic_summary(abstract):
    fill_prompt = SUMMARY_ACADEMIC_PROMPT.format(abstract_content=abstract)
    summary_result = call_ai_api(fill_prompt)
    return summary_result if summary_result else "AI学术总结生成失败"

# 6. 单篇论文写入Notion数据库
def write_paper_to_notion(paper):
    paper_title = paper.title
    paper_authors = ", ".join([auth.name for auth in paper.authors])
    paper_abstract = paper.summary.replace("\n", " ").strip()
    paper_pdf_url = paper.pdf_url

    # 去重跳过
    if check_paper_exists(paper_title):
        print(f"[跳过] 论文已存在：{paper_title}")
        return

    print(f"[写入中] {paper_title}")
    # AI生成标签+总结
    tag_list = extract_ai_tags(paper_abstract)
    academic_sum = get_academic_summary(paper_abstract)

    # 写入Notion
    notion.pages.create(
        parent={"database_id": NOTION_DATABASE_ID},
        properties={
            "Name": {"title": [{"text": {"content": paper_title}}]},
            "Authors": {"rich_text": [{"text": {"content": paper_authors}}]},
            "Abstract": {"rich_text": [{"text": {"content": paper_abstract[:1950]}}]},
            "PDF Link": {"url": paper_pdf_url},
            "Status": {"select": {"name": "To Read"}},
            "Tags": {"multi_select": tag_list},
            "Summary": {"rich_text": [{"text": {"content": academic_sum[:1950]}}]}
        }
    )
    # 写入延时，避免频繁调用Notion接口
    time.sleep(1)

## 7. 生成每日领域论文汇总日报
def create_daily_research_report(papers):
    # 缩进 4 格 ✅
    print("=== 开始生成每日VLA领域研究日报 ===")
    total_content = ""
    # 缩进 4 格 ✅
    for idx, p in enumerate(papers):
        # 再缩进 4 格 ✅
        total_content += f"【论文{idx+1}】{p.title}\n{p.summary[:400]}......\n\n"
    
    report_prompt = f"基于以下今日最新10篇具身智能与VLA领域论文摘要，汇总今日领域研究热点、主流技术趋势、创新方向与未来发展趋势，输出简洁学术日报：\n{total_content}"
    daily_report = call_ai_api(report_prompt) or "今日论文汇总生成失败"

    # 写入日报专属数据库
    notion.pages.create(
        parent={"database_id": NOTION_REPORT_DB_ID},
        properties={
            "Name": {"title": [{"text": {"content": f"VLA领域每日学术日报 {time.strftime('%Y-%m-%d')}"}}]},
            "date": {"date": {"start": time.strftime("%Y-%m-%d")}},
            "content": {"rich_text": [{"text": {"content": daily_report[:1950]}}]}
        }
    )
    print("=== 每日学术日报写入完成 ===")

# ====================== 主运行入口 ======================
if __name__ == "__main__":
    all_papers = fetch_vla_papers()
    for item in all_papers:
        write_paper_to_notion(item)
    # 全部写入完成后生成日报
    create_daily_research_report(all_papers)
    print("===== 今日论文抓取+AI解析+入库全部执行完毕 =====")
