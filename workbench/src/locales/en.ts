import type { Locale } from './types';

export const en: Locale = {
  sections: {
    hero: 'Overview',
    console: 'Console & Rules',
    recommend: 'Recommendation',
    digestTracking: 'Digest & Tracking',
    multimedia: 'Multimedia',
    library: 'Library & Agent Bridge',
    delivery: 'Daily Delivery',
    deploy: 'Deployment & Triggers',
  },
  header: {
    author: 'Zixuan Huang (@link231rog)',
    github: 'GitHub',
    toggleLang: '中',
    toggleTheme: 'Toggle light/dark theme',
  },
  hero: {
    badge: 'Built by Zixuan Huang (@link231rog)',
    title: 'Paper Daily',
    subtitle: 'Automated Paper Discovery, Question Tracking & Library Archiving',
    tags: [
      'Local Engine (LaunchAgent)',
      'n8n Workflow Support',
      'Serverless via GitHub Actions',
      'Multi-Dimensional Reranking',
      'Agent-Reach Web Reach',
      'Dual-Track Audio (Edge-TTS / NotebookLM)',
      'Hypothesis & Question Tracking',
      'Direct Agent Bridge',
    ],
    btnDeploy: 'Deploy on GitHub',
    btnDocs: 'Architecture Docs',
  },
  console: {
    title: 'Console & Custom Rules',
    pills: ['Feishu / Lark', 'Obsidian', 'Notion', 'Custom Skills', 'Exemplar Templates'],
    cards: {
      lightweight: {
        title: 'Declarative Config',
        desc: 'Manage tracking tags, research questions, and exclusion rules directly in your daily markdown doc.',
      },
      templates: {
        title: 'Custom Templates',
        desc: 'Plug in personalized review skills and structured note exemplars matching your research workflow.',
      },
    },
  },
  recommend: {
    title: 'Paper Recommendation & Web Reach',
    pills: ['arXiv', 'HuggingFace', 'OpenReview', 'Semantic Scholar', 'GitHub', 'Agent-Reach'],
    cards: {
      sources: {
        title: 'Multi-Source Retrieval',
        desc: 'Ingests candidate preprints from arXiv, HuggingFace, OpenReview, and Semantic Scholar.',
      },
      agentReach: {
        title: 'Agent-Reach Intelligence',
        desc: 'Zero-install assembly with Agent-Reach to extract Bilibili talks, YouTube talks, and Reddit discussions.',
      },
      scoring: {
        title: 'Relevance Scoring',
        desc: 'Scores candidates via TF-IDF / embeddings against your personal library and tracked research hypotheses.',
      },
      filtering: {
        title: 'Tiered Curation',
        desc: 'Filters low-quality noise and segments selected papers into Must-Read deep digests and Quick-Radar briefs.',
      },
    },
  },
  digestTracking: {
    title: 'Critical Digest & Hypothesis Tracking',
    cards: {
      methodFormula: {
        title: 'Mechanism & Formulation',
        desc: 'Pinpoints core delta over baselines in one sentence, extracting pipeline mechanics and key LaTeX formulas.',
      },
      experimentAudit: {
        title: 'Evidence & Cost Audit',
        desc: 'Audits main tables and limitations for true metric gains, computational overhead, and failure boundaries.',
      },
      questionTracking: {
        title: 'Hypothesis Tracking',
        desc: 'Tracks empirical support, counter-evidence, and knowledge gaps across literature over time.',
      },
      subQuestions: {
        title: 'Follow-up Questions',
        desc: 'Automatically derives next-step inquiries when existing hypotheses converge or evidence gaps emerge.',
      },
    },
  },
  multimedia: {
    title: 'Multimedia Presentations',
    pills: ['AI Architecture Posters', 'NotebookLM Podcast', 'Edge-TTS', 'WeChat Audio', 'PPTX Slides'],
    cards: {
      poster: {
        title: 'Architecture Posters (Poster Engine)',
        desc: 'Generates 16:9 publication-grade vector schematics via gpt-image, natively mounted into reading notes and wiki gallery.',
      },
      podcast: {
        title: 'Dual-Track Academic Podcasts',
        desc: 'Generates Google NotebookLM official dual-host dialogues or Edge-TTS audio overviews.',
      },
      briefing: {
        title: '60-Second Audio Briefing',
        desc: 'Condenses single-paper breakthroughs into concise voice memos synced to WeChat voice material library.',
      },
      pptx: {
        title: 'Presentation Slides (PPTX)',
        desc: 'Extracts architecture flowcharts and benchmark tables into editable academic slide decks.',
      },
    },
  },
  library: {
    title: 'Literature Library & Agent Bridge',
    pills: ['Feishu / Lark', 'Obsidian', 'Notion', 'Zotero'],
    cards: {
      nativeLibrary: {
        title: 'Native Knowledge Bases',
        desc: 'Operates directly on your preferred platform (Feishu/Lark, Obsidian, Notion, or Zotero) with zero vendor lock-in.',
      },
      ingestionNotes: {
        title: 'Ingestion & Annotation',
        desc: 'Select candidate papers to generate structured deep-reading notes with paragraph-level highlights and reflections.',
      },
      agentBridge: {
        title: 'Direct Agent Bridge & Active Search',
        desc: 'paper-library CLI allows local Coding Agents to search literature online, rerank with MMR, and directly ingest notes without checklists.',
      },
    },
  },
  delivery: {
    title: 'Daily Digest Delivery',
    pills: ['Feishu / Lark', 'Email', 'WeChat Official Account', 'Telegram'],
    cards: {
      feishu: {
        title: 'Feishu / Lark',
        desc: 'Publishes cloud doc daily digests and reading tasks.',
      },
      email: {
        title: 'Email (SMTP)',
        desc: 'Delivers clean responsive HTML daily reports.',
      },
      wechat: {
        title: 'WeChat Official Account',
        desc: 'Auto-formats academic articles and uploads to draft box.',
      },
      telegram: {
        title: 'Telegram Bot',
        desc: 'Pushes real-time message digests and 4D rubric scores.',
      },
    },
  },
  deploy: {
    title: 'Deployment & Trigger Integrations',
    pills: ['GitHub Actions', 'macOS LaunchAgent', 'n8n Workflow', 'Local CPA (Gemini)', 'Webhook'],
    cards: {
      cloud: {
        title: 'Cloud Deployment (GitHub Actions)',
        desc: 'Fork the repo and configure secrets for scheduled runs on GitHub Actions with dynamic webhook triggers and zero server costs.',
      },
      local: {
        title: 'Local Execution (LaunchAgent & n8n)',
        desc: 'Native macOS launchd daemon with wake catchup and n8n workflow integration, directly connecting to local CPA (Gemini 3.8 Flash).',
      },
    },
    steps: {
      fork: {
        title: 'Import SKILL.md',
        desc: 'Single skill file with zero local code or dependencies',
      },
      wizard: {
        title: 'Agent Remote Fork',
        desc: 'Remotely forks repo to your personal GitHub account',
      },
      generate: {
        title: 'Configure Secrets & Run',
        desc: 'Injects Actions secrets and schedules 100% serverless',
      },
    },
    terminal: {
      initDesc: 'Interactive multi-select setup and credential configuration',
      searchDesc: 'Direct local execution / agent search',
      copied: 'Copied',
      copy: 'Copy',
    },
  },
  footer: {
    author: 'Zixuan Huang (@link231rog)',
    repo: 'github.com/link231rog/feisu-paper-daily',
  },
};
