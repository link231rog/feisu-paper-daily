import React, { useState } from 'react';
import {
  HYPOTHESIS_SCENARIOS,
  SAMPLE_ANNOTATED_PAPER,
  RichAnnotationSpan,
} from '../data/simulationData';
import { Send, Sparkles, BookOpen, GitBranch, MessageSquarePlus, ExternalLink } from 'lucide-react';

export const ActiveResearchSandbox: React.FC = () => {
  const [selectedScenarioId, setSelectedScenarioId] = useState<string>(HYPOTHESIS_SCENARIOS[0].id);
  const [selectedDayIndex, setSelectedDayIndex] = useState<number>(0);
  const [annotationMode, setAnnotationMode] = useState<'v2_fulltext' | 'v1_abstract'>('v2_fulltext');
  const [selectedEcosystemLink, setSelectedEcosystemLink] = useState<'feishu' | 'obsidian' | 'notion' | 'zotero'>('obsidian');

  // Custom @AI question thread simulator state
  const [aiThreads, setAiThreads] = useState(SAMPLE_ANNOTATED_PAPER.presetAiQuestions);
  const [customQuery, setCustomQuery] = useState('');
  const [isSimulatingQuery, setIsSimulatingQuery] = useState(false);

  const scenario =
    HYPOTHESIS_SCENARIOS.find((s) => s.id === selectedScenarioId) || HYPOTHESIS_SCENARIOS[0];
  const currentStep = scenario.timeline[selectedDayIndex] || scenario.timeline[0];

  const activeSpans: RichAnnotationSpan[] =
    annotationMode === 'v2_fulltext'
      ? SAMPLE_ANNOTATED_PAPER.v2FullTextSpans
      : SAMPLE_ANNOTATED_PAPER.v1AbstractOnlySpans;

  const handleAskInlineAi = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = customQuery.trim();
    if (!trimmed) return;
    setIsSimulatingQuery(true);

    setTimeout(() => {
      const normalized = trimmed.startsWith('@AI') ? trimmed : `@AI: ${trimmed}`;
      let synthesizedAnswer =
        '已拉取 `ar5iv:2610.14892` §3.2 & §4.3 章节原文核查：TieredKV 通过在 Prefill 阶段计算 Pre-RoPE 通道平滑因子，并将低注意力页压缩为 2-bit 常驻 HBM 显存，避免了 PCIe 带宽瓶颈；在 Batch=32 并发下 TPOT 仅增加 1.8ms，显著优于 Quest 的 CPU Offload 方案。';
      let anchor = 'ar5iv §4.2, Figure 5 & Table 2';

      if (trimmed.toLowerCase().includes('flashattention') || trimmed.includes('算子') || trimmed.includes('triton')) {
        synthesizedAnswer =
          '已检索 `ar5iv:2610.14892` **§3.4 Kernel Implementation**：作者基于 FlashAttention-3 / Triton 编写了融合反量化算子（Fused INT2-Unpack + WGMMA），当某 64-token 影子页被质心内积命中时，直接在寄存器级反量化为 FP16 参与 Attention 计算，无需写回全局 HBM。';
        anchor = 'ar5iv §3.4, Listing 1 (Triton Kernel)';
      }

      setAiThreads((prev) => [
        ...prev,
        {
          id: `qa-custom-${Date.now()}`,
          userPrompt: normalized,
          targetSection: '§3.4 & §4.2 ar5iv Full-Text Dynamic Extraction',
          aiResponse: synthesizedAnswer,
          citationAnchor: anchor,
        },
      ]);
      setCustomQuery('');
      setIsSimulatingQuery(false);
    }, 350);
  };

  const getSpanHighlightStyle = (type: RichAnnotationSpan['type']) => {
    switch (type) {
      case 'baseline':
        return 'bg-emerald-500/20 text-emerald-200 border-b border-emerald-400/60 px-1 py-0.5 rounded-xs';
      case 'claim':
        return 'bg-amber-500/20 text-amber-200 border-b border-amber-400/60 px-1 py-0.5 rounded-xs';
      case 'critique':
        return 'bg-orange-500/20 text-orange-200 border-b border-orange-400/60 px-1 py-0.5 rounded-xs';
      case 'counter_evidence':
        return 'bg-pink-500/25 text-pink-200 border-b border-pink-400/70 px-1 py-0.5 rounded-xs font-medium';
    }
  };

  const getSpanBadgeColor = (type: RichAnnotationSpan['type']) => {
    switch (type) {
      case 'baseline':
        return 'text-emerald-400';
      case 'claim':
        return 'text-amber-400';
      case 'critique':
        return 'text-orange-400';
      case 'counter_evidence':
        return 'text-pink-400';
    }
  };

  return (
    <div className="space-y-8">
      {/* Section Part 1: Cross-Day Hypothesis State Machine */}
      <div className="border border-slate-800 bg-[#111827] rounded-xl p-6 space-y-6">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4 pb-5 border-b border-slate-800">
          <div>
            <div className="text-xs text-sky-400 font-mono mb-1">
              突破 1 & 3 · 跨日问题状态机 (Hypothesis State Machine) + 对立反例检索 (Counter-Evidence Querying)
            </div>
            <h2 className="text-2xl font-semibold text-white tracking-tight">
              02. AI 主动追踪问题演进与正反双向检索沙盘
            </h2>
          </div>

          {/* Scenario Selector */}
          <div className="flex items-center gap-1 p-1 bg-[#0B0F19] border border-slate-800 rounded-lg self-start">
            {HYPOTHESIS_SCENARIOS.map((sc, idx) => (
              <button
                key={sc.id}
                onClick={() => {
                  setSelectedScenarioId(sc.id);
                  setSelectedDayIndex(0);
                }}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors whitespace-nowrap shrink-0 ${
                  selectedScenarioId === sc.id
                    ? 'bg-slate-800 text-white'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                议题 {idx + 1}: {sc.domainTag}
              </button>
            ))}
          </div>
        </div>

        {/* Tracked Question Header & Timeline Stepper */}
        <div className="p-4 rounded-lg bg-[#0B0F19] border border-slate-800 space-y-3">
          <div className="text-xs text-slate-400 font-mono">
            当前追踪议题 · {scenario.domainTag}
          </div>
          <div className="text-base font-semibold text-white leading-snug">
            {scenario.question}
          </div>
          <div className="text-xs text-slate-400">
            {scenario.initialPremise}
          </div>

          {/* Interactive Timeline Stepper */}
          <div className="pt-3 border-t border-slate-800/80 flex flex-wrap items-center gap-3">
            <span className="text-xs text-slate-400 font-mono">点击步进演化时间轴：</span>
            {scenario.timeline.map((step, idx) => (
              <button
                key={step.day}
                onClick={() => setSelectedDayIndex(idx)}
                className={`px-3.5 py-2 rounded-lg text-xs font-mono transition-colors flex items-center gap-2 border ${
                  selectedDayIndex === idx
                    ? 'bg-sky-500/15 border-sky-500/60 text-white'
                    : 'bg-[#111827] border-slate-800 text-slate-400 hover:text-slate-200'
                }`}
              >
                <span>{step.dateStr}</span>
                <span aria-hidden="true">·</span>
                <span
                  className={
                    step.status === 'contested'
                      ? 'text-amber-400'
                      : step.status === 'falsified'
                      ? 'text-pink-400'
                      : step.status === 'converged'
                      ? 'text-emerald-400'
                      : 'text-sky-400'
                  }
                >
                  {step.statusLabel}
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* Active Day Details Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left 5 cols: Dual Query Planner (Affirmative vs Adversarial) */}
          <div className="lg:col-span-5 space-y-4">
            <div className="p-4 rounded-lg bg-[#0B0F19] border border-slate-800 space-y-3">
              <div className="flex items-center justify-between text-xs font-mono">
                <span className="text-slate-300">动态状态权重 (Dynamic Weight)</span>
                <span className="text-sky-400 tabular-nums">
                  {currentStep.weightMultiplier.toFixed(2)}x 检索配额
                </span>
              </div>
              <div className="text-xs text-slate-400 leading-relaxed">
                v1.x 在连续命中后机械降权至 0.6x；v2.0 在发现正反方交锋（Contested）时自动提权至{' '}
                <span className="text-amber-300 font-mono">1.35x</span>，集中算力攻克争议焦点。
              </div>
            </div>

            <div className="p-4 rounded-lg bg-[#0B0F19] border border-slate-800 space-y-3">
              <div className="text-xs font-semibold text-emerald-400 font-mono">
                1. 正向机制检索式 (Affirmative S2 Queries)
              </div>
              <ul className="space-y-2 text-xs font-mono text-slate-300">
                {currentStep.affirmativeQueries.map((q, i) => (
                  <li key={i} className="p-2 rounded bg-[#111827] border border-slate-800/80">
                    "{q}"
                  </li>
                ))}
              </ul>

              <div className="text-xs font-semibold text-pink-400 font-mono pt-2">
                2. 对抗性反例与缺陷检索式 (Adversarial Counter-Queries)
              </div>
              <ul className="space-y-2 text-xs font-mono text-pink-200/90">
                {currentStep.adversarialQueries.map((q, i) => (
                  <li key={i} className="p-2 rounded bg-[#111827] border border-pink-900/40">
                    "{q}"
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {/* Right 7 cols: Discovered Evidence & Spawned Sub-Questions */}
          <div className="lg:col-span-7 space-y-4">
            <div className="p-4 rounded-lg bg-[#0B0F19] border border-slate-800 space-y-3">
              <div className="text-xs font-semibold text-slate-200">
                当日捕获的正反方实证论文 ({currentStep.dateStr})
              </div>
              <div className="space-y-3">
                {currentStep.discoveredPapers.map((p, i) => (
                  <div
                    key={i}
                    className="p-3.5 rounded-lg bg-[#111827] border border-slate-800 space-y-1.5"
                  >
                    <div className="flex items-center justify-between gap-2 text-xs font-mono">
                      <span
                        className={
                          p.stance === 'counter'
                            ? 'text-pink-400 font-semibold'
                            : p.stance === 'supporting'
                            ? 'text-emerald-400'
                            : 'text-sky-400'
                        }
                      >
                        {p.stance === 'counter'
                          ? '⚡ 反例/证伪证据 (Counter-Evidence)'
                          : p.stance === 'supporting'
                          ? '🟢 正向支持证据 (Supporting)'
                          : '🛠️ 新范式突破 (Methodology)'}
                      </span>
                      <span className="text-slate-400">{p.venue}</span>
                    </div>
                    <div className="text-sm font-medium text-white">{p.title}</div>
                    <p className="text-xs text-slate-300 leading-relaxed">{p.finding}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="p-4 rounded-lg bg-[#0B0F19] border border-slate-800 space-y-3">
              <div className="flex items-center gap-2 text-xs font-semibold text-sky-400">
                <GitBranch className="w-4 h-4" />
                <span>AI 跨日证据综合与子问题自动裂变 (Synthesis & Next QA)</span>
              </div>
              <p className="text-xs text-slate-300 leading-relaxed">{currentStep.aiSynthesis}</p>
              <div className="pt-2 border-t border-slate-800/80 space-y-1.5">
                <div className="text-xs font-mono text-amber-400">
                  自动反写至四端控制台「建议跟进子问题」：
                </div>
                {currentStep.spawnedSubQuestions.map((sq, i) => (
                  <div
                    key={i}
                    className="text-xs text-slate-200 bg-[#111827] px-3 py-2 rounded border border-slate-800"
                  >
                    ↳ {sq}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Section Part 2: Full-Text Section-Targeted Annotations & @AI Loop */}
      <div className="border border-slate-800 bg-[#111827] rounded-xl p-6 space-y-6">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4 pb-5 border-b border-slate-800">
          <div>
            <div className="text-xs text-emerald-400 font-mono mb-1">
              突破 2 & 4 · 超越摘要的 ar5iv 全文章节靶向批注 + 文档内 @AI 异步追问闭环
            </div>
            <h2 className="text-2xl font-semibold text-white tracking-tight">
              03. 全文章节四色原位高亮与 @AI 异步追问交互器
            </h2>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {/* Toggle v1 Abstract Only vs v2 Full-Text */}
            <div className="flex items-center gap-1 p-1 bg-[#0B0F19] border border-slate-800 rounded-lg">
              <button
                onClick={() => setAnnotationMode('v1_abstract')}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors whitespace-nowrap shrink-0 ${
                  annotationMode === 'v1_abstract'
                    ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                v1.x 仅摘要批注 (盲猜局限)
              </button>
              <button
                onClick={() => setAnnotationMode('v2_fulltext')}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors whitespace-nowrap shrink-0 ${
                  annotationMode === 'v2_fulltext'
                    ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                v2.0 ar5iv 全文章节靶向批注 (含实验表反例)
              </button>
            </div>
          </div>
        </div>

        {/* Paper Metadata Header */}
        <div className="p-4 rounded-lg bg-[#0B0F19] border border-slate-800 space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs font-mono text-slate-400 tabular-nums">
            <span>{SAMPLE_ANNOTATED_PAPER.venue}</span>
            <span>
              Taste: {SAMPLE_ANNOTATED_PAPER.tasteScore} · Question Fit: {SAMPLE_ANNOTATED_PAPER.fitScore}/10.0
            </span>
          </div>
          <h3 className="text-lg font-semibold text-white">
            {SAMPLE_ANNOTATED_PAPER.title}
          </h3>
          <p className="text-xs text-slate-300 leading-relaxed">
            <strong className="text-sky-400 font-mono">横向裁判推荐理由：</strong>
            {SAMPLE_ANNOTATED_PAPER.judgeReason}
          </p>
        </div>

        {/* Annotated Sections Stream */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          <div className="lg:col-span-7 space-y-4">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span className="font-semibold text-slate-200">
                {annotationMode === 'v2_fulltext'
                  ? 'ar5iv 结构化章节原位渲染 (Abstract + §3 Method + §4 Experiments + §6 Limitations)'
                  : 'v1.x 仅 Abstract 截断渲染 (缺失实验表格与真实硬件消融)'}
              </span>
              <div className="flex items-center gap-2 font-mono">
                <span>双链预览格式:</span>
                {(['obsidian', 'feishu', 'notion', 'zotero'] as const).map((eco) => (
                  <button
                    key={eco}
                    onClick={() => setSelectedEcosystemLink(eco)}
                    className={`px-2 py-0.5 rounded text-xs capitalize ${
                      selectedEcosystemLink === eco
                        ? 'bg-slate-800 text-sky-400'
                        : 'text-slate-500 hover:text-slate-300'
                    }`}
                  >
                    {eco}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-4">
              {activeSpans.map((span) => (
                <div
                  key={span.id}
                  className="p-4 rounded-lg bg-[#0B0F19] border border-slate-800 space-y-3"
                >
                  <div className="flex items-center justify-between text-xs font-mono text-slate-400">
                    <span className="text-slate-300 font-semibold">{span.sectionTitle}</span>
                    <span className={getSpanBadgeColor(span.type)}>{span.badgeLabel}</span>
                  </div>

                  {/* Verbatim Text with Inline Highlight */}
                  <p className="text-sm text-slate-300 leading-relaxed font-sans">
                    {span.beforeText}
                    <span className={getSpanHighlightStyle(span.type)}>
                      {span.highlightedText}
                    </span>
                    {span.afterText}
                  </p>

                  {/* Inline Annotation Explanation & Bidirectional Library Link */}
                  <div className="p-3 rounded bg-[#111827] border border-slate-800/90 text-xs space-y-2">
                    <div className="text-slate-200 leading-relaxed">
                      <span className={`font-mono font-semibold mr-1.5 ${getSpanBadgeColor(span.type)}`}>
                        [{span.badgeLabel}]
                      </span>
                      {span.comment}
                    </div>

                    {span.libraryMatch && (
                      <div className="pt-2 border-t border-slate-800/80 flex flex-wrap items-center justify-between gap-2 font-mono">
                        <span className="text-emerald-400">
                          🟢 已命中个人文献库基线：{span.libraryMatch.noteTitle}
                        </span>
                        <span className="text-sky-400 flex items-center gap-1">
                          <span>
                            {selectedEcosystemLink.toUpperCase()} 双链:{' '}
                            {span.libraryMatch.ecosystems[selectedEcosystemLink]}
                          </span>
                          <ExternalLink className="w-3 h-3" />
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Right 5 cols: In-Document @AI Async Question & Answer Loop */}
          <div className="lg:col-span-5 border border-slate-800 rounded-xl bg-[#0B0F19] p-5 flex flex-col justify-between space-y-4">
            <div className="space-y-4">
              <div className="pb-3 border-b border-slate-800">
                <div className="flex items-center gap-2 text-sm font-semibold text-white">
                  <MessageSquarePlus className="w-4 h-4 text-sky-400" />
                  <span>文档内 `@AI` 异步追问闭环模拟器</span>
                </div>
                <p className="text-xs text-slate-400 mt-1 leading-relaxed">
                  您在飞书、Notion、Obsidian 或 Zotero 子笔记的任意位置写下{' '}
                  <code className="text-sky-400">@AI: 你的问题</code>，GitHub Actions
                  巡检或收到 Webhook 后自动拉取该论文的 `ar5iv` 全文章节与实验表格，将带章节锚点的解答原位写回笔记下方。
                </p>
              </div>

              {/* Existing Resolved Threads */}
              <div className="space-y-3 max-h-[420px] overflow-y-auto pr-1">
                {aiThreads.map((thread) => (
                  <div
                    key={thread.id}
                    className="p-3.5 rounded-lg bg-[#111827] border border-slate-800 space-y-2 text-xs"
                  >
                    <div className="font-mono text-sky-400 font-medium leading-snug">
                      {thread.userPrompt}
                    </div>
                    <div className="text-slate-400 font-mono text-[11px]">
                      🎯 靶向检索章节: {thread.targetSection}
                    </div>
                    <div className="text-slate-200 leading-relaxed pt-1 border-t border-slate-800/80">
                      {thread.aiResponse}
                    </div>
                    <div className="text-right font-mono text-[11px] text-emerald-400">
                      出处锚点: {thread.citationAnchor}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Interactive Input to Test @AI Follow-up */}
            <form onSubmit={handleAskInlineAi} className="pt-3 border-t border-slate-800 space-y-2.5">
              <label className="block text-xs font-mono text-slate-300">
                在当前论文笔记中模拟输入 `@AI` 追问：
              </label>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={customQuery}
                  onChange={(e) => setCustomQuery(e.target.value)}
                  placeholder="例如：它的 Triton 融合反量化算子是怎么写的？"
                  className="flex-1 bg-[#111827] border border-slate-700 rounded-lg px-3 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-sky-500"
                />
                <button
                  type="submit"
                  disabled={isSimulatingQuery}
                  className="px-3.5 py-2 bg-sky-500 hover:bg-sky-400 disabled:opacity-50 text-slate-950 font-semibold text-xs rounded-lg transition-colors flex items-center gap-1.5 whitespace-nowrap shrink-0"
                >
                  <Send className="w-3.5 h-3.5" />
                  <span>{isSimulatingQuery ? '检索 ar5iv 中...' : '触发 @AI 解答'}</span>
                </button>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
                <span>快捷测试提问：</span>
                <button
                  type="button"
                  onClick={() =>
                    setCustomQuery('它的 Triton 融合反量化算子是怎么实现的？需要写回 HBM 吗？')
                  }
                  className="text-sky-400 hover:underline"
                >
                  “Triton 反量化算子细节？”
                </button>
                <span>·</span>
                <button
                  type="button"
                  onClick={() =>
                    setCustomQuery('在 Batch=32 高并发下相比 Quest 的 CPU Offload 延迟优势多大？')
                  }
                  className="text-sky-400 hover:underline"
                >
                  “高并发延迟对比 Quest？”
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
};
