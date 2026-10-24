# Feishu Paper Daily 2.0 — 深度架构诊断与多生态重构交互式看板

针对 `feisu-paper-daily` 现有代码库的深度静态分析，构建一套集**架构瓶颈诊断、AI 主动问题追踪推演、四端（飞书 / Zotero / Notion / Obsidian）统一双向适配器重构、以及纯 GitHub Actions 零本地依赖工作流**于一体的交互式架构看板与代码重构方案交付平台。

---

## User Review & Critical Decisions

> [!IMPORTANT]
> 以下核心架构演进方向已根据您的确认全面纳入本次交互式架构看板与重构代码库方案中：

- **交付形态确认**：打造**深度架构诊断与代码重构交互式看板（Architecture Diagnosis & Refactoring Workbench）**。应用内不仅提供对现有 Python 源码（`executor.py`、`research.py`、`annotator.py`、`console.py`、`library.py`、`feishu.py`）的逐模块瓶颈剖析，还提供**交互式架构沙盘、重构前后代码 Diff 对比器、多端数据映射模拟器**，以及可一键复制/导出的 2.0 生产级 Python 模块与 GitHub Actions YAML 源码。
- **AI 主动追踪与批注的四大突破**：
  1. **跨日演化问题状态机（Hypothesis & Question State Machine）**：将 `ResearchState` 从单纯记录日期升级为四态演化（`🌱 探索期 Exploring` ➔ `⚖️ 争议/待验证 Contested` ➔ `✅ 证据链收敛 Converged` / `❌ 假设证伪 Falsified`），动态驱动检索策略。
  2. **超越摘要的全文/章节级靶向批注（ar5iv HTML / PDF Section Parser）**：针对 Top 推荐或勾选论文，按需拉取 `ar5iv` HTML 的 `Method`、`Experiments`、`Limitations` 章节，解决仅靠 2000 字摘要无法核查实验消融与真实算力假设的痛点。
  3. **对立证据与反例追踪（Adversarial & Counter-Evidence Querying）**：在 `plan_queries` 与 `judge_ranking` 中引入对抗检索通道，专门捕获反驳当前主流假设或暴露 Baseline 缺陷的论文，并在正文中新增 `⚡ [反例/证伪证据]` 批注类型。
  4. **文档内 `@AI` 异步追问闭环（In-Doc `@AI` Async Thread Loop）**：在 GitHub Actions 定时/触发巡检时，扫描飞书/Notion/Obsidian/Zotero 笔记中的 `@AI: 你的问题` 标记或评论块，携带对应论文全文上下文定向解答并原位写回。
- **四端全链路双向适配（Bidirectional Sync Adapter）**：打破目前“仅飞书闭环、其余三端只读”的割裂现状，建立统一的 `WorkspaceSinkAdapter` 抽象协议，补齐 **Notion 块级 Callout 与属性映射**、**Zotero 子笔记（Child Note）与标签联动**、以及 **Obsidian 远端 Git Submodule / 跨仓库读写与 `[[]]` 双向回链**。
- **纯 GitHub Actions 零污染与按需触发架构（Zero-Local Serverless Workflow）**：废除主分支状态文件直接提交，改用 **Orphan 独立数据分支（`state-store`）+ GitHub Actions Cache 双写方案**持久化 `paper_store.json` 与 `research_state.json`；结合 `repository_dispatch` / 轻量 Webhook 桥接实现多端打星/勾选即时触发单篇精读。

---

## 1. Overview & Core Concept

- **What It Does**：
  本应用是专为 `feisu-paper-daily` 打造的**架构演进与代码重构工程看板**。它将原本隐藏在 280KB Python 脚本中的检索、打分、批注、回写逻辑可视化，直观呈现现有版本（v1.x）的 6 大架构瓶颈，并提供可交互验证的 v2.0 重构蓝图、状态机模拟器、四端渲染效果预览及可直接落地的重构代码补丁。
- **Target Audience / Persona**：
  追求极致自动化与本地零负担的 AI 领域研究者与个人知识库架构师——希望在飞书、Zotero、Obsidian、Notion 之间自由切换或协同，让 AI 成为真正具备“学术假设证伪能力”和“跨日记忆”的研究搭档。
- **Key Value**：
  1. **看清瓶颈**：精准定位 v1.x 代码中如 `annotator.py` 摘要截断、`console.py` 单向读取、`main.yml` 状态丢失等隐患。
  2. **交互推演**：在看板中实时模拟“问题状态机跨日演化”、“全文级正反方证据批注”与“四端同步数据结构映射”。
  3. **即拿即用**：提供完整的重构版 Python 核心模块代码（Diff 对照视图 + 完整源码复制/导出）与零污染版 `.github/workflows/paper-daily-v2.yml`。

