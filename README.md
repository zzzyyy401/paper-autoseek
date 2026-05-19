# Paper AutoSeek

**Automated arXiv Paper Fetcher & AI-Powered Academic Analysis**

Paper AutoSeek is a Python tool that automatically crawls the latest academic papers from [arXiv](https://arxiv.org) in the fields of **VLA (Vision-Language-Action)**, **Embodied AI**, **World Models**, and related robotics topics. It leverages AI (DeepSeek API) to extract keywords and generate concise summaries, then organizes everything into **Notion** databases for easy tracking and daily research reports.

---

## Features

- 📥 **Automated Paper Fetching** — Searches arXiv daily for the newest papers matching curated queries (cs.RO, VLA, Embodied AI, WAM, etc.)
- 🧠 **AI-Powered Tag Extraction** — Uses DeepSeek Chat API to extract 5–15 core academic keywords from each paper's abstract
- 📝 **Concise Summarization** — Generates a 3-sentence structured summary (problem → method → conclusion) for every paper
- 🗂 **Notion Integration** — Writes paper metadata (title, authors, abstract, PDF link, tags, summary) directly into a Notion database
- 📊 **Daily Research Report** — Automatically creates a daily trend report in a separate Notion database, summarizing the day's papers in under 100 characters
- 🔄 **Deduplication** — Checks existing Notion entries before adding to avoid duplicates
- 🔁 **Automatic Retry** — Built-in retry logic for both arXiv fetching and AI API calls with exponential backoff
- ⏱ **Scheduled Execution** — Runs automatically every day at 22:03 UTC via GitHub Actions
- 🔧 **Manual Trigger** — Supports manual execution via GitHub Actions `workflow_dispatch`

---

## Architecture

```
                  ┌─────────────────┐
                  │    arXiv API    │
                  └────────┬────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │  fetch_vla_papers() │
                  │  (arXiv client)  │
                  └────────┬────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
    ┌──────────────┐ ┌──────────┐ ┌──────────┐
    │ Deduplication │ │ Tag      │ │ Summary  │
    │ (Notion Query)│ │Extraction│ │Generation│
    └──────┬───────┘ │ (DeepSeek)│ │(DeepSeek)│
           │         └─────┬────┘ └─────┬────┘
           │               │            │
           └───────────────┼────────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │   Notion API    │
                  │  (papers + report)│
                  └─────────────────┘
```

---

## Requirements

- Python 3.11+
- Dependencies listed in [`requirements.txt`](paper-autoseek-main/requirements.txt):
  - `arxiv==2.1.3` — arXiv API client
  - `notion-client==2.2.1` — Notion API client
  - `requests>=2.31.0` — HTTP library (with retry support)

---

## Setup

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/paper-autoseek.git
cd paper-autoseek
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

| Variable | Description |
|---|---|
| `NOTION_TOKEN` | Notion integration token |
| `NOTION_DATABASE_ID` | Notion database ID for storing papers |
| `NOTION_REPORT_DB_ID` | Notion database ID for daily research reports |
| `DEEPSEEK_API_KEY` | DeepSeek API key (primary AI provider) |
| `DASHSCOPE_API_KEY` | DashScope API key (fallback if DeepSeek key is missing) |

You can set these in a `.env` file or export them directly:

```bash
export NOTION_TOKEN="ntn_..."
export NOTION_DATABASE_ID="..."
export NOTION_REPORT_DB_ID="..."
export DEEPSEEK_API_KEY="sk-..."
```

### 4. Prepare Notion Databases

Create two databases in Notion:

**Papers Database** (`NOTION_DATABASE_ID`):
| Property | Type |
|---|---|
| `Name` | Title |
| `Authors` | Rich Text |
| `Abstract` | Rich Text |
| `PDF Link` | URL |
| `Status` | Select (e.g., "To Read", "Reading", "Read") |
| `Tags` | Multi-select |
| `Summary` | Rich Text |

**Daily Report Database** (`NOTION_REPORT_DB_ID`):
| Property | Type |
|---|---|
| `Name` | Title |
| `Date` | Date |
| `Content` | Rich Text |

---

## Usage

### Run Locally

```bash
python paper-autoseek-main/paperseek.py
```

The script will:
1. Fetch up to **5 new papers** from arXiv (scanning latest 100 submissions)
2. Check each against your Notion database to avoid duplicates
3. Extract AI tags and generate summaries via DeepSeek API
4. Write all papers to your Notion database
5. Generate and save a daily research trend report

### Automated Schedule (GitHub Actions)

The workflow in [`.github/workflows/run.yml`](paper-autoseek-main/.github/workflows/run.yml) runs automatically every day at **22:03 UTC**.

To trigger manually:
1. Go to your repository on GitHub
2. Navigate to **Actions** → **VLA论文自动抓取&AI学术解析**
3. Click **Run workflow**

---

## Search Query

The tool currently searches arXiv with the following query:

```
cat:cs.RO AND (vision language action OR embodied ai OR world model OR VLA OR WAM)
```

- **Category**: `cs.RO` (Robotics)
- **Keywords**: VLA (Vision-Language-Action), Embodied AI, World Models, WAM

To customize the search, modify the `query` parameter in the [`fetch_vla_papers()`](paper-autoseek-main/paperseek.py:136) function.

---

## Key Functions

| Function | Description |
|---|---|
| [`fetch_vla_papers()`](paper-autoseek-main/paperseek.py:123) | Fetches 5 newest papers from arXiv with deduplication against Notion |
| [`check_paper_exists()`](paper-autoseek-main/paperseek.py:163) | Queries Notion to check if a paper title already exists |
| [`extract_ai_tags()`](paper-autoseek-main/paperseek.py:176) | Calls DeepSeek API to extract academic keywords from abstract |
| [`get_academic_summary()`](paper-autoseek-main/paperseek.py:199) | Generates a 3-sentence structured summary |
| [`write_paper_to_notion()`](paper-autoseek-main/paperseek.py:206) | Writes paper metadata + tags + summary to Notion |
| [`create_daily_research_report()`](paper-autoseek-main/paperseek.py:244) | Creates a daily trend report in Notion |
| [`call_ai_api()`](paper-autoseek-main/paperseek.py:85) | Core AI API caller with retry and fallback logic |

---

## Customization

- **Change number of papers to fetch**: Modify the `target` variable in [`fetch_vla_papers()`](paper-autoseek-main/paperseek.py:126)
- **Adjust AI prompts**: Edit [`TAG_EXTRACT_PROMPT`](paper-autoseek-main/paperseek.py:31) and [`SUMMARY_ACADEMIC_PROMPT`](paper-autoseek-main/paperseek.py:44)
- **Change AI model**: Update [`MODEL_NAME`](paper-autoseek-main/paperseek.py:24) (default: `deepseek-chat`)
- **Switch Notion database**: Change the database ID environment variables

---

## Project Structure

```
paper-autoseek/
├── paperseek.py              # Main script
├── requirements.txt          # Python dependencies
├── .github/
│   └── workflows/
│       └── run.yml           # GitHub Actions workflow (daily schedule)
└── README.md                 # This file
```

---

## License

This project is open source and available under the [MIT License](LICENSE).
