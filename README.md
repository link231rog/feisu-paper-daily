# Paper Daily · 多源学术文献精读、问题追踪与多渠道推送系统

<div align="center">

[![Website](https://img.shields.io/badge/website-paper--daily.pages.dev-black.svg)](https://paper-daily-e9f.pages.dev)
[![License](https://img.shields.io/badge/license-AGPLv3-blue.svg)](/LICENSE)
[![Tests](https://img.shields.io/badge/tests-19%20passed-success.svg)]()

</div>

**Paper Daily** 是一套面向科研人员与工程团队的自动化每日文献推荐、审稿级精读批注、跨日科学问题追踪与多渠道分发流水线（含飞书云文档、微信公众号草稿箱、Telegram 原生音频/卡片、HTML 邮件及可选 MP3 双人学术播客）。

---

## 一、 核心架构与目录组织

代码库按职责划分为三大核心子包与检索/重排插件层，同时在顶层保留向后兼容导入垫片：

```text
src/zotero_arxiv_daily/
├── core/                  # 核心审阅、评分、研究闭环与状态存储
│   ├── annotator.py       # 摘要行内三色高亮批注与字符偏移定位
│   ├── baseline.py        # 对比基线提取与个人文献库双向回链
│   ├── digest.py          # Critical-Paper-Digest 审稿级摘要与 4D Rubric 量化评分
│   ├── interest.py        # 多生态个人文献库（飞书/Obsidian/Notion/Zotero）兴趣语料构建
│   ├── llm.py             # 多 Key 轮询、并发限流与多任务 LLM 路由器
│   ├── paper_store.py     # 跨源去重、已推送记录与负向反馈（移出待选）持久化
│   ├── research.py        # DeepResearch 查询规划、多跳引文追踪与问题证据综述
│   ├── textutil.py        # 鲁棒 JSON 解析与文本工具
│   └── translator.py      # 学术摘要中英双语翻译
├── pipeline/              # 模块化 DAG 流水线引擎与有序容灾降级链 (方案 B)
│   ├── base.py            # Backend, FallbackChain, PipelineContext, PipelineStage 核心抽象
│   ├── engine.py          # 6 阶段流水线调度引擎与生命周期钩子
│   ├── backends/          # 有序降级后端 (AgentReachCLI, ArxivHtml, PyMuPDF, Trafilatura)
│   └── stages/            # 独立执行阶段 (Ingest, Fetch, Rerank, Enrich, Digest, Delivery)
├── channels/              # 多渠道排版、音频合成与推送适配器
│   ├── audio.py           # MP3 双人播客（NotebookLM 风格）/ 学术早报 / 微信 60s 语音合成
│   ├── daily_report.py    # 邮件与通用 HTML 日报构建器
│   ├── feishu.py          # 飞书云文档/知识库日报、全双语精读笔记与顶部音频块挂载
│   ├── telegram.py        # Telegram HTML 消息分片推送与原生 sendAudio 音频播放器
│   └── wechat.py          # 微信公众号三模式推文、内联 CSS、外链转脚注与语音/封面素材上传
├── library/               # 跨平台文献库同步、批注还原与初始化向导
│   ├── bridge.py          # paper-library 命令行检索、批注还原与混合排序
│   ├── console.py         # 飞书 / Obsidian / Notion / Zotero 控制台指令与自定义 Skill 解析
│   └── init_wizard.py     # 多选交互式初始化向导与按需凭证配置生成
├── retriever/             # 多源学术文献与社区热点检索器
│   ├── arxiv_retriever.py            # arXiv API 检索与开源代码/主页链接提取
│   ├── huggingface_retriever.py      # Hugging Face Daily Papers 检索与实时社区热度交叉赋能
│   ├── semantic_scholar_retriever.py # Semantic Scholar 关键词与种子引文多跳检索
│   ├── openreview_retriever.py       # OpenReview API v2 顶会投稿与审稿检索
│   ├── dblp_retriever.py             # DBLP 计算机顶会/期刊文献检索
│   ├── rxiv_retriever.py             # bioRxiv / medRxiv / chemRxiv 预印本检索
│   ├── github_trending_retriever.py  # GitHub AI 趋势仓库检索
│   └── news_retriever.py             # AI 实验室官方博客与 Hacker News 动态检索
└── reranker/              # 多峰相似度、负反馈抑制与多样性重排层
    ├── base.py            # Max-TopK 多峰匹配、Rocchio 负反馈、外部信号加成与 MMR 多样性选择
    ├── local.py           # 本地 Embedding / TF-IDF（含纯 NumPy 零依赖回退）重排器
    └── api.py             # 远程 OpenAI 兼容 Embedding API 重排器
```

---

## 二、 核心能力与算法特性

### 1. 文献推荐与粗排/重排算法
- **Max-TopK 多峰兴趣锚点匹配（Multi-Peak Anchor Similarity）**：
  克服传统全库均值池化将多个独立研究方向稀释为平庸向量的问题，融合单篇最高锚点相似度（`max_sim_alpha: 0.45`）与 Top-K 锚点均值（`top_k_anchors: 5`）及指数时间衰减，自动记录命中的代表作标题（`matched_anchor_title`）。
- **Rocchio 负向原型反馈（Negative Prototype Feedback）**：
  结合用户在日报中勾选「移出待选」的历史负样本（`PaperStore.recent_discarded_texts`）与控制台负向排除词，当候选论文与负向原型的最大相似度超过阈值（`rocchio_neg_threshold: 0.18`）时施加线性扣分（`rocchio_beta: 0.35`）。
- **MMR 最大边缘相关性多样性去重（Maximal Marginal Relevance）**：
  在每日精选截断阶段引入 `mmr_select`（`mmr_lambda: 0.75`），抑制同一天内高度同质化的跟风论文刷屏，保障精读列表的方法多样性。
- **外部冷启动信号与开源代码加成**：
  - 自动从摘要与正文中提取论文专属 GitHub 代码仓库（`code_url`）与项目主页（`project_url`），自动过滤 `pytorch/pytorch` 等通用框架链接，并对开源代码论文给予复现加分（`code_boost: 0.4`）。
  - 交叉比对 **Hugging Face Daily Papers** 免费 API，提取社区点赞热度（`hf_upvotes`）并施加对数缩放加成（`hf_boost_max: 0.8`），解决今日新发 arXiv 论文引用数为 0 的冷启动盲区。

### 2. 审稿级精读摘要与四维量化评分（4D OpenReview Rubric）
- **四维 1–5 分量化打分（`rubric_scores`）**：
  1. `delta`（实质创新与增量）：问题定义或核心算子是否有非平凡突破；
  2. `rigor`（实验与消融严谨度）：基线是否公平、消融是否完备、是否诚实披露算力代价；
  3. `actionability`（对自身研究/工程的可迁移性）：机制或结论能否直接借用；
  4. `reproducibility`（开源与复现友好度）：是否公开代码仓库、超参与模块细节。
- **综合校准总分与二次重排（`composite_score`）**：
  由 4D Rubric 加权映射至 0–10 分，并对「证据存疑/基线较弱」论文执行封顶惩罚（`<= 5.8`），在精读生成后自动重排「精读必看」与「速览雷达」层级。

### 3. 可选多模态音频播客与 Google NotebookLM 专题沉淀
支持将每日精选论文与追踪问题综述自动合成为音频播客，并支持 **Edge-TTS** 与 **Google NotebookLM** 独立双轨并行输出：
- **Edge-TTS 引擎（极速轻量免密）**：
  - **`dialogue`（双人对谈播客模式，NotebookLM 风格）**：由女声主持（`zh-CN-XiaoxiaoNeural` / `nova`）抛出研究痛点与批判追问，男声学者（`zh-CN-YunxiNeural` / `onyx`）拆解核心增量、四维评分与开源复现价值，男女声交替对谈。
  - **`briefing`（单人高密度学术早报模式）**：单人主播 3~5 分钟快速串讲今日问题进展与精选论文核心结论。
  - **`wechat_60s`（微信公众号 60 秒语音导读）**：严格控制在 210 字以内（时长 ≤ 55 秒、体积 ≤ 2MB），适配微信公众号永久语音素材限制。
  - 逐轮语音合成后在纯 Python 内剥离次段 ID3v2 标签头并注入 MPEG-1 Layer 3 静音帧间隔拼接，无需宿主机安装 `ffmpeg`。
- **Google NotebookLM 引擎（专题知识库与官方原生 Audio Overview 播客）**：
  - 基于 [`teng-lin/notebooklm-py`](https://github.com/teng-lin/notebooklm-py) 官方逆向 API 实现，支持按 Topic 标签自动投喂：
    - **`persistent` 模式（默认，长效沉淀）**：每个研究专题（如 `[Topic] Agent Memory`）维护专属长效笔记本，新文献自动追加；当单本容量接近 50 篇限额时（阈值 45 篇），系统自动滚动开启 `Vol.2`、`Vol.3` 分卷继续累积。
    - **`daily` 模式（单期隔离）**：每日按 Topic 独立建本（如 `2026-10-28 [Topic] Agent Memory`），完全聚焦当日新论文对比。
  - 调用 Google Gemini 官方双人播客生成引擎（具有真实的换气声、语气起伏与自然打断），直接下载为高质量音频并推送到各渠道。
- **全渠道双轨独立投递**：
  - **本地归档**：分别保存至 `data/audio/daily_podcast_YYYY-MM-DD.mp3` 与 `data/audio/notebooklm/`。
  - **Telegram**：通过 Bot API 分别推送 `[Edge-TTS 版]` 与 `[NotebookLM 深度版]` 专属原生播放器。
  - **邮件**：通过 `MIMEMultipart("mixed")` 将两份音频作为独立附件发送。
  - **飞书日报文档**：通过飞书云空间媒体上传接口将两份音频分别挂载在日报文档顶部，供读者自主挑选试听。
  - **微信公众号**：自动将 60 秒浓缩语音导读上传至公众号永久素材库。

---

## 三、 快速开始与常用命令

### 0. 零安装全云端运行（Agent-Native Skill，推荐）

**本地无需安装 Python、无需 `git clone` 代码**。只需将本项目提供的单个 Skill 文件加入到您的 AI Agent（Claude Code、OpenCode、Cursor、Hermes 等）中：

- **Skill 文件路径**：[`skills/paper-daily/SKILL.md`](skills/paper-daily/SKILL.md)
- **Agent 执行流程**：
  1. Agent 自动调用 `gh repo fork link231rog/feisu-paper-daily --clone=false` 将流水线远程 Fork 到您的 GitHub 账号中。
  2. Agent 对话询问您关心的研究方向与接收渠道（飞书 / 邮件 / Telegram / 微信），自动将密钥写入云端 GitHub Secrets。
  3. Agent 远程触发首轮云端运行，后续每日自动在 GitHub Actions 免费调度，通过云端或 Webhook 随时对话交互。

---

### 1. 本地开发者环境安装（可选）

```bash
# Python 后端流水线安装（推荐使用 uv）
uv sync

# 前端交互工作台安装与启动
cd workbench && bun install && bun run dev
```

### 2. 交互式初始化向导

支持通过多选交互向导一键生成 `config/custom.yaml`、`.env` 以及 GitHub Actions Secrets 配置命令：

```bash
# 终端交互式多选配置向导
uv run paper-daily init

# 查看/导出 Agent-Native 零安装 Skill 定义
uv run paper-daily init --print-skill

# Agent / 自动化 JSON 配置注入
uv run paper-daily init --from-json '{"libraries":["obsidian","feishu"],"sources":["arxiv","huggingface","openreview"],"deliveries":["feishu","telegram","wechat"]}'
```

### 3. 开启可选 MP3 音频播客推送

在 `config/custom.yaml` 中开启 `audio.enabled`：

```yaml
audio:
  enabled: true
  mode: "dialogue"               # "dialogue" (双人对谈播客) | "briefing" (单人学术早报)
  engine: "edge-tts"             # "edge-tts" (默认免费) | "openai" (兼容 OpenAI /v1/audio/speech)
  host_voice: "zh-CN-XiaoxiaoNeural"
  guest_voice: "zh-CN-YunxiNeural"
  speech_rate: "+5%"
  max_papers: 5
  output_dir: "data/audio"
  attach_telegram: true          # 推送 Telegram 原生音频播放器
  attach_email: true             # 作为邮件 MP3 附件发送
  attach_feishu: true            # 挂载到飞书日报文档顶部
  upload_wechat_voice: true      # 生成 60 秒浓缩版并上传微信公众号语音素材库
```

### 4. 运行测试

```bash
uv run pytest tests/test_smoke.py
```

---

## 四、 开源致谢与参考项目引用 (Acknowledgments & Citations)

本项目在架构演进、推荐算法、审稿评估、音频播客生成与多渠道排版方面吸收并借鉴了以下优秀开源项目的思想与组件，特此致谢并列出完整引用：

### 1. 基础架构与文献推荐算法
- **[`link231rog/feisu-paper-daily`](https://github.com/link231rog/feisu-paper-daily)**（作者：Zixuan Huang / `@link231rog`）  
  *引用说明*：本项目的核心前身与基础框架，提供了飞书云文档/知识库双向协同、行内三色高亮批注、DeepResearch 多跳追问闭环与多生态文献库底座。
- **[`TideDra/zotero-arxiv-daily`](https://github.com/TideDra/zotero-arxiv-daily)**  
  *引用说明*：提供了基于个人 Zotero 文献库语料与 GitHub Actions 定时任务驱动的每日 arXiv 推荐流水线原型设计。
- **[`karpathy/arxiv-sanity-preserver`](https://github.com/karpathy/arxiv-sanity-preserver) & [`Disham220/arxiv_sanity_x`](https://github.com/Disham220/arxiv_sanity_x)**  
  *引用说明*：借鉴了其基于正负样本反馈的 **Rocchio 负向原型抑制（Negative Prototype Feedback）** 与 **MMR（Maximal Marginal Relevance）多样性去重** 思想，用于抑制已「移出待选」方向的同质化论文。
- **[`AutoLLM/ArxivDigest`](https://github.com/AutoLLM/ArxivDigest) & [`dw-dengwei/daily-arXiv-ai-enhanced`](https://github.com/dw-dengwei/daily-arXiv-ai-enhanced)**  
  *引用说明*：借鉴了多兴趣方向下的 **Max-TopK 多峰锚点相似度匹配（Multi-Peak Anchor Similarity）** 与结构化速览生成思路。

### 2. 审稿级量化评分与外部冷启动信号
- **[`SakanaAI/AI-Scientist`](https://github.com/SakanaAI/AI-Scientist) & [OpenReview Review Rubric](https://openreview.net)**  
  *引用说明*：参考了自动化论文审阅中的多维量化评分量表（Rubric）与置信度校准设计，构建了本项目的 **4D OpenReview Rubric（创新增量 Delta / 实验严谨度 Rigor / 可迁移性 Actionability / 复现友好度 Reproducibility）** 及综合重排机制。
- **[Hugging Face Daily Papers API (`huggingface/hub-docs`)](https://huggingface.co/papers) & [Papers with Code](https://paperswithcode.com)**  
  *引用说明*：接入了 Hugging Face 每日论文公开接口以获取社区实时热度（`hf_upvotes`），并结合正文代码链接提取实现新发表预印本的冷启动信号加成。

### 3. MP3 语音合成与双人学术播客生成
- **[`teng-lin/notebooklm-py`](https://github.com/teng-lin/notebooklm-py)**  
  *引用说明*：官方 Google Gemini Notebook / NotebookLM 非官方 Python API 与代理技能，为本项目提供了按 Topic 标签自动投喂专属长效笔记本、自动分卷（Vol.N）以及生成 Google 原生高保真双人对谈 Audio Overview 播客的核心桥梁。
- **[`rany2/edge-tts`](https://github.com/rany2/edge-tts)**  
  *引用说明*：直接集成为默认的免配置神经网络语音合成底座，调用微软 Edge Neural TTS 接口生成中文多角色对谈与早报音频。
- **[`souzatharsis/podcastfy`](https://github.com/souzatharsis/podcastfy)**  
  *引用说明*：参考了其将技术文档转化为 NotebookLM 风格双人对谈播客（Host + Expert 交替拆解）的文稿编排架构与多 TTS 后端路由设计。
- **[`Azzedde/paper_to_podcast`](https://github.com/Azzedde/paper_to_podcast)**  
  *引用说明*：借鉴了针对学术论文的「主持人痛点追问 + 学者方法/实验拆解」双角色提示词工程，以及 TTS 合成前的 LaTeX 公式与链接脱敏清洗流程。
- **[`travisvn/openai-edge-tts`](https://github.com/travisvn/openai-edge-tts)**  
  *引用说明*：参考了其兼容 OpenAI `/v1/audio/speech` 标准接口的音色映射与请求封装方案，使本项目无缝支持 OpenAI 官方 TTS 与自建兼容语音服务。

### 4. 微信公众号排版、封面生成与草稿箱发布
- **[`wechatpy/wechatpy`](https://github.com/wechatpy/wechatpy)**  
  *引用说明*：集成为微信公众号 API 客户端底座，用于 Access Token 管理、永久封面素材上传、60 秒语音素材（`type=voice`）上传及草稿箱创建（`/cgi-bin/draft/add`）。
- **[`doocs/md`](https://github.com/doocs/md) & [`caol64/wenyan`](https://github.com/caol64/wenyan)**  
  *引用说明*：借鉴了微信公众号学术风内联 CSS 样式表（Inline Styles）渲染以及将外部超链接自动转化为文末编号角标（`[1]`, `[2]`）的排版方案。

### 5. 全网外部情报与有序降级链 (External Reach & Fallback Chains)
- **[`Panniantong/Agent-Reach`](https://github.com/Panniantong/Agent-Reach)**  
  *引用说明*：参考了其「以有序降级链（Ordered Backends）处理复杂异构互联网」的架构哲学与统一 CLI JSON 通信契约，为本项目重构了基于 DAG 的 6 阶段文献流水线（`pipeline/`），并在 Enrich 阶段作为免安装/只读外部组件接入，按论文标题自动拓展 B 站/YouTube 学术解说视频与 X/Reddit 社区热议，同时作为通用正文抓取的坚固兜底。
- **[`LucianaiB2004/wechat-publisher`](https://github.com/LucianaiB2004/wechat-publisher)**  
  *引用说明*：参考了其面向微信公众号的多模式推文构建（每日精选合集、单篇深度解读、专题综述）与自动化封面图生成流程。

---

## 五、 许可证 (License)

本项目遵循 **AGPLv3** 许可证开源。基于 [Zixuan Huang (@link231rog) / feisu-paper-daily](https://github.com/link231rog/feisu-paper-daily) 持续演进构建。
