import type { Locale } from './types';

export const zh: Locale = {
  sections: {
    hero: '概览',
    console: '控制台与规则定义',
    recommend: '文献推荐系统',
    digestTracking: '深度精读与问题追踪',
    multimedia: '多媒体衍生呈现',
    library: '文献库与 Agent 直连',
    delivery: '日报推送',
    deploy: '接入触发与部署',
  },
  header: {
    author: 'Zixuan Huang (@link231rog)',
    github: 'GitHub',
    toggleLang: 'EN',
    toggleTheme: '切换浅色/深色主题',
  },
  hero: {
    badge: 'Built by Zixuan Huang (@link231rog)',
    title: 'Paper Daily',
    subtitle: '自动化文献推荐、问题追踪与文献库沉淀',
    tags: [
      'GitHub Actions 免服运行',
      '多维度文献推荐',
      'Agent-Reach 全网声量',
      '双轨音频 (Edge-TTS / NotebookLM)',
      '问题追踪与精读',
      '文献库与 Agent 直连',
    ],
    btnDeploy: 'GitHub 部署',
    btnDocs: '架构文档',
  },
  console: {
    title: '控制台与规则定义',
    pills: ['飞书', 'Obsidian', 'Notion', '自定义 Skill', '范例模板'],
    cards: {
      lightweight: {
        title: '轻量化配置',
        desc: '直接在日常文档中维护关注标签、研究问题与过滤词，无需改代码。',
      },
      templates: {
        title: '自定义模板',
        desc: '支持导入个人审稿 Skill 与笔记模板，按习惯生成总结。',
      },
    },
  },
  recommend: {
    title: '文献推荐与全网情报',
    pills: ['arXiv', 'HuggingFace', 'OpenReview', 'Semantic Scholar', 'GitHub', 'Agent-Reach'],
    cards: {
      sources: {
        title: '多源文献检索',
        desc: '支持 arXiv、HuggingFace、OpenReview、Semantic Scholar 等主流学术源。',
      },
      agentReach: {
        title: 'Agent-Reach 全网声量',
        desc: '免安装组装 Agent-Reach 管道，探查 B站视频、YouTube 演讲与 Reddit 讨论。',
      },
      scoring: {
        title: '相关性打分',
        desc: '结合关注标签、文献库偏好与追踪问题进行关联打分。',
      },
      filtering: {
        title: '质量过滤',
        desc: '剔除低分论文，按评分分为「精读必看」与「速览雷达」。',
      },
    },
  },
  digestTracking: {
    title: '深度精读与问题追踪',
    cards: {
      methodFormula: {
        title: '方法与公式',
        desc: '一句话对齐基线指出核心变量，提炼模块链路与关键公式。',
      },
      experimentAudit: {
        title: '实验核查',
        desc: '核对正文图表，列出真实涨点、算力开销与失效边界。',
      },
      questionTracking: {
        title: '问题追踪',
        desc: '针对关注问题跨文献梳理支持证据、反例与研究盲区。',
      },
      subQuestions: {
        title: '子问题追问',
        desc: '当旧问题收敛或出现证据缺口时，自动生成后续追问。',
      },
    },
  },
  multimedia: {
    title: '多媒体衍生呈现',
    pills: ['NotebookLM', 'Edge-TTS', 'MP3 播客', '微信语音', 'PPTX', 'HTML5'],
    cards: {
      podcast: {
        title: '双轨学术播客',
        desc: '支持 Google NotebookLM 原生双人对谈与 Edge-TTS 语音，提炼核心增量与公式。',
      },
      briefing: {
        title: '60 秒语音简报',
        desc: '提炼单篇文献核心结论，自动生成短音频并写入微信语音素材库。',
      },
      pptx: {
        title: 'PPT 演示文稿',
        desc: '提取方法流程与实验图表，自动输出可编辑的学术汇报幻灯片。',
      },
      videoPoster: {
        title: '架构全景图与海报',
        desc: '支持 GPT-Image 机制全景图生成与 Paper2Poster 学术海报，免除冗长摘抄。',
      },
    },
  },
  library: {
    title: '文献库与 Agent 直连',
    pills: ['飞书', 'Obsidian', 'Notion', 'Zotero'],
    cards: {
      nativeLibrary: {
        title: '原生文献库',
        desc: '直接基于所选平台（飞书、Obsidian、Notion 或 Zotero）构建个人文献库。',
      },
      ingestionNotes: {
        title: '入库与批注',
        desc: '勾选论文沉淀入库，自动抓取正文生成精读笔记并进行细节批注。',
      },
      agentBridge: {
        title: 'Agent 直连与主动检索',
        desc: 'paper-library CLI 支持本地 Coding Agent 在线查找前沿文献、MMR 算法重排并一键免候选直接入库。',
      },
    },
  },
  delivery: {
    title: '日报推送',
    pills: ['飞书', 'Email', '微信公众号', 'Telegram'],
    cards: {
      feishu: {
        title: '飞书',
        desc: '生成飞书云文档日报与阅读待办。',
      },
      email: {
        title: '邮件',
        desc: 'SMTP 推送 HTML 日报。',
      },
      wechat: {
        title: '微信公众号',
        desc: '自动排版并写入草稿箱。',
      },
      telegram: {
        title: 'Telegram',
        desc: 'Bot 实时推送摘要与评分。',
      },
    },
  },
  deploy: {
    title: '接入触发与部署',
    pills: ['GitHub Actions', 'OpenClaw', 'Hermes', 'Grok Bot', 'Webhook'],
    cards: {
      githubActions: {
        title: 'GitHub Actions',
        desc: 'Fork 仓库填好密钥即可定时运行，无需服务器。',
      },
      agentRetrieval: {
        title: 'Agent 检索',
        desc: '支持 OpenClaw、Hermes 等通过 CLI 或 Tool 协议直接调用。',
      },
      webhook: {
        title: 'Webhook 触发',
        desc: '单条请求触发运行，动态传入临时问题与过滤规则。',
      },
    },
    steps: {
      fork: {
        title: '下载 / 引入 SKILL.md',
        desc: '只需单个 Skill 文件，本地零安装依赖与代码',
      },
      wizard: {
        title: 'Agent 自动远程 Fork',
        desc: '免 clone 自动将仓库远程 Fork 到个人 GitHub',
      },
      generate: {
        title: '写入云端密钥并触发',
        desc: '自动配置 Actions Secrets 并在云端定时免费调度',
      },
    },
    terminal: {
      initDesc: '交互式多选引导与渠道密钥初始化',
      searchDesc: 'Agent 直连检索文献库与个人批注',
      copied: '已复制',
      copy: '复制',
    },
  },
  footer: {
    author: 'Zixuan Huang (@link231rog)',
    repo: 'github.com/link231rog/feisu-paper-daily',
  },
};