---

## 2. User Experience & Visual Design

- **Key User Flows**：
  1. **架构全景与瓶颈诊断（Architecture & Bottleneck Audit）**：进入工作台，左侧切换“v1.x 现状诊断”与“v2.0 目标架构”拓扑图；点击任意模块节点（如 `research.py`、`annotator.py`、`library.py`、`main.yml`），右侧展开源码级痛点剖析、性能/Token 开销评估与重构前后对比。
  2. **AI 主动研究与批注沙盘（Active Research & Annotation Sandbox）**：
     - 切换查看**跨日问题状态机**，观察一个研究问题如何在 14 天内经历“提出假设 ➔ 发现正向证据 ➔ 触发对抗检索发现反例 ➔ 修正为子问题”的完整生命周期。
     - 对比 **v1.x 仅摘要批注** vs **v2.0 全文章节靶向批注 + `@AI` 原位追问** 的真实学术论文渲染差异（支持高亮基线、核心发现、学术质疑、反例证据及 `@AI` 异步问答折叠块）。
  3. **多生态四端适配矩阵（Multi-Ecosystem Adapter Matrix）**：在飞书 Docx、Zotero（Item + HTML Child Note）、Notion（Database Properties + Callout Blocks）、Obsidian（YAML Frontmatter + Callout + `[[WikiLinks]]`）四个选项卡之间切换，实时预览同一篇带批注论文与反向基线追踪在四端的原生数据结构与交互闭环方式。
  4. **纯 GitHub Actions 零本地运维方案（Zero-Local CI/CD Blueprint）**：交互式配置个人的目标生态组合（如 `Zotero + Obsidian` 或 `飞书 + Notion`），自动生成定制化的 `paper-daily-v2.yml`（含 `state-store` Orphan 分支持久化、按需精读 `workflow_dispatch` / `repository_dispatch` 触发器及 Secrets 清单）与重构后的 Python 核心模块代码包。

- **Visual Identity & Theme**：
  - *Aesthetic Direction*：**High-Craft Technical Architecture Studio（高精密学术工程控制台）**。采用深邃冷调石板灰（Deep Slate）为主画布，搭配清晰的 1px 结构分割线、等宽数据指标与高对比度语义高亮（复用原项目的绿/黄/橙批注语义并扩展紫/青状态色）。
  - *Color Palette & Mood*：
    - 主背景画布：`#0B0F19`（深邃夜空灰，占 60% 视觉面积）
    - 结构容器表面：`#111827` 至 `#1E293B`，配 `1px solid rgba(255,255,255,0.08)` 细线边框（占 30% 视觉面积）
    - 语义与交互强调色（占 10% 视觉预算）：
      - 基线方法（Baseline）：`#10B981`（Emerald 绿）
      - 核心发现（Claim）：`#F59E0B`（Amber 黄）
      - 学术质疑（Critique）：`#F97316`（Orange 橙）
      - 反例/证伪（Counter-Evidence）：`#EC4899`（Rose/Pink 粉红）
      - `@AI` 追问与系统主控操作：`#38BDF8`（Sky Blue 青蓝）
  - *Typography & Hierarchy*：
    - 标题与架构导航：`Plus Jakarta Sans`（SemiBold 600，紧凑字距，确保工程感与现代感）
    - 正文与学术摘要排版：`DM Sans`（Regular 400 / Medium 500，行高 1.65，适合长文阅读与架构说明）
    - 代码 Diff、YAML 配置与指标数据：`JetBrains Mono`（强制开启 `tabular-nums`，对齐行号、Token 消耗与得分矩阵）
  - *Component Styling & Layout*：
    - 遵循 **SaaS & Developer Console** 规范：左侧固定宽度架构导航栏（`260px`）+ 顶部三区单行导航栏（Top Bar Contract）+ 主视口高密度单层卡片网格（Single-Elevation Depth，严禁卡片套卡片或粗左边框 `border-l-4`）。
    - 所有元数据（如模块行数、API 耗时、状态标签）采用无胶囊纯文本排印加 `·` 分隔符（Zero-Pill Discipline）。

---

## 3. Key Product Decisions & Trade-Offs

