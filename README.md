# Feishu Paper Daily & DeepResearch Framework

<div align="center">

[![Status](https://img.shields.io/badge/status-active-success.svg)]()
[![License](https://img.shields.io/badge/license-AGPLv3-blue.svg)](/LICENSE)
[![GitHub Actions](https://img.shields.io/badge/actions-daily--pipeline-orange.svg)]()

</div>

---

**Feishu Paper Daily & DeepResearch** 是一个由大语言模型（LLM）驱动的自动化科研文献雷达与深度研究（DeepResearch）工作流框架。

系统超越了传统的单一向量相似度检索，通过**多生态控制台（飞书 / Obsidian / Notion / Zotero）**接入用户动态跟踪的研究标签与核心科学问题，实现**动态检索规划、多跳引文扩散、双信号融合推荐、大模型横向裁判、论文正文原位高亮批注、基线双向互联**以及**每日问题级综合与跟进子问题提议**的全闭环。

---

## ✨ 核心特性 (Features)

### 1. 多生态研究控制台 (Multi-Ecosystem Consoles)
- **跨平台统一抽象**：支持在 **飞书 (Wiki / Docx)**、**Obsidian (本地 Vault)**、**Notion (Database)** 或 **Zotero** 中以 Markdown 标准格式维护研究议程：
  - `## 关注标签`：定义当前重点追踪的领域技术词（如 `Memory`, `DecisionModel`, `RL`）。
  - `## 关注问题`：定义正在攻坚的具体科研问题（如 `现有长时记忆系统在多轮交互后如何避免记忆漂移？`）。
- **零代码动态引导**：修改控制台文本即可实时改变每日文献抓取策略与推荐重心，无需变动配置代码。

### 2. DeepResearch 四层闭环演进 (DeepResearch 4-Layer Loop)
- **Layer 1: 动态检索规划 (Query Planning)**：
  大模型基于当前控制台关注的标签与核心问题，自动生成定制化的 Semantic Scholar 针对性检索词和 arXiv 目标分类，替代静态检索词表。
- **Layer 2: 种子多跳引文扩散 (Multi-hop Citation Chasing)**：
  对首轮筛选出的高潜力候选论文作为种子，沿其参考文献 (References) 和施引文献 (Citations) 进行二级多跳扩散检索并去重，挖掘隐藏的关键前沿成果。
- **Layer 3: 问题级每日综合研判 (Question Synthesis)**：
  针对控制台每个追踪问题，大模型分析当日所有候选文献，生成包含**核心结论摘要**、**支撑证据 (论文标题与原文链接)** 以及**当前研究缺口 (Gaps)** 的专题简报。
- **Layer 4: 下一轮子问题推演与自动转向 (Next QA & Pivot)**：
  根据当日文献证据与研读进展，模型自动推演 2~4 个更深度的跟进子问题，追加到飞书控制台的「建议问题（待确认）」区域；同时通过 `ResearchState` 记录证据更新台账，若某问题连续 7 天无新证据突破则主动提议研究转向。

### 3. 品味 + 问题双信号融合推荐与横向裁判 (Fusion Ranking & LLM Judge)
- **品味契合度 (Library Taste)**：基于个人历史文献库的向量相似度与时间衰减打分，捕捉长期学术审美与技术品味。
- **问题匹配度 (Question Fit)**：多并发 LLM 为每篇候选论文对各个关注问题进行 0~10 分的相关性与答案证据打分。
- **动态权重衰减**：对多日无新证据的问题进行权重衰减（0.6x），防止停滞议题霸榜。
- **大模型横向对比裁判 (Comparative Judge)**：由 LLM 对 Top 候选池进行横向比较与全局洗牌，剔除水分论文并输出中文推荐/淘汰理由。
- **多样性保护与探索槽位**：设置单问题推荐上限（Per-question cap），并保留固定探索槽位（Exploration slots）给未命中具体问题但深度符合个人知识库品味的潜力论文。

### 4. 正文原位高亮批注与学术基线双向互联 (In-line Annotations & Bi-directional Linking)
- **正文原位富文本高亮与批注**：彻底取代孤立的底部碎片卡片，直接在论文正文（Abstract）原位做字符级富文本渲染：
  - 🟢 **基线方法 (Baseline)**：淡绿底色高亮。标注模型名称、机制简述、标准录用会议，并关联知识库状态。
  - 🟡 **核心发现 (Claim)**：淡黄底色高亮。标注直接回答关注问题的结论与实验证据。
  - 🟠 **学术质疑 (Critique)**：淡橙底色高亮。指出论文在数据集、合成范围、算力或假设上的局限性。
- **知识库双向文档互联**：
  - **正向链接**：正文提及的 Baseline 若已在个人知识库（飞书精读笔记 / Obsidian / Notion）中收录，自动生成 `🟢 [已入库: 笔记名称]` 跳转双链；未收录则生成权威检索链接。
  - **反向追踪**：自动在个人文献库对应基线文档底部追加 `📌 后续文献对比追踪` 记事，形成动态演进的学术知识图谱。

### 5. 资源池自适应调度与安全合规 (LLM Router & Security)
- **API Key 资源池与智能轮换**：支持配置多把 API Key，自动负载均衡并在遇到 429 频控或权限失效时无缝故障转移；针对长思考推理模型自动做 Token 预算弹性提额。
- **零泄漏安全规范**：全面清洗私有 Token，所有敏感信息收拢至 GitHub Actions Secrets / 本地 `.env`，公共运行日志绝不暴露文档链接与鉴权响应。

---

## 🏗️ 架构概览 (Architecture)

```text
[ 飞书 Wiki / Obsidian / Notion 控制台 ]
       │  (关注标签 & 关注问题)
       ▼
1. 查询规划器 (Query Planner) ──► 动态 S2 检索词 / arXiv 目标分类
       │
       ▼
2. 多源检索与多跳扩散 (Retrieval & Multi-Hop Chasing)
       ├── arXiv RSS & Semantic Scholar API
       └── 顶尖候选种子 ──► 引文 / 参考文献二级扩散
       │
       ▼
3. 学术质量把关 (Quality Gate) ──► 过滤作坊论文与低质预印本
       │
       ▼
4. 双信号融合推荐 (Fusion & Selection)
       ├── 向量相似度 (个人文献库历史品味)
       ├── 关注问题契合度 (LLM 0-10 分逐题打分)
       └── 横向裁判 (Comparative Judge 全局重排)
       │
       ▼
5. 正文行内批注与基线对齐 (In-line Annotations & Baseline Linking)
       ├── 正文原位高亮: 基线 (绿) / 发现 (黄) / 局限 (橙)
       └── 个人知识库对齐 ──► 飞书正向双链 + 历史笔记反向追踪回写
       │
       ▼
6. 深度研究研判与议题演进 (Synthesis & Next QA)
       ├── 每日问题证据简报与研究空白 (Gaps)
       └── 提议后续跟进子问题 ──► 反写回控制台「建议问题（待确认）」
```

---

## 🚀 快速上手 (Quick Start)

### 1. 本地运行 (Local Environment)

本项目采用 [uv](https://github.com/astral-sh/uv) 管理 Python 虚拟环境与依赖。

```bash
# 1. 克隆仓库
git clone https://github.com/link231rog/feisu-paper-daily.git
cd feisu-paper-daily

# 2. 安装依赖
uv sync

# 3. 配置本地环境变量 (.env)
cp .env.example .env
# 编辑 .env 填入你的 FEISHU_* 与 LLM_API_KEYS 等凭据

# 4. 执行全流程
uv run src/zotero_arxiv_daily/main.py
```

### 2. GitHub Actions 自动化部署 (Hosted Pipeline)

1. **Fork 本仓库** 到你的个人 GitHub 账号。
2. 进入仓库 **Settings -> Secrets and variables -> Actions**，配置以下 Secrets：

| Secret 名称 | 作用说明 | 示例 / 说明 |
| :--- | :--- | :--- |
| `FEISHU_APP_ID` | 飞书开放平台自建应用 App ID | `cli_xxx` |
| `FEISHU_APP_SECRET` | 飞书应用 App Secret | `xxx` |
| `FEISHU_WIKI_SPACE_ID` | 飞书知识库空间 Space ID | `748xxxx` |
| `FEISHU_CANDIDATE_NODE_TOKEN` | 候选文献流文档的 Node Token | 每日推送候选库目标节点 |
| `FEISHU_CONSOLE_NODE_TOKEN` | 推荐控制台文档的 Node Token | 存放关注标签与问题的文档 |
| `FEISHU_NOTES_PARENT_NODE_TOKEN` | 精读笔记存放的父节点 Node Token | 用户确认入库文献的目标父节点 |
| `LLM_API_KEYS` | 大模型 API Key 资源池（逗号分隔） | `key1,key2,key3` |
| `TRANSLATION_API_KEY` | 备选学术翻译服务 API Key | 常用模型或翻译接口 Key |
| `ZOTERO_ID` / `ZOTERO_KEY` | (可选) Zotero 账户 ID 与 API Key | 用于同步 Zotero 个人文献库 |
| `NOTION_TOKEN` / `NOTION_DATABASE_ID` | (可选) Notion 凭据 | 用于读取 Notion 文献数据库 |

3. 进入 **Actions** 页面，手动触发 **Feishu Paper Daily** 测试运行；流水线默认通过定时 Cron 每天自动执行推送。

### 3. 交互式架构工作台 (Architecture Workbench)

本项目附带一套完整的 React / Vite 架构诊断与重构沙盘看板（位于 `workbench/`），提供假设状态机 30 天推演、模块瓶颈 Diff 对照、四端数据映射与零污染工作流定制：

```bash
cd workbench
bun install  # 或 npm install
bun run dev  # 启动本地开发服务器预览看板 (http://localhost:3000)
```

---

## ⚙️ 核心配置说明 (Configuration)

配置采用 Hydra / OmegaConf 体系，在 `config/base.yaml` 定义默认项，在 `config/custom.yaml` 中通过 `${oc.env:...}` 动态映射环境变量：

```yaml
research:
  enabled: true
  multi_hop: true          # 是否开启多跳引文追踪扩散
  max_seeds: 4             # 参与多跳扩散的顶尖种子论文数量
  synthesis: true          # 是否生成每日问题级综合简报
  next_questions: true     # 是否在控制台提议下一轮跟进子问题
  
  # 融合打分与裁判机制
  weight_taste: 0.5        # 个人文献库品味权重 (0.0 ~ 1.0)
  weight_fit: 0.5          # 关注问题匹配度权重 (0.0 ~ 1.0)
  qa_workers: 8            # 问题相关性打分并发线程数
  judge: true              # 是否开启横向大模型裁判全局排序
  max_judge: 25            # 参与横向裁判的候选数量
  per_question_cap: 6      # 单个问题最大推荐数量（防止单一议题霸榜）
  exploration_slots: 2     # 为知识库高品味潜力论文保留的探索槽位
  
  # 正文原位批注与基线互联
  inline_annotations: true # 是否直接在正文进行富文本高亮与批注
  baselines: true          # 是否提取核心对比基线
  auto_backlink: true      # 是否向知识库已有笔记追加反向追踪记录

console:
  enabled: true
  provider: auto           # 支持 feishu, obsidian, notion, zotero, static
  node_token: ${oc.env:FEISHU_CONSOLE_NODE_TOKEN,null}
```

---

## 📂 核心模块速查 (Codebase Reference)

- `src/zotero_arxiv_daily/executor.py`：全流程总控调度器（检索、过滤、排序、批注、发布）。
- `src/zotero_arxiv_daily/research.py`：DeepResearch 核心算法（规划、多跳选种、问题综合、跟进推演、横向裁判）。
- `src/zotero_arxiv_daily/annotator.py`：正文原位高亮与批注提取器，负责精确字符切分与富文本 Run 组装。
- `src/zotero_arxiv_daily/baseline.py`：基线方法抽取、学术出处检索与个人知识库实体对齐。
- `src/zotero_arxiv_daily/console.py`：多生态控制台加载器（飞书 / Obsidian / Notion / Zotero）。
- `src/zotero_arxiv_daily/feishu.py`：飞书 API 深度封装（富文本 Docx 渲染、双向回写、权限校验、精读笔记转换）。
- `src/zotero_arxiv_daily/llm.py`：大模型负载均衡路由器（多 Key 轮换、故障转移、推理预算控制）。
- `src/zotero_arxiv_daily/library.py`：Obsidian Vault 与 Notion Database 文献库解析适配器。

---

## 📃 License

本项目基于 AGPLv3 协议开源分发。详见 [LICENSE](/LICENSE)。
