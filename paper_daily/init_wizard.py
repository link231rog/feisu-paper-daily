"""Interactive CLI & Agent Skill Initialization Wizard for Paper Daily.

Supports two execution modes:
1. Interactive CLI Wizard (`uv run paper-daily init` or `uv run paper-library init`):
   Guides the user through multi-select architecture choices (Console/Library,
   Retrieval Sources, Delivery Channels, Deployment Modes, Research Topics/Questions)
   and dynamically follows up ONLY on the selected channels to collect API Keys,
   Tokens, Auth credentials, or local paths.
2. Agent Skill Bridge (`--schema`, `--print-skill`, `--from-json`):
   Provides structured multi-select question schemas and conditional credential
   prompts for AI Coding Agents (Claude Code, OpenClaw, Cursor, Hermes) using
   their native `AskUserQuestion` tool, then applies the collected JSON payload
   to generate `config/custom.yaml`, `.env`, local console templates, and
   GitHub Actions secret commands.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable


def _dump_yaml_lines(obj: Any, indent: int = 0) -> list[str]:
    prefix = "  " * indent
    if isinstance(obj, dict):
        lines: list[str] = []
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{prefix}{k}:")
                lines.extend(_dump_yaml_lines(v, indent + 1))
            elif isinstance(v, list) and not v:
                lines.append(f"{prefix}{k}: []")
            elif isinstance(v, dict) and not v:
                lines.append(f"{prefix}{k}: {{}}")
            else:
                lines.append(f"{prefix}{k}: {_format_yaml_scalar(v)}")
        return lines
    if isinstance(obj, list):
        lines = []
        for item in obj:
            if isinstance(item, dict):
                first = True
                for k, v in item.items():
                    head = f"{prefix}- " if first else f"{prefix}  "
                    first = False
                    if isinstance(v, (dict, list)) and v:
                        lines.append(f"{head}{k}:")
                        lines.extend(_dump_yaml_lines(v, indent + 2))
                    else:
                        lines.append(f"{head}{k}: {_format_yaml_scalar(v)}")
            else:
                lines.append(f"{prefix}- {_format_yaml_scalar(item)}")
        return lines
    return [f"{prefix}{_format_yaml_scalar(obj)}"]


def _format_yaml_scalar(val: Any) -> str:
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    return json.dumps(str(val), ensure_ascii=False)


def _save_yaml_config(cfg: dict[str, Any], target_path: Path) -> None:
    try:
        from omegaconf import OmegaConf

        OmegaConf.save(config=OmegaConf.create(cfg), f=str(target_path))
    except ImportError:
        target_path.write_text("\n".join(_dump_yaml_lines(cfg)) + "\n", encoding="utf-8")

# ---------------------------------------------------------------------------
# 1. Multi-Select Option Definitions & Conditional Credential Schema
# ---------------------------------------------------------------------------

LIBRARY_OPTIONS: list[dict[str, str]] = [
    {"id": "feishu", "label": "飞书云文档 (Feishu Wiki / Docx)", "desc": "云端协同控制台与精读文献库"},
    {"id": "obsidian", "label": "Obsidian 本地库 (Markdown Vault)", "desc": "本地双链笔记与 Console.md 控制台"},
    {"id": "notion", "label": "Notion 数据库 (Database & Page)", "desc": "Notion 页面控制台与数据库文献库"},
    {"id": "zotero", "label": "Zotero 文献库 (Web API)", "desc": "读取 Zotero 题录并回写精读子笔记"},
]

SOURCE_OPTIONS: list[dict[str, str]] = [
    {"id": "arxiv", "label": "arXiv (cs.AI / cs.CL / cs.CV / cs.LG)", "desc": "每日最新预印本"},
    {"id": "huggingface", "label": "Hugging Face Daily Papers", "desc": "社区高热度精选论文"},
    {"id": "semantic_scholar", "label": "Semantic Scholar", "desc": "语义检索与引用网络多跳追踪"},
    {"id": "openreview", "label": "OpenReview (ICLR / NeurIPS / ICML)", "desc": "顶会投稿与公开审稿意见"},
    {"id": "dblp", "label": "DBLP", "desc": "计算机顶会与期刊题录检索"},
    {"id": "news_and_trends", "label": "科技媒体与开源动态 (AlphaXiv / X / 小红书 / 机器之心 / 量子位 / 新智元)", "desc": "前沿动态与高星开源项目"},
]

DELIVERY_OPTIONS: list[dict[str, str]] = [
    {"id": "feishu", "label": "飞书云文档日报", "desc": "生成飞书云文档日报与阅读待办"},
    {"id": "email", "label": "Email 邮件推送 (SMTP)", "desc": "发送 HTML 排版日报到指定邮箱"},
    {"id": "wechat", "label": "微信公众号草稿箱", "desc": "自动排版并写入公众号后台草稿箱"},
    {"id": "telegram", "label": "Telegram Bot 推送", "desc": "Bot 实时推送每日摘要与评分"},
]

DEPLOY_OPTIONS: list[dict[str, str]] = [
    {"id": "github_actions", "label": "GitHub Actions 定时运行", "desc": "Fork 仓库免服务器每日定时执行"},
    {"id": "agent_cli", "label": "本地 Agent 直连 (OpenClaw / Hermes / Claude Code)", "desc": "本地通过 CLI 检索文献库与运行流水线"},
    {"id": "webhook", "label": "Webhook 远程触发 (repository_dispatch)", "desc": "通过单条请求携带临时问题远程触发"},
]

CREDENTIAL_SPECS: dict[str, list[dict[str, Any]]] = {
    "llm": [
        {
            "env": "OPENAI_API_BASE",
            "prompt": "LLM API Base URL",
            "default": "https://api.openai.com/v1",
            "required": True,
        },
        {
            "env": "OPENAI_MODEL",
            "prompt": "LLM 主力模型名称",
            "default": "gpt-4o-mini",
            "required": True,
        },
        {
            "env": "LLM_API_KEYS",
            "prompt": "LLM API Key (支持多个 Key 逗号分隔轮询)",
            "default": "",
            "required": True,
            "secret": True,
        },
    ],
    "feishu": [
        {
            "env": "FEISHU_APP_ID",
            "prompt": "飞书应用 App ID (cli_xxx)",
            "default": "",
            "required": True,
        },
        {
            "env": "FEISHU_APP_SECRET",
            "prompt": "飞书应用 App Secret",
            "default": "",
            "required": True,
            "secret": True,
        },
        {
            "env": "FEISHU_CONSOLE_NODE_TOKEN",
            "prompt": "飞书控制台云文档 Node Token (可选，用于读取规则与问题)",
            "default": "",
            "required": False,
        },
        {
            "env": "FEISHU_DAILY_PARENT_NODE_TOKEN",
            "prompt": "飞书日报挂载目录 Node Token",
            "default": "",
            "required": False,
        },
        {
            "env": "FEISHU_NOTES_PARENT_NODE_TOKEN",
            "prompt": "飞书精读笔记入库目录 Node Token",
            "default": "",
            "required": False,
        },
    ],
    "obsidian": [
        {
            "env": "OBSIDIAN_VAULT_PATH",
            "config_key": "obsidian.vault_path",
            "prompt": "Obsidian 本地库目录路径 (例如 ~/Documents/ObsidianVault)",
            "default": "./obsidian_vault",
            "required": True,
        },
        {
            "env": "OBSIDIAN_CONSOLE_PATH",
            "config_key": "obsidian.console_path",
            "prompt": "Obsidian 控制台文档相对路径",
            "default": "Console.md",
            "required": False,
        },
        {
            "env": "OBSIDIAN_NOTES_FOLDER",
            "config_key": "obsidian.notes_folder",
            "prompt": "Obsidian 精读笔记保存目录",
            "default": "Literature",
            "required": False,
        },
    ],
    "notion": [
        {
            "env": "NOTION_TOKEN",
            "prompt": "Notion Integration Token (secret_xxx / ntn_xxx)",
            "default": "",
            "required": True,
            "secret": True,
        },
        {
            "env": "NOTION_DATABASE_ID",
            "prompt": "Notion 文献库 Database ID",
            "default": "",
            "required": True,
        },
        {
            "env": "NOTION_CONSOLE_PAGE_ID",
            "config_key": "notion.console_page_id",
            "prompt": "Notion 控制台 Page ID (可选)",
            "default": "",
            "required": False,
        },
    ],
    "zotero": [
        {
            "env": "ZOTERO_ID",
            "prompt": "Zotero User ID (数字 ID)",
            "default": "",
            "required": True,
        },
        {
            "env": "ZOTERO_KEY",
            "prompt": "Zotero API Key (需勾选读写权限)",
            "default": "",
            "required": True,
            "secret": True,
        },
        {
            "env": "ZOTERO_CONSOLE_NOTE_KEY",
            "config_key": "zotero.console_note_key",
            "prompt": "Zotero 控制台笔记 Item Key (可选)",
            "default": "",
            "required": False,
        },
    ],
    "semantic_scholar": [
        {
            "env": "SEMANTIC_SCHOLAR_API_KEY",
            "prompt": "Semantic Scholar API Key (可选，直接回车可跳过)",
            "default": "",
            "required": False,
            "secret": True,
        },
    ],
    "email": [
        {
            "env": "SMTP_SERVER",
            "prompt": "SMTP 服务器地址 (如 smtp.qq.com / smtp.gmail.com)",
            "default": "smtp.qq.com",
            "required": True,
        },
        {
            "env": "SMTP_PORT",
            "prompt": "SMTP 端口 (SSL 通常为 465)",
            "default": "465",
            "required": True,
        },
        {
            "env": "SENDER",
            "prompt": "发件人邮箱地址",
            "default": "",
            "required": True,
        },
        {
            "env": "SENDER_PASSWORD",
            "prompt": "发件人邮箱授权码 / App Password",
            "default": "",
            "required": True,
            "secret": True,
        },
        {
            "env": "RECEIVER",
            "prompt": "收件人邮箱地址 (多个邮箱用逗号分隔)",
            "default": "",
            "required": True,
        },
    ],
    "wechat": [
        {
            "env": "WECHAT_APP_ID",
            "prompt": "微信公众号开发者 AppID",
            "default": "",
            "required": True,
        },
        {
            "env": "WECHAT_APP_SECRET",
            "prompt": "微信公众号开发者 AppSecret",
            "default": "",
            "required": True,
            "secret": True,
        },
        {
            "env": "WECHAT_THUMB_MEDIA_ID",
            "prompt": "公众号默认封面永久素材 thumb_media_id",
            "default": "",
            "required": False,
        },
        {
            "env": "WECHAT_AUTHOR",
            "prompt": "公众号文章作者署名",
            "default": "Paper Daily",
            "required": False,
        },
    ],
    "telegram": [
        {
            "env": "TELEGRAM_BOT_TOKEN",
            "prompt": "Telegram Bot Token (来自 @BotFather)",
            "default": "",
            "required": True,
            "secret": True,
        },
        {
            "env": "TELEGRAM_CHAT_ID",
            "prompt": "Telegram 接收推送的 Chat ID / Channel ID",
            "default": "",
            "required": True,
        },
    ],
    "translation": [
        {
            "env": "TRANSLATION_ENABLED",
            "prompt": "是否开启长文全文中英双语翻译 (true/false)",
            "default": "true",
            "required": False,
        },
        {
            "env": "TRANSLATION_ENGINE",
            "prompt": "翻译引擎模式 (web: 免密极速 Bing/Google 双轨 / llm: 调用大模型)",
            "default": "web",
            "required": False,
        },
        {
            "env": "TRANSLATION_CONCURRENCY",
            "prompt": "翻译并发线程数",
            "default": "5",
            "required": False,
        },
    ],
}


def get_required_credential_groups(
    libraries: list[str],
    sources: list[str],
    deliveries: list[str],
) -> list[str]:
    """Determines which credential groups need follow-up based on multi-select choices."""
    groups: list[str] = ["llm"]
    combined = set(libraries) | set(sources) | set(deliveries)
    for key in ("feishu", "obsidian", "notion", "zotero", "semantic_scholar", "email", "wechat", "telegram"):
        if key in combined:
            groups.append(key)
    return groups


def get_conditional_credential_prompts(
    libraries: list[str],
    sources: list[str],
    deliveries: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """Returns the exact credential prompt definitions required for the selected channels."""
    groups = get_required_credential_groups(libraries, sources, deliveries)
    return {g: CREDENTIAL_SPECS[g] for g in groups if g in CREDENTIAL_SPECS}


def get_agent_skill_schema() -> dict[str, Any]:
    """Returns the structured multi-select questions and conditional credential rules for AI Agents."""
    return {
        "skill_name": "paper-daily-init",
        "description": "Interactive multi-select initialization wizard for Paper Daily",
        "phase_1_multi_select_questions": [
            {
                "id": "libraries",
                "question": "请选择您使用的控制台与文献库平台（可多选）：",
                "is_multi_select": True,
                "options": LIBRARY_OPTIONS,
                "default": ["obsidian"],
            },
            {
                "id": "sources",
                "question": "请选择每日抓取的论文与资讯信源（可多选）：",
                "is_multi_select": True,
                "options": SOURCE_OPTIONS,
                "default": ["arxiv", "huggingface", "semantic_scholar"],
            },
            {
                "id": "deliveries",
                "question": "请选择日报推送渠道（可多选）：",
                "is_multi_select": True,
                "options": DELIVERY_OPTIONS,
                "default": ["feishu"],
            },
            {
                "id": "deploy_modes",
                "question": "请选择接入触发与部署方式（可多选）：",
                "is_multi_select": True,
                "options": DEPLOY_OPTIONS,
                "default": ["github_actions", "agent_cli"],
            },
        ],
        "phase_2_conditional_credentials": CREDENTIAL_SPECS,
        "apply_command": "uv run paper-daily init --from-json '<json_payload>'",
    }


def export_agent_skill_markdown() -> str:
    """Returns the SKILL.md instruction text for Claude Code / OpenClaw / Cursor / Hermes."""
    for parent in Path(__file__).resolve().parents:
        skill_file = parent / "skills" / "paper-daily" / "SKILL.md"
        if skill_file.is_file():
            return skill_file.read_text(encoding="utf-8")
    return """---
