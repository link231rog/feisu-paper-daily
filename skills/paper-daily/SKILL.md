---
name: paper-daily
description: >
  Zero-install cloud literature pipeline: automatically forks the repository to the user's GitHub,
  configures secrets, and runs paper recommendation, 4D rubric review, audio podcast generation,
  and multi-channel delivery (Feishu, Email, Telegram, WeChat) 100% serverless on GitHub Actions.
  Zero local Python or dependencies needed.
---

# Paper Daily · Agent-Native Cloud Pipeline (`paper-daily`)

Use this skill when the user wants to set up, trigger, configure, or monitor **Paper Daily** with **zero local installation**. All computing, LLM calls, audio synthesis, and paper scraping run serverless in GitHub Actions.

## Capabilities
1. **Zero-Clone Cloud Onboarding**: Remotely fork repository and configure repository secrets in seconds without `git clone` or Python environment.
2. **On-Demand Run & Force Today**: Trigger immediate paper curation and delivery via GitHub CLI or Webhook.
3. **Dynamic Question & Skill Injection**: Inject ad-hoc research questions, exclusion keywords, or custom review rules directly into cloud runs.
4. **Pipeline Monitoring & Diagnostics**: Check workflow run status, view failed logs, and inspect report URLs.
5. **Local Coding Agent Active Search & Ingest**: Active online academic literature search (`find`), relevance & MMR reranking, and zero-checklist direct note ingestion (`ingest`) for local agents.

---

## Workflow 1: Cloud Onboarding (Zero-Install Setup)

When the user asks to "set up paper-daily", "deploy paper-daily", or initializes for the first time:

### Step 1: Check GitHub CLI Authentication
Run:
```bash
gh auth status
```
If not logged in, prompt the user:
> "Please run `gh auth login` in your terminal to grant GitHub CLI access, then say continue."

### Step 2: One-Click Remote Fork (Zero Clone)
Run:
```bash
gh repo fork link231rog/feisu-paper-daily --clone=false
```
Detect the user's username via `gh api user -q .login`. Let `<repo>` be `<username>/feisu-paper-daily`.

### Step 3: Ask User for Delivery Channels & Minimal Credentials
Ask the user in chat (or using `question` / `AskUserQuestion` tool):
1. **LLM Provider (Required)**:
   - `OPENAI_API_BASE` (e.g. `https://api.deepseek.com/v1`, `https://openrouter.ai/api/v1`, or default OpenAI)
   - `OPENAI_MODEL` (e.g. `deepseek-chat`, `gpt-4o-mini`, or OpenRouter free models)
   - `LLM_API_KEYS` (The API key)
2. **Preferred Delivery Channels (Choose 1 or more)**:
   - **Feishu / Lark (飞书云文档/知识库)**:
     - `FEISHU_APP_ID`, `FEISHU_APP_SECRET` (from Feishu Open Platform)
     - `FEISHU_WIKI_SPACE_ID`, `FEISHU_DAILY_PARENT_NODE_TOKEN`
     - Optional console node: `FEISHU_CONSOLE_NODE_TOKEN`
   - **Email (QQ / 163 / Gmail / Outlook)**:
     - `SMTP_SERVER` (e.g. `smtp.qq.com`), `SMTP_PORT` (e.g. `465`)
     - `SENDER`, `SENDER_PASSWORD` (SMTP auth code), `RECEIVER`
   - **Telegram**:
     - `TELEGRAM_BOT_TOKEN` (from @BotFather), `TELEGRAM_CHAT_ID`
   - **WeChat Official Account (微信公众号)**:
     - `WECHAT_APP_ID`, `WECHAT_APP_SECRET`
     - 可选出口代理（突破 GitHub Actions IP 白名单）: `WECHAT_PROXY_URL` (如 `http://user:pass@host:port`), `WECHAT_API_BASE` (自定义中转接口)
   - **Google NotebookLM (可选专题文献库与双人播客)**:
     - `NOTEBOOKLM_ENABLED` (`true` / `false`)
     - `NOTEBOOKLM_AUTH_JSON` (或 `NOTEBOOKLM_COOKIES`)
     - `NOTEBOOKLM_MODE` (`persistent` 长效专题自动分卷 | `daily` 每日专题)
   - **Visual Framework Diagram / Poster (可选框架图与海报生成)**:
     - `POSTER_ENABLED` (`true` / `false`)
     - `POSTER_API_KEY` (如 `sk-...`)
     - `POSTER_API_BASE` (默认 `https://sub.umapis.com/v1`)
     - `POSTER_MODEL` (默认 `gpt-image-2.5-sunburst`)
   - **Academic Translation (可选学术长文双语翻译)**:
     - `TRANSLATION_ENABLED` (`true` / `false`，默认 `true`)
     - `TRANSLATION_ENGINE` (`web` 免密极速 Bing/Google 双轨，默认推荐 | `bing` | `google` | `llm`)
     - `TRANSLATION_CONCURRENCY` (默认 `5` 并发线程)
     - `TRANSLATION_LAYOUT` (`quote` 默认引言排版 `> 译文` | `inline` 行内紧随)
     - 若切换为 `llm` 大模型模式可选: `TRANSLATION_API_BASE`, `TRANSLATION_API_KEY`, `TRANSLATION_MODEL`
