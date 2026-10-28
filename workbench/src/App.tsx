import React, { useState, useEffect } from 'react';
import { motion, useScroll, useSpring } from 'motion/react';
import {
  Terminal,
  Webhook,
  Bot,
  Cpu,
  BookOpen,
  FileText,
  Mail,
  Send,
  Check,
  Copy,
  ArrowUpRight,
  Database,
  Search,
  Layers,
  ShieldCheck,
  Sparkles,
  GitPullRequest,
  Globe,
  Newspaper,
  Headphones,
  Volume2,
  Presentation,
  Sun,
  Moon,
} from 'lucide-react';

import { locales, type Language, type Theme } from './locales';

const README_URL = 'https://github.com/link231rog/feisu-paper-daily#readme';
const README_ARCH = 'https://github.com/link231rog/feisu-paper-daily#一-核心架构与目录组织';
const README_RERANK = 'https://github.com/link231rog/feisu-paper-daily#1-文献推荐与粗排重排算法';
const README_RUBRIC = 'https://github.com/link231rog/feisu-paper-daily#2-审稿级精读摘要与四维量化评分4d-openreview-rubric';
const README_AUDIO = 'https://github.com/link231rog/feisu-paper-daily#3-可选-mp3-音频播客与多渠道语音推送';
const README_WECHAT = 'https://github.com/link231rog/feisu-paper-daily#4-微信公众号排版封面生成与草稿箱发布';
const README_INIT = 'https://github.com/link231rog/feisu-paper-daily#2-交互式初始化向导';
const AUTHOR_HOMEPAGE_URL = 'https://link231rog.github.io/Poster/';

function BrandIcon({ name }: { name: string }) {
  switch (name) {
    case 'GitHub Actions':
    case 'GitHub':
      return (
        <svg viewBox="0 0 24 24" className="w-5 h-5 fill-current" aria-hidden="true">
          <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
        </svg>
      );
    case '飞书':
    case '飞书控制台':
    case 'Feishu':
    case 'Feishu / Lark':
      return (
        <svg viewBox="0 0 24 24" className="w-5 h-5 fill-current" aria-hidden="true">
          <path d="M3.5 5.5L11 2l9.5 6.5-5.5 4.5L3.5 5.5zm0 6.5l11.5 2.5-4.5 7.5L2 16.5 3.5 12zm12.2 2.2L22 10l-2.5 9.5-3.8-5.3z" />
        </svg>
      );
    case 'Obsidian':
      return (
        <svg viewBox="0 0 24 24" className="w-5 h-5 fill-current" aria-hidden="true">
          <path d="M12 1.5L5.5 7.2 3 15.8l6.8 6.7 8.2-2.3 3-9.2L12 1.5zm0 3.2l5.8 6.5-4.6 7.8-5.7-5.6L12 4.7z" />
        </svg>
      );
    case 'Notion':
      return (
        <svg viewBox="0 0 24 24" className="w-5 h-5 fill-current" aria-hidden="true">
          <path d="M4.5 3.5l11.8-.9c1.2-.1 1.8.3 2.5.9l2.7 2c.4.3.5.6.5 1.1v13.2c0 .9-.4 1.5-1.4 1.6l-13.2.8c-.9.1-1.4-.2-1.9-.8l-2.1-2.7c-.4-.5-.6-1-.6-1.7V4.9c0-.8.5-1.3 1.7-1.4zm2.6 3.7v11.2l2-.1V10l5.3 8.2 2.2-.1V6.8l-1.9.1v7.8L9.6 6.9l-2.5.3z" />
        </svg>
      );
    case 'Zotero':
      return (
        <svg viewBox="0 0 24 24" className="w-5 h-5 fill-current" aria-hidden="true">
          <path d="M4 3h16v3.2L9.2 18H20v3H4v-3.2L14.8 6H4V3z" />
        </svg>
      );
    case '微信公众号':
    case 'WeChat Official Account':
      return (
        <svg viewBox="0 0 24 24" className="w-5 h-5 fill-current" aria-hidden="true">
          <path d="M9.5 4C5.36 4 2 6.91 2 10.5c0 1.98 1.03 3.75 2.66 4.95L4 18l2.72-1.36c.88.23 1.81.36 2.78.36.34 0 .68-.02 1.01-.06-.2-.63-.31-1.3-.31-1.99 0-3.87 3.58-7 8-7 .34 0 .67.02 1 .06C18.36 5.69 14.34 4 9.5 4zm-2.75 4.25a1 1 0 110 2 1 1 0 010-2zm5.5 0a1 1 0 110 2 1 1 0 010-2zM16.5 10c-3.59 0-6.5 2.46-6.5 5.5S12.91 21 16.5 21c.78 0 1.53-.12 2.22-.34L21 22l-.55-2.15C21.99 18.84 23 17.28 23 15.5c0-3.04-2.91-5.5-6.5-5.5zm-2.25 3.5a.88.88 0 110 1.75.88.88 0 010-1.75zm4.5 0a.88.88 0 110 1.75.88.88 0 010-1.75z" />
        </svg>
      );
    case 'Telegram':
      return (
        <svg viewBox="0 0 24 24" className="w-5 h-5 fill-current" aria-hidden="true">
          <path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z" />
        </svg>
      );
    case 'Email':
      return <Mail className="w-5 h-5" />;
    case 'OpenClaw':
      return <Terminal className="w-5 h-5" />;
    case 'Hermes':
      return <Cpu className="w-5 h-5" />;
    case 'Grok Bot':
      return <Bot className="w-5 h-5" />;
    case 'Webhook':
      return <Webhook className="w-5 h-5" />;
    case '自定义 Skill':
    case 'Custom Skills':
      return <Sparkles className="w-5 h-5" />;
    case '范例模板':
    case 'Exemplar Templates':
      return <FileText className="w-5 h-5" />;
    case 'arXiv':
      return <BookOpen className="w-5 h-5" />;
    case 'HuggingFace':
      return <Sparkles className="w-5 h-5" />;
    case 'OpenReview':
      return <ShieldCheck className="w-5 h-5" />;
    case 'Semantic Scholar':
      return <Search className="w-5 h-5" />;
    case 'DBLP':
      return <Database className="w-5 h-5" />;
    case 'Crossref':
      return <Layers className="w-5 h-5" />;
    case 'bioRxiv':
    case 'medRxiv':
      return <FileText className="w-5 h-5" />;
    case 'AI News':
      return <Newspaper className="w-5 h-5" />;
    case 'Edge-TTS':
    case 'MP3 播客':
    case 'MP3 Podcast':
      return <Headphones className="w-5 h-5" />;
    case '微信语音':
    case 'WeChat Audio':
      return <Volume2 className="w-5 h-5" />;
    case 'PPTX':
      return <Presentation className="w-5 h-5" />;
    case 'HTML5':
      return <Globe className="w-5 h-5" />;
    default:
      return <Globe className="w-5 h-5" />;
  }
}

