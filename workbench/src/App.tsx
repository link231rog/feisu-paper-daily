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
} from 'lucide-react';

const SECTIONS = [
  { id: 'hero', label: '概览' },
  { id: 'console', label: '控制台与规则定义' },
  { id: 'recommend', label: '文献推荐系统' },
  { id: 'digest-tracking', label: '深度精读与问题追踪' },
  { id: 'library', label: '文献库与 Agent 直连' },
  { id: 'delivery', label: '日报推送' },
  { id: 'deploy', label: '接入触发与部署' },
] as const;

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
      return <Sparkles className="w-5 h-5" />;
    case '范例模板':
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
    default:
      return <Globe className="w-5 h-5" />;
  }
}

function PlatformPill({ name }: { name: string }) {
  return (
    <motion.div
      whileHover={{ y: -2, borderColor: '#ffffff' }}
      transition={{ duration: 0.16, ease: 'easeOut' }}
      className="inline-flex items-center gap-2.5 px-3.5 py-2 border border-neutral-800 bg-neutral-950 text-white text-sm font-medium transition-colors"
    >
      <BrandIcon name={name} />
      <span>{name}</span>
    </motion.div>
  );
}

function GridCard({
  title,
  desc,
  className = '',
}: {
  title: string;
  desc: string;
  className?: string;
}) {
  return (
    <div
      className={`group relative p-6 border-r border-b border-neutral-800 bg-black hover:bg-neutral-950 transition-colors duration-200 ${className}`}
    >
      <span className="pointer-events-none absolute top-0 left-0 h-px w-0 bg-white transition-all duration-300 group-hover:w-full" />
      <h3 className="text-lg font-semibold text-white">{title}</h3>
      <p className="mt-2 text-base text-neutral-300">{desc}</p>
    </div>
  );
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
  const [copiedCmd, setCopiedCmd] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string>('hero');

  const { scrollYProgress } = useScroll();
  const scaleX = useSpring(scrollYProgress, {
    stiffness: 120,
    damping: 30,
    restDelta: 0.001,
  });

  const initCommand = `uv run paper-daily init`;
  const cliCommand = `uv run paper-library search "memory gap"`;

  useEffect(() => {
    const handleScroll = () => {
      const scrollPos = window.scrollY + 160;
      for (let i = SECTIONS.length - 1; i >= 0; i--) {
        const el = document.getElementById(SECTIONS[i].id);
        if (el && el.offsetTop <= scrollPos) {
          setActiveId(SECTIONS[i].id);
          break;
        }
      }
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    handleScroll();
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

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

  return (
    <div className="min-h-screen bg-black text-white selection:bg-white selection:text-black">
      {/* Top Progress Line */}
      <motion.div
        style={{ scaleX }}
        className="fixed top-0 left-0 right-0 h-0.5 bg-white origin-left z-50"
      />

      {/* Top Bar */}
      <header className="border-b border-neutral-800 bg-black/90 backdrop-blur sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              onClick={() => scrollToSection('hero')}
              className="flex items-center gap-3 cursor-pointer"
            >
              <div className="w-3 h-3 bg-white" />
              <span className="font-semibold tracking-tight text-lg">Paper Daily</span>
            </button>
            <span className="text-neutral-700">/</span>
            <a
              href="https://github.com/link231rog"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 text-sm font-mono text-neutral-300 hover:text-white transition-colors"
            >
              <span>Zixuan Huang (@link231rog)</span>
            </a>
          </div>

          <nav className="flex items-center gap-6">
            <a
              href="https://github.com/link231rog/feisu-paper-daily"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 text-sm font-medium text-neutral-300 hover:text-white transition-colors"
            >
              <BrandIcon name="GitHub" />
              <span>GitHub</span>
              <ArrowUpRight className="w-4 h-4" />
            </a>
          </nav>
        </div>
      </header>

      {/* Main Layout with Sticky Side TOC */}
      <div className="max-w-7xl mx-auto px-6 lg:grid lg:grid-cols-[240px_1fr] lg:border-x lg:border-neutral-800">
        {/* Sticky Side TOC */}
        <aside className="hidden lg:block border-r border-neutral-800 py-12 pr-6">
          <div className="sticky top-28">
            <nav className="flex flex-col gap-4 py-2">
              {SECTIONS.map(({ id, label }) => {
                const isActive = activeId === id;
                return (
                  <button
                    key={id}
                    onClick={() => scrollToSection(id)}
                    className="group flex items-center gap-3.5 text-left py-1 cursor-pointer focus:outline-none"
                    aria-label={`跳转到${label}`}
                  >
                    <span
                      className={`h-[2px] transition-all duration-300 ease-out shrink-0 ${
                        isActive
                          ? 'w-14 bg-white'
                          : 'w-6 bg-neutral-600 group-hover:w-9 group-hover:bg-neutral-400'
                      }`}
                    />
                    <span
                      className={`transition-all duration-300 tracking-tight select-none ${
                        isActive
                          ? 'text-white font-bold text-base'
                          : 'text-neutral-500 font-medium text-sm group-hover:text-neutral-300'
                      }`}
                    >
                      {label}
                    </span>
                  </button>
                );
              })}
            </nav>

            {/* Author Identity Card in Sidebar */}
            <div className="mt-12 pt-6 border-t border-neutral-800">
              <div className="text-xs font-mono text-neutral-500 uppercase tracking-wider">作者</div>
              <a
                href="https://github.com/link231rog"
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-flex items-center gap-1.5 text-sm font-semibold text-white hover:underline"
              >
                <span>Zixuan Huang</span>
                <ArrowUpRight className="w-3.5 h-3.5" />
              </a>
              <div className="mt-0.5 text-xs font-mono text-neutral-500">@link231rog</div>
            </div>
          </div>
        </aside>

        {/* Content Column */}
        <main className="divide-y divide-neutral-800">
          {/* 00 · 概览 */}
          <motion.section
            id="hero"
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, amount: 0.2 }}
            variants={sectionReveal}
            className="py-20 md:py-24 lg:px-10 scroll-mt-16"
          >
            <div className="inline-flex items-center gap-2 px-3 py-1 border border-neutral-800 bg-neutral-950 text-sm font-mono text-neutral-300 mb-6">
              <span>Built by Zixuan Huang (@link231rog)</span>
            </div>

            <h1 className="text-5xl md:text-7xl font-bold tracking-tight text-white">
              Paper Daily
            </h1>
            <p className="mt-5 text-xl md:text-2xl text-neutral-300 font-normal">
              自动化文献推荐、问题追踪与文献库沉淀
            </p>

            <div className="mt-8 flex flex-wrap gap-2.5">
              {[
                'GitHub Actions 免服运行',
                '多维度文献推荐',
                '问题追踪与精读',
                '文献库与 Agent 直连',
              ].map((tag) => (
                <span
                  key={tag}
                  className="px-3.5 py-1.5 border border-neutral-800 bg-neutral-950 text-neutral-200 text-sm font-mono"
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
                className="inline-flex items-center gap-2 px-6 py-3 bg-white text-black font-semibold text-base hover:bg-neutral-200 transition-colors"
              >
                <span>GitHub 部署</span>
                <ArrowUpRight className="w-4 h-4" />
              </a>
              <a
                href="https://github.com/link231rog/feisu-paper-daily#readme"
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-2 px-6 py-3 border border-neutral-700 bg-black text-white font-semibold text-base hover:border-white transition-colors"
              >
                <span>架构文档</span>
              </a>
            </div>
          </motion.section>

          {/* 01 · 控制台与规则定义 */}
          <motion.section
            id="console"
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, amount: 0.2 }}
            variants={sectionReveal}
            className="py-16 lg:px-10 scroll-mt-16"
          >
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
              <h2 className="text-2xl md:text-3xl font-bold tracking-tight">控制台与规则定义</h2>
              <div className="flex flex-wrap gap-2">
                {['飞书', 'Obsidian', 'Notion', '自定义 Skill', '范例模板'].map((item) => (
                  <PlatformPill key={item} name={item} />
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 border-t border-l border-neutral-800">
              <GridCard
                title="轻量化配置"
                desc="直接在日常文档中维护关注标签、研究问题与过滤词，无需改代码。"
              />
              <GridCard
                title="自定义模板"
                desc="支持导入个人审稿 Skill 与笔记模板，按习惯生成总结。"
              />
            </div>
          </motion.section>

          {/* 02 · 文献推荐系统 */}
          <motion.section
            id="recommend"
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, amount: 0.2 }}
            variants={sectionReveal}
            className="py-16 lg:px-10 scroll-mt-16"
          >
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
              <h2 className="text-2xl md:text-3xl font-bold tracking-tight">文献推荐系统</h2>
              <div className="flex flex-wrap gap-2">
                {['arXiv', 'HuggingFace', 'OpenReview', 'Semantic Scholar', 'GitHub', 'DBLP'].map(
                  (item) => (
                    <PlatformPill key={item} name={item} />
                  )
                )}
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 border-t border-l border-neutral-800">
              <GridCard
                title="多信源抓取"
                desc="支持 arXiv、HuggingFace、OpenReview、Semantic Scholar 等主流信源。"
              />
              <GridCard
                title="相关性打分"
                desc="结合关注标签、文献库偏好与追踪问题进行关联打分。"
              />
              <GridCard
                title="质量过滤"
                desc="剔除低分论文，按评分分为「精读必看」与「速览雷达」。"
              />
            </div>
          </motion.section>

          {/* 03 · 深度精读与问题追踪 */}
          <motion.section
            id="digest-tracking"
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, amount: 0.2 }}
            variants={sectionReveal}
            className="py-16 lg:px-10 scroll-mt-16"
          >
            <h2 className="text-2xl md:text-3xl font-bold tracking-tight mb-8">
              深度精读与问题追踪
            </h2>

            <div className="grid grid-cols-1 md:grid-cols-2 border-t border-l border-neutral-800">
              <GridCard
                title="方法与公式"
                desc="一句话对齐基线指出核心变量，提炼模块链路与关键公式。"
              />
              <GridCard
                title="实验核查"
                desc="核对正文图表，列出真实涨点、算力开销与失效边界。"
              />
              <GridCard
                title="问题追踪"
                desc="针对关注问题跨文献梳理支持证据、反例与研究盲区。"
              />
              <GridCard
                title="子问题追问"
                desc="当旧问题收敛或出现证据缺口时，自动生成后续追问。"
              />
            </div>
          </motion.section>

          {/* 04 · 文献库与 Agent 直连 */}
          <motion.section
            id="library"
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, amount: 0.2 }}
            variants={sectionReveal}
            className="py-16 lg:px-10 scroll-mt-16"
          >
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
              <h2 className="text-2xl md:text-3xl font-bold tracking-tight">
                文献库与 Agent 直连
              </h2>
              <div className="flex flex-wrap gap-2">
                {['飞书', 'Obsidian', 'Notion', 'Zotero'].map((item) => (
                  <PlatformPill key={item} name={item} />
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 border-t border-l border-neutral-800">
              <GridCard
                title="原生文献库"
                desc="直接基于所选平台（飞书、Obsidian、Notion 或 Zotero）构建个人文献库。"
              />
              <GridCard
                title="入库与批注"
                desc="勾选论文沉淀入库，自动抓取正文生成精读笔记并进行细节批注。"
              />
              <GridCard
                title="Agent 直连"
                desc="paper-library CLI 直接读取文献库中的高亮与批注，供本地 Agent 调用。"
              />
            </div>
          </motion.section>

          {/* 05 · 日报推送 */}
          <motion.section
            id="delivery"
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, amount: 0.2 }}
            variants={sectionReveal}
            className="py-16 lg:px-10 scroll-mt-16"
          >
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
              <h2 className="text-2xl md:text-3xl font-bold tracking-tight">日报推送</h2>
              <div className="flex flex-wrap gap-2">
                {['飞书', 'Email', '微信公众号', 'Telegram'].map((item) => (
                  <PlatformPill key={item} name={item} />
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 border-t border-l border-neutral-800">
              <GridCard title="飞书" desc="生成飞书云文档日报与阅读待办。" />
              <GridCard title="邮件" desc="SMTP 推送 HTML 日报。" />
              <GridCard title="微信公众号" desc="自动排版并写入草稿箱。" />
              <GridCard title="Telegram" desc="Bot 实时推送摘要与评分。" />
            </div>
          </motion.section>

          {/* 06 · 接入触发与部署 */}
          <motion.section
            id="deploy"
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, amount: 0.2 }}
            variants={sectionReveal}
            className="py-16 lg:px-10 scroll-mt-16"
          >
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
              <h2 className="text-2xl md:text-3xl font-bold tracking-tight">接入触发与部署</h2>
              <div className="flex flex-wrap gap-2">
                {['GitHub Actions', 'OpenClaw', 'Hermes', 'Grok Bot', 'Webhook'].map((item) => (
                  <PlatformPill key={item} name={item} />
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 border-t border-l border-neutral-800 mb-8">
              <GridCard
                title="GitHub Actions"
                desc="Fork 仓库填好密钥即可定时运行，无需服务器。"
              />
              <GridCard
                title="Agent 检索"
                desc="支持 OpenClaw、Hermes 等通过 CLI 或 Tool 协议直接调用。"
              />
              <GridCard
                title="Webhook 触发"
                desc="单条请求触发运行，动态传入临时问题与过滤规则。"
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 border-t border-l border-neutral-800 mb-8">
              <div className="p-6 border-r border-b border-neutral-800 flex items-center gap-3">
                <GitPullRequest className="w-5 h-5 text-white shrink-0" />
                <div>
                  <div className="text-lg font-semibold">Fork 仓库</div>
                  <div className="text-sm text-neutral-400 mt-1">克隆或 Fork 项目仓库</div>
                </div>
              </div>
              <div className="p-6 border-r border-b border-neutral-800 flex items-center gap-3">
                <ShieldCheck className="w-5 h-5 text-white shrink-0" />
                <div>
                  <div className="text-lg font-semibold">Agent / CLI 引导初始化</div>
                  <div className="text-sm text-neutral-400 mt-1">多选勾选信源与渠道，按需填入对应 Key</div>
                </div>
              </div>
              <div className="p-6 border-r border-b border-neutral-800 flex items-center gap-3">
                <Send className="w-5 h-5 text-white shrink-0" />
                <div>
                  <div className="text-lg font-semibold">生成配置与控制台</div>
                  <div className="text-sm text-neutral-400 mt-1">自动写入配置、密钥与初始控制台文档</div>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 border-t border-l border-neutral-800">
              <div className="border-r border-b border-neutral-800 bg-neutral-950 p-5 flex items-center justify-between gap-4">
                <div className="min-w-0">
                  <div className="text-xs text-neutral-400 mb-1">交互式多选引导与渠道密钥初始化</div>
                  <code className="text-base font-mono text-white block overflow-x-auto">
                    $ {initCommand}
                  </code>
                </div>
                <button
                  onClick={() => handleCopy(initCommand, 'init')}
                  className="inline-flex items-center gap-2 px-4 py-2 border border-neutral-700 bg-black text-white text-sm font-medium hover:border-white transition-colors shrink-0 cursor-pointer"
                >
                  {copiedCmd === 'init' ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                  <span>{copiedCmd === 'init' ? '已复制' : '复制'}</span>
                </button>
              </div>

              <div className="border-r border-b border-neutral-800 bg-neutral-950 p-5 flex items-center justify-between gap-4">
                <div className="min-w-0">
                  <div className="text-xs text-neutral-400 mb-1">Agent 直连检索文献库与个人批注</div>
                  <code className="text-base font-mono text-white block overflow-x-auto">
                    $ {cliCommand}
                  </code>
                </div>
                <button
                  onClick={() => handleCopy(cliCommand, 'search')}
                  className="inline-flex items-center gap-2 px-4 py-2 border border-neutral-700 bg-black text-white text-sm font-medium hover:border-white transition-colors shrink-0 cursor-pointer"
                >
                  {copiedCmd === 'search' ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                  <span>{copiedCmd === 'search' ? '已复制' : '复制'}</span>
                </button>
              </div>
            </div>
          </motion.section>

          {/* Author Footer */}
          <footer className="py-10 lg:px-10 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="w-2.5 h-2.5 bg-white" />
              <span className="text-base font-semibold text-white">Paper Daily</span>
              <span className="text-neutral-700">·</span>
              <a
                href="https://github.com/link231rog"
                target="_blank"
                rel="noreferrer"
                className="text-base text-neutral-300 hover:text-white transition-colors"
              >
                Zixuan Huang (@link231rog)
              </a>
            </div>
            <div className="flex items-center gap-6">
              <a
                href="https://github.com/link231rog/feisu-paper-daily"
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 text-sm font-mono text-neutral-300 hover:text-white transition-colors"
              >
                <span>github.com/link231rog/feisu-paper-daily</span>
                <ArrowUpRight className="w-4 h-4" />
              </a>
            </div>
          </footer>
        </main>
      </div>
    </div>
  );
}