- **Decision 1：问题追踪从“被动关键词打分”升级为“带正反双向检索的假设状态机”**
  - *Chosen Approach*：将控制台中的每个关注问题建模为具备生命周期的状态机（`exploring` ➔ `contested` ➔ `converged` / `falsified`），并在 `plan_queries` 中为 `exploring/contested` 状态的问题自动生成 1 条**对抗性检索式（Counter-Query，如寻找 failure modes / ablation degradation / negative results）**。
  - *Why*：现有 `research.py` 中的 `saturated()` 仅靠“连续 7 天未命中或有命中”做简单 0.6x 衰减，容易产生确认偏误（Confirmation Bias），且无法区分“这个问题已经被完美解答”与“这个问题目前搜不到论文”。
  - *Alternatives Considered*：完全交由 LLM 自由决定每天搜什么——被否决，因为缺乏显式状态约束会导致多日运行后检索方向漂移且不可控。

- **Decision 2：两阶段按需全文章节拉取（Two-Stage Section-Targeted Parsing）取代全量 PDF 解析**
  - *Chosen Approach*：日常初筛（Top 25）依然使用 Abstract 进行轻量打分与横向裁判；仅对最终入选 Top N（如 5~8 篇）或用户勾选精读的论文，优先通过 `https://ar5iv.labs.arxiv.org/html/{arxiv_id}` 提取结构化 HTML 的 `Method`、`Experiments`、`Limitations` 段落（若无 HTML 则 fallback 到 PyMuPDF 文本流抽取），再交由 `annotator.py` 生成跨章节细粒度批注。
  - *Why*：在 GitHub Actions 中用 MinerU 或视觉大模型解析几十篇 PDF 会导致运行超时且 Token 成本激增；而 `ar5iv` HTML 天然具备 `<section>` 语义标签，拉取耗时仅需 0.5 秒/篇，零 OCR 成本即可拿到实验表格与局限性原文。

- **Decision 3：统一抽象 `KnowledgeSinkAdapter` 解决四端能力不对称**
  - *Chosen Approach*：将原本紧耦合在 `executor.py` 和 `feishu.py` 中的推送、勾选扫描、反向回写抽离为标准的 `KnowledgeSinkAdapter` 接口（包含 `fetch_console()`, `push_daily_candidates()`, `poll_user_actions()`, `write_deep_note()`, `append_backlink()` 五大原子方法），分别为 Feishu、Notion、Zotero、Obsidian 提供对等实现。
  - *Why*：现有代码中 `library.py` 和 `console.py` 对 Notion/Obsidian/Zotero 只有百余行读取代码，而 `feishu.py` 高达 116KB，导致非飞书用户无法享受行内高亮批注、反向基线回写与勾选精读。通过统一 AST 中间表示（`AnnotatedDocumentAST`），一次批注即可编译为飞书 Docx Run、Notion RichText/Callout、Zotero HTML Note 与 Obsidian Markdown Callout。

- **Decision 4：Orphan 独立分支（`state-store`）持久化状态，保持主分支 100% 纯净**
  - *Chosen Approach*：在 GitHub Actions 中使用 `git worktree` 将名为 `state-store` 的 Orphan 分支挂载到 `.state/` 目录，每次运行自动从 `.state/paper_store.json` 和 `.state/research_state.json` 读写并 push 回 `state-store` 分支，彻底脱离 `main` 分支。
  - *Why*：现有 `main.yml` 设置了 `contents: read` 且未提交 `data/*.json`，导致每次 GitHub Actions 跑完后去重记录和问题演化状态全部丢失；若直接向 `main` 分支 commit 又会污染代码提交历史并引发本地 `git pull` 冲突。Orphan 分支方案兼具永久持久化、可审计与主干零污染。

---

## 4. Technical Architecture & Data Strategy *(Technical Reference)*

### 4.1 架构演进与组件拓扑图 (v1.x 痛点 vs v2.0 升级架构)