const PLATFORM_URLS: Record<string, string> = {
  // Sources
  arXiv: 'https://arxiv.org',
  HuggingFace: 'https://huggingface.co/papers',
  OpenReview: 'https://openreview.net',
  'Semantic Scholar': 'https://www.semanticscholar.org',
  GitHub: 'https://github.com',
  DBLP: 'https://dblp.org',
  Crossref: 'https://www.crossref.org',
  bioRxiv: 'https://www.biorxiv.org',
  medRxiv: 'https://www.medrxiv.org',
  'AI News': 'https://news.ycombinator.com',

  // Console & Libraries
  飞书: 'https://www.feishu.cn',
  飞书控制台: 'https://www.feishu.cn',
  'Feishu / Lark': 'https://www.feishu.cn',
  Obsidian: 'https://obsidian.md',
  Notion: 'https://www.notion.so',
  Zotero: 'https://www.zotero.org',
  '自定义 Skill': 'https://github.com/link231rog/feisu-paper-daily#readme',
  'Custom Skills': 'https://github.com/link231rog/feisu-paper-daily#readme',
  范例模板: 'https://github.com/link231rog/feisu-paper-daily#readme',
  'Exemplar Templates': 'https://github.com/link231rog/feisu-paper-daily#readme',

  // Multimedia
  'Edge-TTS': 'https://github.com/rany2/edge-tts',
  'MP3 播客': 'https://github.com/link231rog/feisu-paper-daily#3-可选-mp3-音频播客与多渠道语音推送',
  'MP3 Podcast': 'https://github.com/link231rog/feisu-paper-daily#3-可选-mp3-音频播客与多渠道语音推送',
  微信语音: 'https://mp.weixin.qq.com',
  'WeChat Audio': 'https://mp.weixin.qq.com',
  PPTX: 'https://github.com/link231rog/feisu-paper-daily#readme',
  HTML5: 'https://developer.mozilla.org/zh-CN/docs/Web/HTML',

  // Channels
  Email: 'https://github.com/link231rog/feisu-paper-daily#readme',
  微信公众号: 'https://mp.weixin.qq.com',
  'WeChat Official Account': 'https://mp.weixin.qq.com',
  Telegram: 'https://telegram.org',

  // Deploy
  'GitHub Actions': 'https://github.com/features/actions',
  OpenClaw: 'https://github.com/link231rog/feisu-paper-daily#readme',
  Hermes: 'https://github.com/link231rog/feisu-paper-daily#readme',
  'Grok Bot': 'https://x.ai',
  Webhook: 'https://github.com/link231rog/feisu-paper-daily#readme',
};

