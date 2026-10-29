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
      'Serverless via GitHub Actions',
      'Multi-Dimensional Reranking',
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
    title: 'Paper Recommendation System',
    pills: ['arXiv', 'HuggingFace', 'OpenReview', 'Semantic Scholar', 'GitHub', 'Agent-Reach'],
    cards: {
      sources: {
        title: 'Multi-Source & Community Reach',
        desc: 'Ingests from arXiv, HuggingFace, OpenReview, and enriches candidates via Agent-Reach community talks.',
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
    pills: ['NotebookLM', 'Edge-TTS', 'MP3 Podcast', 'WeChat Audio', 'PPTX', 'HTML5'],
    cards: {
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
      videoPoster: {
        title: 'Video & Interactive Posters',
        desc: 'Compiles paper assets into dynamic video narratives and lightweight interactive HTML5 exhibits.',
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
        title: 'Direct Agent Bridge',
        desc: 'Provides the paper-library CLI to query highlights, comments, and bilingual contexts directly into local AI agents.',
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
    pills: ['GitHub Actions', 'OpenClaw', 'Hermes', 'Grok Bot', 'Webhook'],
    cards: {
      githubActions: {
        title: 'GitHub Actions',
        desc: 'Fork the repo and configure repository secrets for scheduled runs with zero server costs.',
      },
      agentRetrieval: {
        title: 'Agent Retrieval',
        desc: 'Integrates with OpenClaw, Hermes, and custom AI agents via CLI or OpenAPI Tool schemas.',
      },
      webhook: {
        title: 'Webhook Dispatch',
        desc: 'Triggers on-demand runs via repository_dispatch with dynamic questions and exclusion overlays.',
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
      searchDesc: 'Direct agent search across personal highlights and reading notes',
      copied: 'Copied',
      copy: 'Copy',
    },
  },
  footer: {
    author: 'Zixuan Huang (@link231rog)',
    repo: 'github.com/link231rog/feisu-paper-daily',
  },
};
