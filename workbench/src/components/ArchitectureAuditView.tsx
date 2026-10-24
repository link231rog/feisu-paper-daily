import React, { useState } from 'react';
import { AUDIT_MODULES, AuditModule } from '../data/auditData';
import { Copy, Check, ArrowRight, FileCode2, AlertTriangle, GitCompare } from 'lucide-react';

export const ArchitectureAuditView: React.FC = () => {
  const [selectedDimension, setSelectedDimension] = useState<'all' | 'ai_interaction' | 'multi_ecosystem' | 'github_actions'>('all');
  const [selectedModuleId, setSelectedModuleId] = useState<string>(AUDIT_MODULES[0].id);
  const [codeViewMode, setCodeViewMode] = useState<'side_by_side' | 'v1_only' | 'v2_only'>('side_by_side');
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const filteredModules = AUDIT_MODULES.filter(
    (m) => selectedDimension === 'all' || m.dimension === selectedDimension
  );

  const activeModule: AuditModule =
    filteredModules.find((m) => m.id === selectedModuleId) || filteredModules[0] || AUDIT_MODULES[0];

  const handleCopyCode = (code: string, key: string) => {
    navigator.clipboard.writeText(code);
    setCopiedId(key);
    setTimeout(() => setCopiedId(null), 1800);
  };

  const dimensionLabel = (dim: AuditModule['dimension']) => {
    if (dim === 'ai_interaction') return 'AI 主动追踪与批注';
    if (dim === 'multi_ecosystem') return '四端双向适配器';
    return 'GitHub Actions 零污染';
  };

  return (
    <div className="space-y-8">
      {/* Top Architecture Summary Banner */}
      <div className="border border-slate-800 bg-[#111827] rounded-xl p-6">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4 pb-6 border-b border-slate-800/80">
          <div>
            <div className="text-xs text-sky-400 font-mono mb-1.5">
              源码级静态审计 · 基于上传的 feisu-paper-daily (286 KB / 13 个核心模块)
            </div>
            <h2 className="text-2xl font-semibold text-white tracking-tight">
              01. 现有方案瓶颈诊断与 v2.0 架构重构对照
            </h2>
          </div>

          {/* Interactive Filter Segmented Control */}
          <div className="flex items-center gap-1 p-1 bg-[#0B0F19] border border-slate-800 rounded-lg self-start">
            {[
              { id: 'all', label: '全部模块 (5)' },
              { id: 'ai_interaction', label: 'AI 追踪与批注 (2)' },
              { id: 'multi_ecosystem', label: '多生态适配 (2)' },
              { id: 'github_actions', label: 'GitHub Actions 轻量化 (1)' },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => {
                  setSelectedDimension(tab.id as any);
                  const firstMatch = AUDIT_MODULES.find(
                    (m) => tab.id === 'all' || m.dimension === tab.id
                  );
                  if (firstMatch) setSelectedModuleId(firstMatch.id);
                }}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors whitespace-nowrap shrink-0 ${
                  selectedDimension === tab.id
                    ? 'bg-slate-800 text-white shadow-xs'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {/* High-Density Overview KPIs (Tabular Numerals, Unboxed Metadata) */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6 pt-6">
          <div>
            <div className="text-xs text-slate-400">已审计核心代码规模</div>
            <div className="text-2xl font-semibold text-white font-mono tabular-nums mt-1">
              1,188 LOC · 44.5 KB
            </div>
            <div className="text-xs text-slate-500 mt-1">
              覆盖 research / annotator / library / main.yml
            </div>
          </div>
          <div>
            <div className="text-xs text-slate-400">批注上下文实证容量</div>
            <div className="text-2xl font-semibold text-amber-400 font-mono tabular-nums mt-1">
              2K ➔ 18K Chars
            </div>
            <div className="text-xs text-slate-500 mt-1">
              从仅截断 Abstract 升级为 ar5iv 靶向章节拉取
            </div>
          </div>
          <div>
            <div className="text-xs text-slate-400">双向闭环支持生态</div>
            <div className="text-2xl font-semibold text-emerald-400 font-mono tabular-nums mt-1">
              1 端 ➔ 4 端对等
            </div>
            <div className="text-xs text-slate-500 mt-1">
              飞书 · Zotero · Notion · Obsidian 统一 AST
            </div>
          </div>
          <div>
            <div className="text-xs text-slate-400">云端状态丢失率 & 主分支污染</div>
            <div className="text-2xl font-semibold text-sky-400 font-mono tabular-nums mt-1">
              0 丢失 · 0 污染
            </div>
            <div className="text-xs text-slate-500 mt-1">
              修复 `contents: read` 蒸发漏洞，隔离至 `state-store`
            </div>
          </div>
        </div>
      </div>

      {/* Main Split Workspace: Left Module Selector + Right Deep Inspection */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Column: Audited Files List */}
        <div className="lg:col-span-4 border border-slate-800 bg-[#111827] rounded-xl divide-y divide-slate-800/80">
          <div className="px-5 py-4 flex items-center justify-between">
            <span className="text-xs font-medium text-slate-300">
              源码审计模块列表
            </span>
            <span className="text-xs text-slate-500 font-mono tabular-nums">
              点击切换模块诊断
            </span>
          </div>
          {filteredModules.map((mod) => {
            const isSelected = mod.id === activeModule.id;
            return (
              <button
                key={mod.id}
                onClick={() => setSelectedModuleId(mod.id)}
                className={`w-full text-left px-5 py-4 transition-colors ${
                  isSelected
                    ? 'bg-slate-800/70 text-white'
                    : 'hover:bg-slate-800/30 text-slate-300'
                }`}
              >
                <div className="flex items-center justify-between gap-2 text-xs text-slate-400 font-mono tabular-nums mb-1.5">
                  <span className="truncate text-sky-400">{mod.filePath}</span>
                  <span className="shrink-0">{mod.linesOfCode} lines</span>
                </div>
                <div className="text-sm font-semibold text-slate-100 leading-snug mb-2">
                  {mod.title}
                </div>
                <div className="flex items-center gap-2 text-xs text-slate-400">
                  <span>{dimensionLabel(mod.dimension)}</span>
                  <span aria-hidden="true">·</span>
                  <span className={mod.severity === 'critical' ? 'text-amber-400' : 'text-emerald-400'}>
                    {mod.severity === 'critical' ? '核心架构重构点' : '重要能力补齐'}
                  </span>
                </div>
              </button>
            );
          })}
        </div>

        {/* Right Column: Detailed Bottleneck Diagnosis & Code Diff */}
        <div className="lg:col-span-8 border border-slate-800 bg-[#111827] rounded-xl p-6 space-y-6">
          {/* Header Info */}
          <div className="pb-5 border-b border-slate-800">
            <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400 font-mono tabular-nums mb-2">
              <FileCode2 className="w-3.5 h-3.5 text-sky-400" />
              <span className="text-sky-400">{activeModule.filePath}</span>
              <span aria-hidden="true">·</span>
              <span>{activeModule.linesOfCode} LOC ({activeModule.fileSizeKB} KB)</span>
              <span aria-hidden="true">·</span>
              <span>{dimensionLabel(activeModule.dimension)}</span>
            </div>
            <h3 className="text-xl font-semibold text-white">
              {activeModule.title}
            </h3>

            {/* Before vs After Summary Strip */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4 pt-4 border-t border-slate-800/60 text-xs">
              <div className="p-3.5 rounded-lg bg-[#0B0F19] border border-slate-800/90">
                <div className="font-mono text-amber-400 mb-1">v1.x 当前实现局限</div>
                <p className="text-slate-300 leading-relaxed">{activeModule.v1StatusSummary}</p>
              </div>
              <div className="p-3.5 rounded-lg bg-[#0B0F19] border border-slate-800/90">
                <div className="font-mono text-emerald-400 mb-1">v2.0 架构重构方案</div>
                <p className="text-slate-200 leading-relaxed">{activeModule.v2UpgradeSummary}</p>
              </div>
            </div>
          </div>

          {/* Bottleneck Breakdown List */}
          <div className="space-y-4">
            <h4 className="text-sm font-semibold text-slate-200">
              源码定位与根因剖析 (Root-Cause & Refactoring Strategy)
            </h4>
            <div className="space-y-3">
              {activeModule.keyBottlenecks.map((b, idx) => (
                <div
                  key={idx}
                  className="p-4 rounded-lg bg-[#0B0F19] border border-slate-800 space-y-2.5"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2 text-sm font-medium text-white">
                      <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
                      <span>{b.issue}</span>
                    </div>
                    <span className="text-xs font-mono text-slate-400 tabular-nums">
                      定位: {b.lineRef}
                    </span>
                  </div>
                  <p className="text-xs text-slate-400 leading-relaxed">
                    <strong className="text-slate-300">影响评估：</strong>
                    {b.impact}
                  </p>
                  <div className="pt-2 border-t border-slate-800/70 flex items-start gap-2 text-xs text-emerald-300 leading-relaxed">
                    <ArrowRight className="w-3.5 h-3.5 mt-0.5 shrink-0 text-emerald-400" />
                    <span>
                      <strong className="text-emerald-400">v2.0 改造落地：</strong>
                      {b.solution}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Quantitative Metrics Table */}
          <div>
            <h4 className="text-sm font-semibold text-slate-200 mb-3">
              改造前后量化指标对比
            </h4>
            <div className="overflow-x-auto border border-slate-800 rounded-lg">
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="border-b border-slate-800 bg-[#0B0F19] text-slate-400">
                    <th className="py-2.5 px-4 font-medium">评估维度</th>
                    <th className="py-2.5 px-4 font-medium font-mono">v1.x 现状</th>
                    <th className="py-2.5 px-4 font-medium font-mono text-emerald-400">v2.0 重构后</th>
                    <th className="py-2.5 px-4 font-medium text-right font-mono">收益提升</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/70 font-mono tabular-nums">
                  {activeModule.metricsComparison.map((m, i) => (
                    <tr key={i} className="hover:bg-slate-800/20">
                      <td className="py-2.5 px-4 font-sans text-slate-200">{m.metric}</td>
                      <td className="py-2.5 px-4 text-slate-400">{m.v1Value}</td>
                      <td className="py-2.5 px-4 text-emerald-300">{m.v2Value}</td>
                      <td className="py-2.5 px-4 text-right text-sky-400">{m.delta}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Code Refactoring Diff Viewer */}
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
                <GitCompare className="w-4 h-4 text-sky-400" />
                <span>核心代码重构对照 (v1.x 原生实现 vs v2.0 升级实现)</span>
              </div>

              <div className="flex items-center gap-1 p-1 bg-[#0B0F19] border border-slate-800 rounded-lg">
                {[
                  { id: 'side_by_side', label: '双栏对照' },
                  { id: 'v1_only', label: '仅看 v1.x' },
                  { id: 'v2_only', label: '仅看 v2.0 重构代码' },
                ].map((mode) => (
                  <button
                    key={mode.id}
                    onClick={() => setCodeViewMode(mode.id as any)}
                    className={`px-2.5 py-1 text-xs rounded transition-colors whitespace-nowrap shrink-0 ${
                      codeViewMode === mode.id
                        ? 'bg-slate-800 text-white'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    {mode.label}
                  </button>
                ))}
              </div>
            </div>

            <div
              className={`grid gap-4 ${
                codeViewMode === 'side_by_side' ? 'grid-cols-1 xl:grid-cols-2' : 'grid-cols-1'
              }`}
            >
              {(codeViewMode === 'side_by_side' || codeViewMode === 'v1_only') && (
                <div className="border border-slate-800 rounded-lg bg-[#0B0F19] overflow-hidden flex flex-col">
                  <div className="px-4 py-2 border-b border-slate-800 flex items-center justify-between text-xs font-mono text-amber-400 bg-slate-900/60">
                    <span>v1.x 原始代码片段</span>
                    <button
                      onClick={() => handleCopyCode(activeModule.v1CodeSnippet, `${activeModule.id}-v1`)}
                      className="flex items-center gap-1 text-slate-400 hover:text-white transition-colors"
                    >
                      {copiedId === `${activeModule.id}-v1` ? (
                        <>
                          <Check className="w-3.5 h-3.5 text-emerald-400" />
                          <span>已复制</span>
                        </>
                      ) : (
                        <>
                          <Copy className="w-3.5 h-3.5" />
                          <span>复制</span>
                        </>
                      )}
                    </button>
                  </div>
                  <pre className="p-4 text-xs font-mono text-slate-300 overflow-x-auto leading-relaxed">
                    <code>{activeModule.v1CodeSnippet}</code>
                  </pre>
                </div>
              )}

              {(codeViewMode === 'side_by_side' || codeViewMode === 'v2_only') && (
                <div className="border border-slate-800 rounded-lg bg-[#0B0F19] overflow-hidden flex flex-col">
                  <div className="px-4 py-2 border-b border-slate-800 flex items-center justify-between text-xs font-mono text-emerald-400 bg-slate-900/60">
                    <span>v2.0 重构后生产代码</span>
                    <button
                      onClick={() => handleCopyCode(activeModule.v2CodeSnippet, `${activeModule.id}-v2`)}
                      className="flex items-center gap-1 text-slate-400 hover:text-white transition-colors"
                    >
                      {copiedId === `${activeModule.id}-v2` ? (
                        <>
                          <Check className="w-3.5 h-3.5 text-emerald-400" />
                          <span>已复制</span>
                        </>
                      ) : (
                        <>
                          <Copy className="w-3.5 h-3.5" />
                          <span>复制 v2.0 代码</span>
                        </>
                      )}
                    </button>
                  </div>
                  <pre className="p-4 text-xs font-mono text-emerald-200/90 overflow-x-auto leading-relaxed">
                    <code>{activeModule.v2CodeSnippet}</code>
                  </pre>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