function PlatformPill({ name, href }: { name: string; href?: string }) {
  const targetUrl = href || PLATFORM_URLS[name];
  const content = (
    <>
      <BrandIcon name={name} />
      <span>{name}</span>
      <ArrowUpRight className="w-3.5 h-3.5 text-neutral-400 dark:text-neutral-500 group-hover:text-black dark:group-hover:text-white transition-colors" />
    </>
  );

  const className =
    "group inline-flex items-center gap-2 px-3 py-1.5 border border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-950 text-neutral-900 dark:text-white text-sm font-medium hover:border-neutral-400 dark:hover:border-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-900 transition-all cursor-pointer";

  if (targetUrl) {
    return (
      <motion.a
        href={targetUrl}
        target="_blank"
        rel="noreferrer"
        whileHover={{ y: -2 }}
        transition={{ duration: 0.16, ease: 'easeOut' }}
        className={className}
        aria-label={`Open ${name} official website`}
      >
        {content}
      </motion.a>
    );
  }

  return (
    <motion.div
      whileHover={{ y: -2 }}
      transition={{ duration: 0.16, ease: 'easeOut' }}
      className={className}
    >
      {content}
    </motion.div>
  );
}

function GridCard({
  title,
  desc,
  href,
  dimmed = false,
  className = '',
}: {
  title: string;
  desc: string;
  href?: string;
  dimmed?: boolean;
  className?: string;
}) {
  const content = (
    <>
      <span
        className={`pointer-events-none absolute top-0 left-0 h-px w-0 transition-all duration-300 ${
          dimmed
            ? 'bg-neutral-400 dark:bg-neutral-600 group-hover:w-full'
            : 'bg-black dark:bg-white group-hover:w-full'
        }`}
      />
      <div className="flex items-start justify-between gap-2">
        <h3
          className={`text-lg font-semibold ${
            dimmed ? 'text-neutral-400 dark:text-neutral-500' : 'text-neutral-900 dark:text-white'
          }`}
        >
          {title}
        </h3>
        {href && (
          <ArrowUpRight
            className={`w-4 h-4 shrink-0 transition-colors ${
              dimmed
                ? 'text-neutral-300 dark:text-neutral-700 group-hover:text-neutral-500'
                : 'text-neutral-400 dark:text-neutral-600 group-hover:text-black dark:group-hover:text-white'
            }`}
          />
        )}
      </div>
      <p
        className={`mt-2 text-base leading-relaxed ${
          dimmed ? 'text-neutral-400 dark:text-neutral-600' : 'text-neutral-600 dark:text-neutral-300'
        }`}
      >
        {desc}
      </p>
    </>
  );

  const containerClasses = `group relative p-6 border-r border-b border-neutral-200 dark:border-neutral-800 bg-white dark:bg-black hover:bg-neutral-50 dark:hover:bg-neutral-950 transition-colors duration-200 block text-left ${className}`;

  if (href) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        className={containerClasses}
        aria-label={`View ${title} documentation`}
      >
        {content}
      </a>
    );
  }

  return <div className={containerClasses}>{content}</div>;
}

const sectionReveal = {
  hidden: { opacity: 0, y: 18 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.45, ease: [0.22, 1, 0.36, 1] as const },
  },
};

