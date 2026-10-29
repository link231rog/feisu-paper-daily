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
