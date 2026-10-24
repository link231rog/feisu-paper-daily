/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import { ArchitectureAuditView } from './components/ArchitectureAuditView';
import { ActiveResearchSandbox } from './components/ActiveResearchSandbox';
import { MultiEcosystemMatrixView } from './components/MultiEcosystemMatrixView';
import { ZeroLocalWorkflowBuilder } from './components/ZeroLocalWorkflowBuilder';
import {
  REFACTORED_PYTHON_BUNDLE,
  generateGitHubWorkflowYaml,
} from './data/workflowTemplates';
import {
  FileSearch,
  Sparkles,
  Layers,
  GitBranch,
  Download,
  ChevronRight,
} from 'lucide-react';

type ActiveSection = 'audit' | 'research_sandbox' | 'multi_ecosystem' | 'github_actions';

export default function App() {
  const [activeSection, setActiveSection] = useState<ActiveSection>('audit');

  const handleExportFullBundle = () => {
    const defaultYaml = generateGitHubWorkflowYaml({
      ecosystems: { feishu: true, zotero: true, notion: true, obsidian: true },
      stateBackend: 'orphan_branch',
      fullTextMode: 'ar5iv_html_targeted',
      enableAdversarialQueries: true,
      enableInlineAiThreads: true,
      onDemandWebhookTrigger: true,
      schedulePreset: 'three_times_daily',
    });

    const combinedArtifact = `# ====================================================================
# Feishu Paper Daily 2.0 — Full Upgrade Blueprint & Code Bundle
# ====================================================================
# 1. .github/workflows/paper-daily-v2.yml (Zero-Local Orphan State Branch)
# 2. src/zotero_arxiv_daily/paper_daily_v2_core.py (State Machine + ar5iv + 4-Adapters)
# ====================================================================

# --- [FILE 1: .github/workflows/paper-daily-v2.yml] ---
${defaultYaml}

# --- [FILE 2: src/zotero_arxiv_daily/paper_daily_v2_core.py] ---
${REFACTORED_PYTHON_BUNDLE}
`;
    const blob = new Blob([combinedArtifact], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'feisu-paper-daily-v2-upgrade-bundle.txt';
    a.click();
    URL.revokeObjectURL(url);
  };

  const navItems: {
    id: ActiveSection;
    label: string;
    shortLabel: string;
    subtitle: string;
    icon: React.FC<{ className?: string }>;
  }[] = [
    {
      id: 'audit',
      label: '01. 架构瓶颈诊断与 Diff',
      shortLabel: '架构诊断',
      subtitle: '5 大核心模块源码审计与重构对照',
      icon: FileSearch,
    },
    {
      id: 'research_sandbox',
      label: '02. AI 主动追踪与全文批注',
      shortLabel: 'AI 追踪与批注',
      subtitle: '假设状态机 · 反例检索 · ar5iv · @AI 闭环',
      icon: Sparkles,
    },
    {
      id: 'multi_ecosystem',
      label: '03. 四端对称双向适配器',
      shortLabel: '四端双向适配',
      subtitle: '飞书 · Zotero · Notion · Obsidian',
      icon: Layers,
    },
    {
      id: 'github_actions',
      label: '04. 纯 GitHub Actions 运维',
      shortLabel: 'Actions 零污染',
      subtitle: 'Orphan 状态分支 · 按需触发生成器',
      icon: GitBranch,
    },
  ];

  return (
    <div className="min-h-screen bg-[#0B0F19] text-slate-200 flex flex-col">
      {/* Top Bar Contract: 3 Zones separated by gap-8 */}
      <header className="flex items-center justify-between gap-8 px-6 py-4 border-b border-slate-800 bg-[#0B0F19]/95 sticky top-0 z-30 backdrop-blur-xs">
        {/* Zone 1: Single text element wordmark */}
        <a
          href="#top"
          onClick={(e) => {
            e.preventDefault();
            setActiveSection('audit');
          }}
          className="text-base font-bold tracking-tight text-white whitespace-nowrap shrink-0 font-display"
        >
          Feishu Paper Daily 2.0 Workbench
        </a>

        {/* Zone 2: 4 concise single-line text navigation links */}
        <nav className="hidden md:flex items-center gap-6 text-sm font-medium text-slate-400">
          {navItems.map((item) => (
            <button
              key={item.id}
              onClick={() => setActiveSection(item.id)}
              className={`hover:text-white transition-colors whitespace-nowrap shrink-0 pb-0.5 ${
                activeSection === item.id
                  ? 'text-white border-b-2 border-sky-400'
                  : 'text-slate-400'
              }`}
            >
              {item.shortLabel}
            </button>
          ))}
        </nav>

        {/* Zone 3: 1 primary action */}
        <div className="flex items-center gap-3 shrink-0">
          <button
            onClick={handleExportFullBundle}
            className="px-4 py-2 text-xs font-semibold text-slate-950 bg-sky-400 hover:bg-sky-300 rounded-lg transition-colors whitespace-nowrap shrink-0 flex items-center gap-1.5"
          >
            <Download className="w-3.5 h-3.5" />
            <span>导出 v2.0 升级代码包</span>
          </button>
        </div>
      </header>

      {/* Workspace Body: Left Architecture Navigation Sidebar + Main Viewport */}
      <div className="flex-1 flex flex-col lg:flex-row max-w-[1600px] w-full mx-auto">
        {/* Left Sidebar (270px on desktop) */}
        <aside className="w-full lg:w-[270px] shrink-0 border-b lg:border-b-0 lg:border-r border-slate-800 bg-[#0B0F19] p-5 space-y-6">
          <div className="space-y-1">
            <div className="text-xs font-mono text-slate-400">
              工作台模块导航
            </div>
            <p className="text-xs text-slate-500 leading-relaxed">
              基于 `feisu-paper-daily` 源码审计，点击切换查看各维度的重构方案与交互沙盘。
            </p>
          </div>

          <div className="space-y-2">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = activeSection === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setActiveSection(item.id)}
                  className={`w-full text-left p-3 rounded-xl border transition-colors flex items-start justify-between gap-2 ${
                    isActive
                      ? 'bg-[#111827] border-sky-500/60 text-white'
                      : 'bg-transparent border-slate-800/60 text-slate-400 hover:bg-[#111827]/60 hover:text-slate-200'
                  }`}
                >
                  <div className="space-y-1 min-w-0">
                    <div className="flex items-center gap-2 text-xs font-semibold">
                      <Icon
                        className={`w-4 h-4 shrink-0 ${
                          isActive ? 'text-sky-400' : 'text-slate-500'
                        }`}
                      />
                      <span className="truncate">{item.label}</span>
                    </div>
                    <div className="text-[11px] text-slate-500 pl-6 truncate">
                      {item.subtitle}
                    </div>
                  </div>
                  <ChevronRight
                    className={`w-4 h-4 shrink-0 mt-0.5 ${
                      isActive ? 'text-sky-400' : 'text-slate-600'
                    }`}
                  />
                </button>
              );
            })}
          </div>

          {/* Architectural Topology Summary Box */}
          <div className="p-4 rounded-xl bg-[#111827] border border-slate-800 space-y-3 text-xs">
            <div className="font-semibold text-white">
              三大核心演进方向速览
            </div>
            <div className="space-y-2.5 text-slate-400 leading-relaxed">
              <div>
                <span className="text-emerald-400 font-mono">1. AI 深度交互：</span>
                跨日假设状态机 + 反例检索 + ar5iv 章节级四色批注 + 文档内 `@AI` 追问闭环。
              </div>
              <div>
                <span className="text-sky-400 font-mono">2. 四端双向对等：</span>
                统一 `AnnotatedPaperAST`，补齐 Zotero 子笔记、Notion Callout 与 Obsidian 云端 Git 双链回写。
              </div>
              <div>
                <span className="text-amber-400 font-mono">3. 本地零负担：</span>
                Orphan 分支 `state-store` 隔离状态 JSON，主分支零污染，支持跨端打星按需精读。
              </div>
            </div>
          </div>
        </aside>

        {/* Main Content Viewport */}
        <main className="flex-1 p-6 lg:p-8 min-w-0">
          {activeSection === 'audit' && <ArchitectureAuditView />}
          {activeSection === 'research_sandbox' && <ActiveResearchSandbox />}
          {activeSection === 'multi_ecosystem' && <MultiEcosystemMatrixView />}
          {activeSection === 'github_actions' && <ZeroLocalWorkflowBuilder />}
        </main>
      </div>
    </div>
  );
}