export default function App() {
  const [theme, setTheme] = useState<Theme>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('paper-daily-theme');
      if (saved === 'light' || saved === 'dark') return saved;
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'dark';
    }
    return 'dark';
  });

  const [lang, setLang] = useState<Language>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('paper-daily-lang');
      if (saved === 'zh' || saved === 'en') return saved;
      const navLang = navigator.language.toLowerCase();
      if (navLang.startsWith('en')) return 'en';
    }
    return 'zh';
  });

  const [copiedCmd, setCopiedCmd] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string>('hero');

  const { scrollYProgress } = useScroll();
  const scaleX = useSpring(scrollYProgress, {
    stiffness: 120,
    damping: 30,
    restDelta: 0.001,
  });

  const t = locales[lang];

  const sections = [
    { id: 'hero', label: t.sections.hero },
    { id: 'console', label: t.sections.console },
    { id: 'recommend', label: t.sections.recommend },
    { id: 'digest-tracking', label: t.sections.digestTracking },
    { id: 'multimedia', label: t.sections.multimedia },
    { id: 'library', label: t.sections.library },
    { id: 'delivery', label: t.sections.delivery },
    { id: 'deploy', label: t.sections.deploy },
  ] as const;

  const initCommand = `uv run paper-daily init`;
  const cliCommand = `uv run paper-library search "memory gap"`;

  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'dark') {
      root.classList.add('dark');
    } else {
      root.classList.remove('dark');
    }
    localStorage.setItem('paper-daily-theme', theme);
  }, [theme]);

  useEffect(() => {
    localStorage.setItem('paper-daily-lang', lang);
  }, [lang]);

  useEffect(() => {
    const handleScroll = () => {
      const scrollPos = window.scrollY + 160;
      for (let i = sections.length - 1; i >= 0; i--) {
        const el = document.getElementById(sections[i].id);
        if (el && el.offsetTop <= scrollPos) {
          setActiveId(sections[i].id);
          break;
        }
      }
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    handleScroll();
    return () => window.removeEventListener('scroll', handleScroll);
  }, [sections]);

  const scrollToSection = (id: string) => {
    const el = document.getElementById(id);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  const handleCopy = (cmd: string, key: string) => {
    navigator.clipboard.writeText(cmd);
    setCopiedCmd(key);
    setTimeout(() => setCopiedCmd(null), 1800);
  };

  const toggleTheme = () => {
    setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'));
  };

  const toggleLanguage = () => {
    setLang((prev) => (prev === 'zh' ? 'en' : 'zh'));
  };

  return (
    <div className="min-h-screen bg-white dark:bg-black text-neutral-900 dark:text-white transition-colors duration-200 selection:bg-black selection:text-white dark:selection:bg-white dark:selection:text-black">
      {/* Top Progress Line */}
      <motion.div
        style={{ scaleX }}
        className="fixed top-0 left-0 right-0 h-0.5 bg-black dark:bg-white origin-left z-50"
      />

      {/* Top Bar */}
      <header className="border-b border-neutral-200 dark:border-neutral-800 bg-white/90 dark:bg-black/90 backdrop-blur sticky top-0 z-40 transition-colors">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              onClick={() => scrollToSection('hero')}
              className="flex items-center gap-3 cursor-pointer"
            >
              <div className="w-3 h-3 bg-black dark:bg-white transition-colors" />
              <span className="font-semibold tracking-tight text-lg text-neutral-900 dark:text-white">
                Paper Daily
              </span>
            </button>
            <span className="text-neutral-300 dark:text-neutral-700">/</span>
            <a
              href={AUTHOR_HOMEPAGE_URL}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 text-sm font-mono text-neutral-600 dark:text-neutral-300 hover:text-black dark:hover:text-white transition-colors"
            >
              <span>{t.header.author}</span>
            </a>
          </div>

          <nav className="flex items-center gap-3 md:gap-5">
            {/* Language Switch */}
            <button
              onClick={toggleLanguage}
              className="px-2.5 py-1 text-xs font-mono font-semibold border border-neutral-200 dark:border-neutral-800 bg-neutral-100 dark:bg-neutral-900 text-neutral-700 dark:text-neutral-300 hover:border-neutral-400 dark:hover:border-neutral-600 hover:text-black dark:hover:text-white transition-all cursor-pointer rounded-sm"
              aria-label={lang === 'zh' ? 'Switch to English' : '切换为中文'}
            >
              {lang === 'zh' ? 'EN' : '中文'}
            </button>

            {/* Theme Switch */}
            <button
              onClick={toggleTheme}
              className="p-1.5 border border-neutral-200 dark:border-neutral-800 bg-neutral-100 dark:bg-neutral-900 text-neutral-700 dark:text-neutral-300 hover:border-neutral-400 dark:hover:border-neutral-600 hover:text-black dark:hover:text-white transition-all cursor-pointer rounded-sm"
              aria-label={t.header.toggleTheme}
            >
              {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            </button>

            <a
              href="https://github.com/link231rog/feisu-paper-daily"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 text-sm font-medium text-neutral-700 dark:text-neutral-300 hover:text-black dark:hover:text-white transition-colors"
            >
              <BrandIcon name="GitHub" />
              <span className="hidden sm:inline">{t.header.github}</span>
              <ArrowUpRight className="w-4 h-4" />
            </a>
          </nav>
        </div>
      </header>

      {/* Main Layout with Sticky Side TOC */}
      <div className="max-w-7xl mx-auto px-6 lg:grid lg:grid-cols-[240px_1fr] lg:border-x lg:border-neutral-200 dark:lg:border-neutral-800 transition-colors">
        {/* Sticky Side TOC */}
        <aside className="hidden lg:block border-r border-neutral-200 dark:border-neutral-800 py-12 pr-6 transition-colors">
          <div className="sticky top-28">
            <nav className="flex flex-col gap-4 py-2">
              {sections.map(({ id, label }) => {
                const isActive = activeId === id;
                return (
                  <button
                    key={id}
                    onClick={() => scrollToSection(id)}
                    className="group flex items-center gap-3.5 text-left py-1 cursor-pointer focus:outline-none"
                    aria-label={`Jump to ${label}`}
                  >
                    <span
                      className={`h-[2px] transition-all duration-300 ease-out shrink-0 ${
                        isActive
                          ? 'w-14 bg-black dark:bg-white'
                          : 'w-6 bg-neutral-300 dark:bg-neutral-600 group-hover:w-9 group-hover:bg-neutral-500 dark:group-hover:bg-neutral-400'
                      }`}
                    />
                    <span
                      className={`transition-all duration-300 tracking-tight select-none ${
                        isActive
                          ? 'text-neutral-900 dark:text-white font-bold text-base'
                          : 'text-neutral-400 dark:text-neutral-500 font-medium text-sm group-hover:text-neutral-700 dark:group-hover:text-neutral-300'
                      }`}
                    >
                      {label}
                    </span>
                  </button>
                );
              })}
            </nav>

            {/* Author Identity Card in Sidebar */}
            <div className="mt-12 pt-6 border-t border-neutral-200 dark:border-neutral-800 transition-colors">
              <div className="text-xs font-mono text-neutral-400 dark:text-neutral-500 uppercase tracking-wider">
                {lang === 'zh' ? '作者' : 'Author'}
              </div>
              <a
                href={AUTHOR_HOMEPAGE_URL}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-flex items-center gap-1.5 text-sm font-semibold text-neutral-900 dark:text-white hover:underline"
              >
                <span>Zixuan Huang</span>
                <ArrowUpRight className="w-3.5 h-3.5" />
              </a>
              <div className="mt-0.5 text-xs font-mono text-neutral-400 dark:text-neutral-500">
                @link231rog
              </div>
            </div>
          </div>
        </aside>

        {/* Content Column */}
        <main className="divide-y divide-neutral-200 dark:divide-neutral-800 transition-colors">
          {/* 00 · Hero */}
          <motion.section
            id="hero"
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, amount: 0.2 }}
            variants={sectionReveal}
            className="py-20 md:py-24 lg:px-10 scroll-mt-16"
          >
            <a
              href={AUTHOR_HOMEPAGE_URL}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 px-3 py-1 border border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-950 text-sm font-mono text-neutral-700 dark:text-neutral-300 hover:text-black dark:hover:text-white hover:border-neutral-400 dark:hover:border-neutral-700 transition-colors mb-6 cursor-pointer"
            >
              <span>{t.hero.badge}</span>
              <ArrowUpRight className="w-3.5 h-3.5 text-neutral-400 dark:text-neutral-500" />
            </a>

            <h1 className="text-5xl md:text-7xl font-bold tracking-tight text-neutral-900 dark:text-white">
              {t.hero.title}
            </h1>
            <p className="mt-5 text-xl md:text-2xl text-neutral-600 dark:text-neutral-300 font-normal">
              {t.hero.subtitle}
            </p>

            <div className="mt-8 flex flex-wrap gap-2.5">
              {t.hero.tags.map((tag) => (
                <span
                  key={tag}
                  className="px-3.5 py-1.5 border border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-950 text-neutral-800 dark:text-neutral-200 text-sm font-mono"
                >
                  {tag}
                </span>
              ))}
            </div>

            <div className="mt-10 flex flex-wrap gap-4">
              <a
                href="https://github.com/link231rog/feisu-paper-daily/fork"
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-2 px-6 py-3 bg-black dark:bg-white text-white dark:text-black font-semibold text-base hover:bg-neutral-800 dark:hover:bg-neutral-200 transition-colors"
              >
                <span>{t.hero.btnDeploy}</span>
                <ArrowUpRight className="w-4 h-4" />
              </a>
              <a
                href="https://github.com/link231rog/feisu-paper-daily#readme"
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-2 px-6 py-3 border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-black text-neutral-900 dark:text-white font-semibold text-base hover:border-black dark:hover:border-white transition-colors"
              >
                <span>{t.hero.btnDocs}</span>
              </a>
            </div>
          </motion.section>

          {/* 01 · Console & Custom Rules */}
          <motion.section
            id="console"
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, amount: 0.2 }}
            variants={sectionReveal}
            className="py-16 lg:px-10 scroll-mt-16"
          >
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
              <h2 className="text-2xl md:text-3xl font-bold tracking-tight text-neutral-900 dark:text-white">
                {t.console.title}
              </h2>
              <div className="flex flex-wrap gap-2">
                {t.console.pills.map((item) => (
                  <PlatformPill key={item} name={item} />
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 border-t border-l border-neutral-200 dark:border-neutral-800">
              <GridCard
                title={t.console.cards.lightweight.title}
                desc={t.console.cards.lightweight.desc}
                href={README_URL}
              />
              <GridCard
                title={t.console.cards.templates.title}
                desc={t.console.cards.templates.desc}
                href={README_URL}
              />
            </div>
          </motion.section>

          {/* 02 · Recommendation System */}
          <motion.section
            id="recommend"
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, amount: 0.2 }}
            variants={sectionReveal}
            className="py-16 lg:px-10 scroll-mt-16"
          >
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
              <h2 className="text-2xl md:text-3xl font-bold tracking-tight text-neutral-900 dark:text-white">
                {t.recommend.title}
              </h2>
              <div className="flex flex-wrap gap-2">
                {t.recommend.pills.map((item) => (
                  <PlatformPill key={item} name={item} />
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 border-t border-l border-neutral-200 dark:border-neutral-800">
              <GridCard
                title={t.recommend.cards.sources.title}
                desc={t.recommend.cards.sources.desc}
                href={README_ARCH}
              />
              <GridCard
                title={t.recommend.cards.scoring.title}
                desc={t.recommend.cards.scoring.desc}
                href={README_RERANK}
              />
              <GridCard
                title={t.recommend.cards.filtering.title}
                desc={t.recommend.cards.filtering.desc}
                href={README_RUBRIC}
              />
            </div>
          </motion.section>

          {/* 03 · Critical Digest & Hypothesis Tracking */}
          <motion.section
            id="digest-tracking"
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, amount: 0.2 }}
            variants={sectionReveal}
            className="py-16 lg:px-10 scroll-mt-16"
          >
            <h2 className="text-2xl md:text-3xl font-bold tracking-tight text-neutral-900 dark:text-white mb-8">
              {t.digestTracking.title}
            </h2>

            <div className="grid grid-cols-1 md:grid-cols-2 border-t border-l border-neutral-200 dark:border-neutral-800">
              <GridCard
                title={t.digestTracking.cards.methodFormula.title}
                desc={t.digestTracking.cards.methodFormula.desc}
                href={README_RUBRIC}
              />
              <GridCard
                title={t.digestTracking.cards.experimentAudit.title}
                desc={t.digestTracking.cards.experimentAudit.desc}
                href={README_RUBRIC}
              />
              <GridCard
                title={t.digestTracking.cards.questionTracking.title}
                desc={t.digestTracking.cards.questionTracking.desc}
                href={README_ARCH}
              />
              <GridCard
                title={t.digestTracking.cards.subQuestions.title}
                desc={t.digestTracking.cards.subQuestions.desc}
                href={README_ARCH}
              />
            </div>
          </motion.section>

          {/* 04 · Multimedia Presentations */}
          <motion.section
            id="multimedia"
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, amount: 0.2 }}
            variants={sectionReveal}
            className="py-16 lg:px-10 scroll-mt-16"
          >
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
              <h2 className="text-2xl md:text-3xl font-bold tracking-tight text-neutral-900 dark:text-white">
                {t.multimedia.title}
              </h2>
              <div className="flex flex-wrap gap-2">
                {t.multimedia.pills.map((item) => (
                  <PlatformPill key={item} name={item} />
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 border-t border-l border-neutral-200 dark:border-neutral-800">
              <GridCard
                title={t.multimedia.cards.podcast.title}
                desc={t.multimedia.cards.podcast.desc}
                href={README_AUDIO}
              />
              <GridCard
                title={t.multimedia.cards.briefing.title}
                desc={t.multimedia.cards.briefing.desc}
                href={README_AUDIO}
              />
              <GridCard
                dimmed
                title={t.multimedia.cards.pptx.title}
                desc={t.multimedia.cards.pptx.desc}
                href={README_URL}
              />
              <GridCard
                dimmed
                title={t.multimedia.cards.videoPoster.title}
                desc={t.multimedia.cards.videoPoster.desc}
                href={README_URL}
              />
            </div>
          </motion.section>

          {/* 05 · Library & Agent Bridge */}
          <motion.section
            id="library"
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, amount: 0.2 }}
            variants={sectionReveal}
            className="py-16 lg:px-10 scroll-mt-16"
          >
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
              <h2 className="text-2xl md:text-3xl font-bold tracking-tight text-neutral-900 dark:text-white">
                {t.library.title}
              </h2>
              <div className="flex flex-wrap gap-2">
                {t.library.pills.map((item) => (
                  <PlatformPill key={item} name={item} />
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 border-t border-l border-neutral-200 dark:border-neutral-800">
              <GridCard
                title={t.library.cards.nativeLibrary.title}
                desc={t.library.cards.nativeLibrary.desc}
                href={README_URL}
              />
              <GridCard
                title={t.library.cards.ingestionNotes.title}
                desc={t.library.cards.ingestionNotes.desc}
                href={README_URL}
              />
              <GridCard
                title={t.library.cards.agentBridge.title}
                desc={t.library.cards.agentBridge.desc}
                href={README_URL}
              />
            </div>
          </motion.section>

          {/* 06 · Daily Delivery */}
          <motion.section
            id="delivery"
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, amount: 0.2 }}
            variants={sectionReveal}
            className="py-16 lg:px-10 scroll-mt-16"
          >
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
              <h2 className="text-2xl md:text-3xl font-bold tracking-tight text-neutral-900 dark:text-white">
                {t.delivery.title}
              </h2>
              <div className="flex flex-wrap gap-2">
                {t.delivery.pills.map((item) => (
                  <PlatformPill key={item} name={item} />
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 border-t border-l border-neutral-200 dark:border-neutral-800">
              <GridCard
                title={t.delivery.cards.feishu.title}
                desc={t.delivery.cards.feishu.desc}
                href={README_ARCH}
              />
              <GridCard
                title={t.delivery.cards.email.title}
                desc={t.delivery.cards.email.desc}
                href={README_ARCH}
              />
              <GridCard
                title={t.delivery.cards.wechat.title}
                desc={t.delivery.cards.wechat.desc}
                href={README_WECHAT}
              />
              <GridCard
                title={t.delivery.cards.telegram.title}
                desc={t.delivery.cards.telegram.desc}
                href={README_AUDIO}
              />
            </div>
          </motion.section>

          {/* 07 · Deployment & Triggers */}
          <motion.section
            id="deploy"
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, amount: 0.2 }}
            variants={sectionReveal}
            className="py-16 lg:px-10 scroll-mt-16"
          >
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
              <h2 className="text-2xl md:text-3xl font-bold tracking-tight text-neutral-900 dark:text-white">
                {t.deploy.title}
              </h2>
              <div className="flex flex-wrap gap-2">
                {t.deploy.pills.map((item) => (
                  <PlatformPill key={item} name={item} />
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 border-t border-l border-neutral-200 dark:border-neutral-800 mb-8">
              <GridCard
                title={t.deploy.cards.githubActions.title}
                desc={t.deploy.cards.githubActions.desc}
                href={README_URL}
              />
              <GridCard
                title={t.deploy.cards.agentRetrieval.title}
                desc={t.deploy.cards.agentRetrieval.desc}
                href={README_URL}
              />
              <GridCard
                title={t.deploy.cards.webhook.title}
                desc={t.deploy.cards.webhook.desc}
                href={README_URL}
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 border-t border-l border-neutral-200 dark:border-neutral-800 mb-8">
              <a
                href="https://github.com/link231rog/feisu-paper-daily/fork"
                target="_blank"
                rel="noreferrer"
                className="group p-6 border-r border-b border-neutral-200 dark:border-neutral-800 flex items-center justify-between gap-3 bg-white dark:bg-black hover:bg-neutral-50 dark:hover:bg-neutral-950 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <GitPullRequest className="w-5 h-5 text-neutral-900 dark:text-white shrink-0" />
                  <div>
                    <div className="text-lg font-semibold text-neutral-900 dark:text-white">
                      {t.deploy.steps.fork.title}
                    </div>
                    <div className="text-sm text-neutral-500 dark:text-neutral-400 mt-1">
                      {t.deploy.steps.fork.desc}
                    </div>
                  </div>
                </div>
                <ArrowUpRight className="w-4 h-4 text-neutral-400 dark:text-neutral-600 group-hover:text-black dark:group-hover:text-white transition-colors shrink-0" />
              </a>
              <a
                href={README_INIT}
                target="_blank"
                rel="noreferrer"
                className="group p-6 border-r border-b border-neutral-200 dark:border-neutral-800 flex items-center justify-between gap-3 bg-white dark:bg-black hover:bg-neutral-50 dark:hover:bg-neutral-950 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <ShieldCheck className="w-5 h-5 text-neutral-900 dark:text-white shrink-0" />
                  <div>
                    <div className="text-lg font-semibold text-neutral-900 dark:text-white">
                      {t.deploy.steps.wizard.title}
                    </div>
                    <div className="text-sm text-neutral-500 dark:text-neutral-400 mt-1">
                      {t.deploy.steps.wizard.desc}
                    </div>
                  </div>
                </div>
                <ArrowUpRight className="w-4 h-4 text-neutral-400 dark:text-neutral-600 group-hover:text-black dark:group-hover:text-white transition-colors shrink-0" />
              </a>
              <a
                href={README_INIT}
                target="_blank"
                rel="noreferrer"
                className="group p-6 border-r border-b border-neutral-200 dark:border-neutral-800 flex items-center justify-between gap-3 bg-white dark:bg-black hover:bg-neutral-50 dark:hover:bg-neutral-950 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <Send className="w-5 h-5 text-neutral-900 dark:text-white shrink-0" />
                  <div>
                    <div className="text-lg font-semibold text-neutral-900 dark:text-white">
                      {t.deploy.steps.generate.title}
                    </div>
                    <div className="text-sm text-neutral-500 dark:text-neutral-400 mt-1">
                      {t.deploy.steps.generate.desc}
                    </div>
                  </div>
                </div>
                <ArrowUpRight className="w-4 h-4 text-neutral-400 dark:text-neutral-600 group-hover:text-black dark:group-hover:text-white transition-colors shrink-0" />
              </a>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 border-t border-l border-neutral-200 dark:border-neutral-800">
              <div className="border-r border-b border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-950 p-5 flex items-center justify-between gap-4 transition-colors">
                <div className="min-w-0">
                  <div className="text-xs text-neutral-500 dark:text-neutral-400 mb-1">
                    {t.deploy.terminal.initDesc}
                  </div>
                  <code className="text-base font-mono text-neutral-900 dark:text-white block overflow-x-auto">
                    $ {initCommand}
                  </code>
                </div>
                <button
                  onClick={() => handleCopy(initCommand, 'init')}
                  className="inline-flex items-center gap-2 px-4 py-2 border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-black text-neutral-900 dark:text-white text-sm font-medium hover:border-black dark:hover:border-white transition-colors shrink-0 cursor-pointer"
                >
                  {copiedCmd === 'init' ? (
                    <Check className="w-4 h-4 text-emerald-500" />
                  ) : (
                    <Copy className="w-4 h-4" />
                  )}
                  <span>
                    {copiedCmd === 'init' ? t.deploy.terminal.copied : t.deploy.terminal.copy}
                  </span>
                </button>
              </div>

              <div className="border-r border-b border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-950 p-5 flex items-center justify-between gap-4 transition-colors">
                <div className="min-w-0">
                  <div className="text-xs text-neutral-500 dark:text-neutral-400 mb-1">
                    {t.deploy.terminal.searchDesc}
                  </div>
                  <code className="text-base font-mono text-neutral-900 dark:text-white block overflow-x-auto">
                    $ {cliCommand}
                  </code>
                </div>
                <button
                  onClick={() => handleCopy(cliCommand, 'search')}
                  className="inline-flex items-center gap-2 px-4 py-2 border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-black text-neutral-900 dark:text-white text-sm font-medium hover:border-black dark:hover:border-white transition-colors shrink-0 cursor-pointer"
                >
                  {copiedCmd === 'search' ? (
                    <Check className="w-4 h-4 text-emerald-500" />
                  ) : (
                    <Copy className="w-4 h-4" />
                  )}
                  <span>
                    {copiedCmd === 'search' ? t.deploy.terminal.copied : t.deploy.terminal.copy}
                  </span>
                </button>
              </div>
            </div>
          </motion.section>

          {/* Author Footer */}
          <footer className="py-10 lg:px-10 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="w-2.5 h-2.5 bg-black dark:bg-white transition-colors" />
              <span className="text-base font-semibold text-neutral-900 dark:text-white">
                Paper Daily
              </span>
              <span className="text-neutral-300 dark:text-neutral-700">·</span>
              <a
                href={AUTHOR_HOMEPAGE_URL}
                target="_blank"
                rel="noreferrer"
                className="text-base text-neutral-600 dark:text-neutral-300 hover:text-black dark:hover:text-white transition-colors"
              >
                {t.footer.author}
              </a>
            </div>
            <div className="flex items-center gap-6">
              <a
                href="https://github.com/link231rog/feisu-paper-daily"
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 text-sm font-mono text-neutral-600 dark:text-neutral-300 hover:text-black dark:hover:text-white transition-colors"
              >
                <span>{t.footer.repo}</span>
                <ArrowUpRight className="w-4 h-4" />
              </a>
            </div>
          </footer>
        </main>
      </div>
    </div>
  );
}