3. **Initial Research Tags & Questions**:
   - Tags (e.g. `LLM Agents, Memory, Reinforcement Learning`)
   - 1~2 core questions (e.g. `How to compress episodic memory with bounded tokens?`)

### Step 4: Write Secrets Directly to Cloud Repository
Execute for each provided credential:
```bash
gh secret set <KEY> -R <repo> --body "<VALUE>"
```
*Tip: Always use `--body` with sanitized strings to prevent trailing newline issues.*

### Step 5: Trigger First Cloud Run & Report
Run:
```bash
gh workflow run main.yml -R <repo> -f force_today=true
```
Wait 5 seconds and check:
```bash
gh run list -R <repo> -L 1
```
Report the workflow run URL to the user.

---

## Workflow 2: On-Demand Report Triggering

When the user asks to "推送今天的日报", "跑一下最新论文", or "运行 paper-daily":
```bash
gh workflow run main.yml -R <repo> -f force_today=true
```
Confirm the run has started with `gh run list -R <repo> -L 1`.

---

## Workflow 3: Dynamic Question & Rule Injection (Cloud Webhook)

When the user wants to temporarily track a new question, test a custom rule, or inject an exclusion keyword without modifying configs:
```bash
gh api repos/<repo>/dispatches --input - <<'JSON'
{
  "event_type": "paper-daily",
  "client_payload": {
    "force_today": true,
    "questions": ["How to achieve zero-shot instance sizing?"],
    "custom_rules": ["Focus on training-free methods"]
  }
}
JSON
```

---

## Workflow 4: Status Monitoring & Log Inspection

- **Check recent runs**:
  ```bash
  gh run list -R <repo> -L 3
  ```
- **Inspect run failure**:
  ```bash
  gh run view <run_id> -R <repo> --log-failed
  ```
- **Watch run until complete**:
  ```bash
  gh run watch <run_id> -R <repo>
  ```

---

## Workflow 5: Local Coding Agent Active Research & Direct Ingestion

Use this workflow when a local Coding Agent (Claude Code, Cursor, OpenCode, Cline) is working on code/architecture and needs academic references, algorithmic baselines, or wants to save a paper:

### Step 1: Online Academic Literature Search & MMR Reranking
Search online across official arXiv, Semantic Scholar, and DBLP engines with Max-TopK relevance scoring and MMR diversity:
```bash
uv run paper-library find "<keywords or problem description>" --top-k 5 [--json]
```
The agent receives clean candidate cards (title, authors, venue, relevance score, abstract, paper URL, PDF link, open-source code repo) without entering an interactive checklist.

### Step 2: One-Click Direct Ingestion (Zero-Checklist)
When the Coding Agent or user decides a paper is helpful and should be saved into the personal knowledge base:
```bash
uv run paper-library ingest "<url_or_arxiv_id>" [--provider auto|feishu|obsidian|notion|zotero] [--poster] [--json]
```
Add `--poster` to automatically generate and mount an academic pipeline framework diagram into the reading note.

### Step 3: Standalone Framework Diagram / Poster Generation
When the Coding Agent only needs a visual pipeline/framework diagram for a paper without ingesting:
```bash
uv run paper-library poster "<url_or_arxiv_id>" [--json]
```
Returns local image path and `file://` URI for immediate visual inspection in terminal or markdown preview.
This command:
1. Resolves full text via ordered fallback chains (`arXiv HTML` -> `PyMuPDF` -> `Agent-Reach` -> `Trafilatura`).
2. Generates structured 5-section reading notes (core summary, motivation, method, experiments, takeaways) and detail annotations.
3. Directly writes the note to the user's active library (Feishu Docx note, Obsidian vault Markdown, Notion database, or Zotero collection).
4. Marks the paper in `paper_store.json` so future daily morning runs do not re-recommend it as unread.
5. Returns the direct note link or local URI immediately for the Coding Agent to continue coding.