name: paper-daily
description: Zero-install cloud literature pipeline running 100% serverless on GitHub Actions.
---
"""


# ---------------------------------------------------------------------------
# 2. Configuration, .env & Console Document Generator
# ---------------------------------------------------------------------------

def build_console_template_markdown(
    tags: list[str],
    questions: list[str],
    custom_rules: list[str] | None = None,
) -> str:
    """Builds an initial Console.md markdown document with tags, tracked questions, and templates."""
    tag_lines = "\n".join(f"- {t}" for t in (tags or ["LLM Agents", "Long-Context Memory"]))
    q_lines = "\n".join(
        f"- {q}"
        for q in (
            questions
            or [
                "How can LLM agents maintain long-horizon episodic memory with bounded token overhead?",
            ]
        )
    )
    rule_lines = "\n".join(
        f"- {r}"
        for r in (
            custom_rules
            or [
                "重点核查实验表格中的真实涨点与算力开销，过滤仅靠堆叠工程模块无理论或机制创新的灌水工作。",
            ]
        )
    )
    return f"""# Paper Daily 控制台

## 关注领域
{tag_lines}

## 核心问题
{q_lines}

## 自定义 Skill
{rule_lines}

## 笔记模板
- 核心增量与基线对比：一句话指出相比已有基线的核心变量与机制差异
- 实验核查与失效边界：列出正文图表中的关键指标、开销对比与适用边界
"""


def apply_init_configuration(
    payload: dict[str, Any],
    custom_yaml_path: str | Path = "config/custom.yaml",
    env_path: str | Path = ".env",
    create_console_doc: bool = True,
) -> dict[str, Any]:
    """Applies collected multi-select choices and channel credentials to config/custom.yaml and .env."""
    libraries = [str(x).strip().lower() for x in (payload.get("libraries") or ["obsidian"]) if str(x).strip()]
    sources = [
        str(x).strip().lower()
        for x in (payload.get("sources") or ["arxiv", "huggingface", "semantic_scholar"])
        if str(x).strip()
    ]
    deliveries = [str(x).strip().lower() for x in (payload.get("deliveries") or []) if str(x).strip()]
    deploy_modes = [str(x).strip().lower() for x in (payload.get("deploy_modes") or ["github_actions"]) if str(x).strip()]
    tags = [str(x).strip() for x in (payload.get("tags") or ["LLM Agents"]) if str(x).strip()]
    questions = [str(x).strip() for x in (payload.get("questions") or []) if str(x).strip()]
    custom_rules = [str(x).strip() for x in (payload.get("custom_rules") or []) if str(x).strip()]
    arxiv_categories = [
        str(x).strip()
        for x in (payload.get("arxiv_categories") or ["cs.AI", "cs.CL", "cs.CV", "cs.LG"])
        if str(x).strip()
    ]
    creds: dict[str, str] = {
        str(k).strip(): str(v).strip()
        for k, v in (payload.get("credentials") or {}).items()
        if str(v).strip()
    }

    # Separate retrieval sources vs news_and_trends
    paper_sources = [s for s in sources if s in {"arxiv", "huggingface", "semantic_scholar", "openreview", "dblp", "biorxiv", "medrxiv", "chemrxiv"}]
    if not paper_sources:
        paper_sources = ["arxiv", "huggingface"]
    news_enabled = "news_and_trends" in sources

    # Primary console provider preference
    console_provider = libraries[0] if libraries else "auto"

    custom_cfg: dict[str, Any] = {
        "topics": [
            {
                "name": tag,
                "keywords": [tag],
                "description": f"Research direction: {tag}",
            }
            for tag in tags
        ],
        "source": {
            "arxiv": {
                "category": arxiv_categories,
                "include_cross_list": True,
            },
            "semantic_scholar": {
                "queries": tags,
                "date_range": "2025:2026",
                "limit_per_query": 15,
            },
            "openreview": {
                "queries": tags,
                "limit_per_query": 15,
            },
            "dblp": {
                "queries": tags,
                "limit_per_query": 15,
                "min_year": 2025,
            },
        },
        "executor": {
            "source": paper_sources,
            "max_paper_num": int(payload.get("max_paper_num") or 15),
            "total_daily_quota": int(payload.get("total_daily_quota") or 15),
            "reranker": "local",
        },
        "console": {
            "enabled": True,
            "provider": console_provider,
            "node_token": creds.get("FEISHU_CONSOLE_NODE_TOKEN") or None,
            "tags": tags,
            "questions": questions or None,
            "custom_rules": custom_rules or None,
        },
        "obsidian": {
            "enabled": "obsidian" in libraries,
            "vault_path": creds.get("OBSIDIAN_VAULT_PATH") or ("./obsidian_vault" if "obsidian" in libraries else None),
            "console_path": creds.get("OBSIDIAN_CONSOLE_PATH") or "Console.md",
            "notes_folder": creds.get("OBSIDIAN_NOTES_FOLDER") or "Literature",
        },
        "notion": {
            "enabled": "notion" in libraries,
            "token": creds.get("NOTION_TOKEN") or None,
            "database_id": creds.get("NOTION_DATABASE_ID") or None,
            "console_page_id": creds.get("NOTION_CONSOLE_PAGE_ID") or None,
        },
        "zotero": {
            "user_id": creds.get("ZOTERO_ID") or None,
            "api_key": creds.get("ZOTERO_KEY") or None,
            "console_note_key": creds.get("ZOTERO_CONSOLE_NOTE_KEY") or None,
        },
        "feishu": {
            "app_id": creds.get("FEISHU_APP_ID") or None,
            "app_secret": creds.get("FEISHU_APP_SECRET") or None,
            "daily_parent_node_token": creds.get("FEISHU_DAILY_PARENT_NODE_TOKEN") or None,
            "notes_parent_node_token": creds.get("FEISHU_NOTES_PARENT_NODE_TOKEN") or None,
            "dry_run": not ("feishu" in libraries or "feishu" in deliveries),
        },
        "email": {
            "enabled": "email" in deliveries,
            "smtp_server": creds.get("SMTP_SERVER") or None,
            "smtp_port": int(creds["SMTP_PORT"]) if creds.get("SMTP_PORT", "").isdigit() else 465,
            "sender": creds.get("SENDER") or None,
            "sender_password": creds.get("SENDER_PASSWORD") or None,
            "receiver": creds.get("RECEIVER") or None,
        },
        "wechat": {
            "enabled": "wechat" in deliveries,
            "app_id": creds.get("WECHAT_APP_ID") or None,
            "app_secret": creds.get("WECHAT_APP_SECRET") or None,
            "thumb_media_id": creds.get("WECHAT_THUMB_MEDIA_ID") or None,
            "author": creds.get("WECHAT_AUTHOR") or "Paper Daily",
        },
        "telegram": {
            "enabled": "telegram" in deliveries,
            "bot_token": creds.get("TELEGRAM_BOT_TOKEN") or None,
            "chat_id": creds.get("TELEGRAM_CHAT_ID") or None,
        },
        "news_and_trends": {
            "enabled": news_enabled,
        },
        "llm": {
            "api": {
                "base_url": creds.get("OPENAI_API_BASE") or "https://api.openai.com/v1",
            },
            "generation_kwargs": {
                "model": creds.get("OPENAI_MODEL") or "gpt-4o-mini",
                "max_tokens": 16384,
            },
        },
    }

    # 1. Write config/custom.yaml
    yaml_target = Path(custom_yaml_path)
    yaml_target.parent.mkdir(parents=True, exist_ok=True)
    _save_yaml_config(custom_cfg, yaml_target)

    # 2. Write or merge .env
    env_target = Path(env_path)
    existing_env: dict[str, str] = {}
    if env_target.exists():
        for line in env_target.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k, v = stripped.split("=", 1)
                existing_env[k.strip()] = v.strip()

    env_updates: dict[str, str] = {
        "EMAIL_ENABLED": "true" if "email" in deliveries else "false",
        "WECHAT_ENABLED": "true" if "wechat" in deliveries else "false",
        "TELEGRAM_ENABLED": "true" if "telegram" in deliveries else "false",
    }
    for k, v in creds.items():
        if v:
            env_updates[k] = v

    existing_env.update(env_updates)
    env_lines = [f"{k}={v}" for k, v in sorted(existing_env.items())]
    env_target.write_text("\n".join(env_lines) + "\n", encoding="utf-8")

    # 3. Initialize Obsidian Console.md if Obsidian is enabled
    created_console_file: str | None = None
    if create_console_doc and "obsidian" in libraries:
        vault_dir = Path(str(custom_cfg["obsidian"]["vault_path"])).expanduser()
        console_rel = str(custom_cfg["obsidian"]["console_path"] or "Console.md").lstrip("/")
        console_file = vault_dir / console_rel
        console_file.parent.mkdir(parents=True, exist_ok=True)
        if not console_file.exists():
            console_file.write_text(
                build_console_template_markdown(tags=tags, questions=questions, custom_rules=custom_rules),
                encoding="utf-8",
            )
        created_console_file = str(console_file)

    # 4. Generate GitHub Actions `gh secret set` commands if github_actions selected
    gh_secret_commands: list[str] = []
    if "github_actions" in deploy_modes:
        for k, v in sorted(env_updates.items()):
            if v and not k.startswith("OBSIDIAN_"):
                safe_val = v.replace('"', '\\"')
                gh_secret_commands.append(f'gh secret set {k} --body "{safe_val}"')

    return {
        "status": "success",
        "custom_yaml_path": str(yaml_target),
        "env_path": str(env_target),
        "created_console_file": created_console_file,
        "selected": {
            "libraries": libraries,
            "sources": sources,
            "deliveries": deliveries,
            "deploy_modes": deploy_modes,
        },
        "configured_env_keys": sorted(env_updates.keys()),
        "gh_secret_commands": gh_secret_commands,
    }


# ---------------------------------------------------------------------------
# 3. Interactive Terminal Multi-Select & Credential Wizard
# ---------------------------------------------------------------------------

def _prompt_multi_select(
    title: str,
    options: list[dict[str, str]],
    default_ids: list[str],
    input_fn: Callable[[str], str] = input,
) -> list[str]:
    print(f"\n=== {title} (可多选，输入编号用逗号分隔，直接回车使用默认) ===")
    default_indices: list[str] = []
    for idx, opt in enumerate(options, 1):
        marker = "*" if opt["id"] in default_ids else " "
        if opt["id"] in default_ids:
            default_indices.append(str(idx))
        print(f"  [{idx}]{marker} {opt['label']} — {opt['desc']}")

    raw = input_fn(f"请选择编号 (默认 {','.join(default_indices)}): ").strip()
    if not raw:
        return list(default_ids)

    picked: list[str] = []
    for part in raw.replace("，", ",").split(","):
        p = part.strip()
        if p.isdigit():
            i = int(p) - 1
            if 0 <= i < len(options):
                opt_id = options[i]["id"]
                if opt_id not in picked:
                    picked.append(opt_id)
        else:
            for opt in options:
                if p.lower() == opt["id"].lower() and opt["id"] not in picked:
                    picked.append(opt["id"])
    return picked or list(default_ids)


def run_interactive_init(
    custom_yaml_path: str | Path = "config/custom.yaml",
    env_path: str | Path = ".env",
    input_fn: Callable[[str], str] = input,
) -> dict[str, Any]:
    """Runs the interactive CLI multi-select + conditional credential setup wizard."""
    print("================================================================")
    print("  Paper Daily · 交互式初始化向导 (Multi-Select + 渠道凭证配置)")
    print("================================================================")

    libraries = _prompt_multi_select(
        "步骤 1/5: 选择控制台与文献库平台",
        LIBRARY_OPTIONS,
        default_ids=["obsidian"],
        input_fn=input_fn,
    )
    sources = _prompt_multi_select(
        "步骤 2/5: 选择每日抓取的论文与资讯信源",
        SOURCE_OPTIONS,
        default_ids=["arxiv", "huggingface", "semantic_scholar"],
        input_fn=input_fn,
    )
    deliveries = _prompt_multi_select(
        "步骤 3/5: 选择日报推送渠道",
        DELIVERY_OPTIONS,
        default_ids=["feishu"],
        input_fn=input_fn,
    )
    deploy_modes = _prompt_multi_select(
        "步骤 4/5: 选择接入触发与部署方式",
        DEPLOY_OPTIONS,
        default_ids=["github_actions", "agent_cli"],
        input_fn=input_fn,
    )

    print("\n=== 步骤 5/5: 初始研究领域与追踪问题 ===")
    raw_tags = input_fn("关注领域关键词 (逗号分隔，默认 'LLM Agents, Memory'): ").strip()
    tags = [t.strip() for t in raw_tags.replace("，", ",").split(",") if t.strip()] or ["LLM Agents", "Memory"]

    raw_questions = input_fn(
        "首批追踪的核心科学问题 (多个问题用分号 ; 分隔，直接回车使用默认示例): "
    ).strip()
    questions = [q.strip() for q in raw_questions.replace("；", ";").split(";") if q.strip()] or [
        "How can LLM agents maintain long-horizon episodic memory with bounded token overhead?"
    ]

    # Dynamic conditional credential follow-up based on selected channels
    cred_prompts = get_conditional_credential_prompts(libraries, sources, deliveries)
    credentials: dict[str, str] = {}
    print("\n================================================================")
    print("  按所选渠道配置 API Key / Auth / 路径 (直接回车可使用默认值或稍后在 .env 填写)")
    print("================================================================")
    for group_name, specs in cred_prompts.items():
        print(f"\n--- [{group_name.upper()}] 渠道参数配置 ---")
        for spec in specs:
            env_key = spec["env"]
            default_val = spec.get("default", "")
            default_hint = f" [默认: {default_val}]" if default_val else ""
            val = input_fn(f"  {spec['prompt']} ({env_key}){default_hint}: ").strip()
            if not val and default_val:
                val = default_val
            if val:
                credentials[env_key] = val

    payload = {
        "libraries": libraries,
        "sources": sources,
        "deliveries": deliveries,
        "deploy_modes": deploy_modes,
        "tags": tags,
        "questions": questions,
        "credentials": credentials,
    }
    result = apply_init_configuration(
        payload,
        custom_yaml_path=custom_yaml_path,
        env_path=env_path,
    )

    print("\n[初始化完成]")
    print(f"  - 配置文件已生成: {result['custom_yaml_path']}")
    print(f"  - 环境变量已写入: {result['env_path']}")
    if result.get("created_console_file"):
        print(f"  - 控制台初始文档: {result['created_console_file']}")
    if result.get("gh_secret_commands"):
        print("\n[GitHub Actions 密钥一键同步命令]")
        for cmd in result["gh_secret_commands"]:
            print(f"  {cmd}")
    return result


def handle_init_cli(argv: list[str] | None = None) -> dict[str, Any] | None:
    """CLI handler for `paper-daily init` and `paper-library init`."""
    parser = argparse.ArgumentParser(
        prog="paper-daily init",
        description="Interactive & Agent-driven initialization wizard for Paper Daily.",
    )
    parser.add_argument(
        "--schema",
        action="store_true",
        help="Output JSON schema of multi-select questions and conditional credential prompts for AI Agents",
    )
    parser.add_argument(
        "--print-skill",
        action="store_true",
        help="Print the Agent SKILL.md definition for Claude Code / OpenClaw / Cursor / Hermes",
    )
    parser.add_argument(
        "--from-json",
        default=None,
        help="Apply configuration non-interactively from a JSON string or JSON file path",
    )
    parser.add_argument(
        "--config-out",
        default="config/custom.yaml",
        help="Target path for generated custom.yaml (default: config/custom.yaml)",
    )
    parser.add_argument(
        "--env-out",
        default=".env",
        help="Target path for generated .env file (default: .env)",
    )
    args = parser.parse_args(argv)

    if args.schema:
        schema = get_agent_skill_schema()
        print(json.dumps(schema, ensure_ascii=False, indent=2))
        return schema

    if args.print_skill:
        skill_md = export_agent_skill_markdown()
        print(skill_md)
        return {"status": "printed_skill"}

    if args.from_json:
        raw = str(args.from_json).strip()
        if Path(raw).is_file():
            raw = Path(raw).read_text(encoding="utf-8")
        payload = json.loads(raw)
        res = apply_init_configuration(
            payload,
            custom_yaml_path=args.config_out,
            env_path=args.env_out,
        )
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return res

    return run_interactive_init(custom_yaml_path=args.config_out, env_path=args.env_out)