```text
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                     Cloud Consoles (Remote Zero-Local Control Plane)                     │
│   [Feishu Wiki Console]   [Notion Console DB]   [Zotero Pinned Note]   [Obsidian Git]    │
└───────────────────┬──────────────────────────────────────────────────┬───────────────────┘
                    │ 1. Load Questions, Hypothesis States & `@AI`     │ 6. Poll Checked /
                    ▼    Follow-up Threads                             │    Starred Papers
┌──────────────────────────────────────────────────────────────────────┴───────────────────┐
│                      GitHub Actions Serverless Runtime (Zero-Local)                      │
│  ┌────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ State Layer: Orphan Branch `state-store` (.state/paper_store.json & research.json) │  │
│  └──────┬──────────────────────────────────────────────────────────────────────▲──────┘  │
│         ▼                                                                      │         │
│  ┌─────────────────────────────────────────────────────────────────────────────┴──────┐  │
│  │ 2. Active Research Engine (research_v2.py)                                         │  │
│  │    ├─ Hypothesis State Machine (Exploring ➔ Contested ➔ Converged / Falsified)     │  │
│  │    ├─ Dual Query Planner: Affirmative Queries + Adversarial Counter-Queries        │  │
│  │    └─ Multi-Hop Citation Chasing + Comparative LLM Judge                           │  │
│  └──────┬─────────────────────────────────────────────────────────────────────────────┘  │
│         ▼                                                                                │
│  ┌────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ 3. Two-Stage Full-Text Annotator & Baseline Linker (annotator_v2.py & baseline.py) │  │
│  │    ├─ Stage 1: Abstract-level filtering & scoring                                  │  │
│  │    ├─ Stage 2: ar5iv HTML / PDF Section Fetcher (Method / Experiments / Limits)    │  │
│  │    ├─ 4-Color Inline AST: 🟢Baseline  🟡Claim  🟠Critique  ⚡Counter-Evidence      │  │
│  │    └─ `@AI` Thread Resolver: Answers inline user questions with paper full-text    │  │
│  └──────┬─────────────────────────────────────────────────────────────────────────────┘  │
│         ▼                                                                                │
│  ┌────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ 4. Universal AST Compiler & Bidirectional Sink Adapters (adapters/*.py)            │  │
│  │    ├─ FeishuAdapter   ──► Docx RichText Runs + Wiki Backlinks + `@AI` Reply Blocks │  │
│  │    ├─ NotionAdapter   ──► Database Properties + Colored RichText + Callout Blocks  │  │
│  │    ├─ ZoteroAdapter   ──► Pyzotero Item Tags (`#to-read`) + HTML Child Notes       │  │
│  │    └─ ObsidianAdapter ──► Git Submodule / Repo Push + YAML + `[[WikiLinks]]`       │  │
│  └────────────────────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 交互式看板应用的数据模型与状态设计 (Interactive Workbench State)

在我们将构建的 Web 交互式架构看板中，包含以下核心数据模块与工作流：

1. **源码诊断审计库 (`AuditModule[]`)**：
   - 收录对您上传的 `feisu-paper-daily` 真实源码文件的逐行级审计数据（含 `executor.py`、`research.py`、`annotator.py`、`baseline.py`、`console.py`、`library.py`、`feishu.py`、`.github/workflows/main.yml`）。
   - 支持按严重程度（架构阻断 / 交互受限 / 维护性隐患）、所属维度（AI 交互 / 多端适配 / GitHub Actions 轻量化）过滤，并提供 **v1.x 原生代码 vs v2.0 重构代码 Side-by-Side Diff 视图**。
2. **AI 主动追踪与全文批注模拟器 (`ResearchSimulatorState`)**：
   - **问题状态机推演器**：内置真实学术议题（如 *"Long-context KV cache compression vs retrieval drift"*），支持点击步进模拟 Day 1 ➔ Day 14 的状态跃迁、正反双向 Query 生成、以及自动生成待确认子问题。
   - **全文靶向批注 & `@AI` 追问交互器**：展示从仅 Abstract 批注升级到拉取 `ar5iv` 实验章节后的细粒度高亮效果；用户可在模拟器中直接输入 `@AI: 这篇论文在 128K 长度下的消融实验是否对比了 SnapKV？`，实时演练 GitHub Action 异步扫描并原位插入解答块的完整闭环。
3. **四端双向适配器转换沙盒 (`AdapterPreviewState`)**：
   - 将同一套 `AnnotatedPaperAST` 实时编译并渲染为 **飞书云文档视图**、**Notion 数据库页面视图**、**Zotero 桌面端条目+子笔记视图**、**Obsidian 双链 Markdown 源码与预览视图**，直观展示四端如何实现勾选入库、行内四色高亮、反向基线回写与 `@AI` 追问。
4. **纯 GitHub Actions 定制生成器 (`WorkflowBuilderState`)**：
   - 提供交互式勾选面板（选择启用的知识库端、配置状态持久化模式 `Orphan Branch` vs `Actions Cache`、配置按需精读触发频率），动态生成完整的 `.github/workflows/paper-daily-v2.yml` 与对应的 Python 适配器代码，支持一键复制或打包下载。
