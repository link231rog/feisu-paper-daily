import React, { useState } from 'react';
import { ECOSYSTEM_SPECS, EcosystemSpec } from '../data/adapterData';
import { Check, Copy, Layers, ArrowLeftRight, Database, FileText } from 'lucide-react';

export const MultiEcosystemMatrixView: React.FC = () => {
  const [selectedEcoId, setSelectedEcoId] = useState<EcosystemSpec['id']>('zotero');
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  const activeSpec =
    ECOSYSTEM_SPECS.find((e) => e.id === selectedEcoId) || ECOSYSTEM_SPECS[0];

  const handleCopy = (text: string, key: string) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 1800);
  };

  return (
    <div className="space-y-8">
      {/* Header & Comparison Matrix */}
      <div className="border border-slate-800 bg-[#111827] rounded-xl p-6 space-y-6">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4 pb-5 border-b border-slate-800">
          <div>
            <div className="text-xs text-sky-400 font-mono mb-1">
              四端对称双向协议 · 统一 AnnotatedPaperAST 编译至 Feishu / Zotero / Notion / Obsidian
            </div>
            <h2 className="text-2xl font-semibold text-white tracking-tight">
              04. 多生态双向适配器矩阵与原生载荷预览
            </h2>
          </div>

          {/* Ecosystem Selector Tabs */}
          <div className="flex items-center gap-1 p-1 bg-[#0B0F19] border border-slate-800 rounded-lg self-start">
            {ECOSYSTEM_SPECS.map((eco) => (
              <button
                key={eco.id}
                onClick={() => setSelectedEcoId(eco.id)}
                className={`px-3.5 py-1.5 text-xs font-medium rounded-md transition-colors whitespace-nowrap shrink-0 ${
                  selectedEcoId === eco.id
                    ? 'bg-slate-800 text-white shadow-xs'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {eco.name.split(' ')[0]}
              </button>
            ))}
          </div>
        </div>

        {/* Full 4-Ecosystem Capability Comparison Table */}
        <div className="overflow-x-auto border border-slate-800 rounded-lg">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="border-b border-slate-800 bg-[#0B0F19] text-slate-400">
                <th className="py-3 px-4 font-medium">能力维度</th>
                <th className="py-3 px-4 font-medium">飞书 (Feishu Wiki)</th>
                <th className="py-3 px-4 font-medium text-sky-400">Zotero (Pyzotero v3)</th>
                <th className="py-3 px-4 font-medium text-emerald-400">Notion (Database API)</th>
                <th className="py-3 px-4 font-medium text-amber-400">Obsidian (Cloud Git Vault)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/70 text-slate-300">
              <tr>
                <td className="py-3 px-4 font-medium text-white">v1.x 原始状态</td>
                <td className="py-3 px-4 text-emerald-400">读写闭环 (116KB 硬编码)</td>
                <td className="py-3 px-4 text-amber-400">仅只读拉取历史标题</td>
                <td className="py-3 px-4 text-amber-400">仅只读拉取页面标题</td>
                <td className="py-3 px-4 text-pink-400">仅本地路径只读 (云端失效)</td>
              </tr>
              <tr>
                <td className="py-3 px-4 font-medium text-white">控制台读取 (Console)</td>
                <td className="py-3 px-4">Wiki 节点 Todo 与二级标题</td>
                <td className="py-3 px-4">置顶 Standalone Note 解析</td>
                <td className="py-3 px-4">Questions DB 状态列查询</td>
                <td className="py-3 px-4">`00-Inbox/Console.md` Frontmatter</td>
              </tr>
              <tr>
                <td className="py-3 px-4 font-medium text-white">四色原位高亮载体</td>
                <td className="py-3 px-4">Docx `text_run` 背景色枚举</td>
                <td className="py-3 px-4">{'HTML Child Note `<span style>`'}</td>
                <td className="py-3 px-4">RichText `annotations.color` + Callout</td>
                <td className="py-3 px-4">{'`<mark>` 标签 + `> [!failure]` Callout'}</td>
              </tr>
              <tr>
                <td className="py-3 px-4 font-medium text-white">按需触发全文精读</td>
                <td className="py-3 px-4">勾选 `[x]` 候选论文 Todo</td>
                <td className="py-3 px-4">打上 `#deep-read` 标签或星标</td>
                <td className="py-3 px-4">勾选 `Deep Read` Checkbox 属性</td>
                <td className="py-3 px-4">勾选 `- [x] #ingest` 并 Git Push</td>
              </tr>
              <tr>
                <td className="py-3 px-4 font-medium text-white">基线双向回链 (Backlink)</td>
                <td className="py-3 px-4">Wiki 节点链接 + 底部追加块</td>
                <td className="py-3 px-4">`dc:relation` 关联 + `zotero://` 链接</td>
                <td className="py-3 px-4">双向 `Relation` 属性 + 页面 Mention</td>
                <td className="py-3 px-4">原生 `[[WikiLink]]` + 底部对比表</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* Selected Ecosystem Deep Dive */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left 5 cols: Adapter Architecture & Lifecycle */}
        <div className="lg:col-span-5 border border-slate-800 bg-[#111827] rounded-xl p-6 space-y-5">
          <div className="pb-4 border-b border-slate-800">
            <div className="text-xs font-mono text-sky-400 mb-1">{activeSpec.tagline}</div>
            <h3 className="text-xl font-semibold text-white">{activeSpec.name}</h3>
          </div>

          <div className="space-y-4 text-xs">
            <div className="p-3.5 rounded-lg bg-[#0B0F19] border border-slate-800 space-y-1">
              <div className="font-mono text-amber-400">1. 云端控制台同步机制 (fetch_console)</div>
              <p className="text-slate-300 leading-relaxed">{activeSpec.consoleMechanism}</p>
            </div>

            <div className="p-3.5 rounded-lg bg-[#0B0F19] border border-slate-800 space-y-1">
              <div className="font-mono text-emerald-400">2. 正文四色原位批注渲染 (compile_ast)</div>
              <p className="text-slate-300 leading-relaxed">{activeSpec.inlineAnnotationFormat}</p>
            </div>

            <div className="p-3.5 rounded-lg bg-[#0B0F19] border border-slate-800 space-y-1">
              <div className="font-mono text-sky-400">3. 勾选/打星按需精读闭环 (poll_user_actions)</div>
              <p className="text-slate-300 leading-relaxed">{activeSpec.ingestTriggerMechanism}</p>
            </div>

            <div className="p-3.5 rounded-lg bg-[#0B0F19] border border-slate-800 space-y-1">
              <div className="font-mono text-pink-400">4. 历史基线笔记反向追踪 (append_backlink)</div>
              <p className="text-slate-300 leading-relaxed">{activeSpec.backlinkMechanism}</p>
            </div>
          </div>

          {/* Required GitHub Secrets */}
          <div className="pt-4 border-t border-slate-800 space-y-2.5">
            <div className="text-xs font-semibold text-slate-200">
              所需的 GitHub Actions Secrets 凭据
            </div>
            <div className="space-y-2">
              {activeSpec.requiredSecrets.map((sec) => (
                <div
                  key={sec.key}
                  className="flex items-center justify-between text-xs p-2.5 rounded bg-[#0B0F19] border border-slate-800/80"
                >
                  <code className="text-sky-400 font-mono">{sec.key}</code>
                  <span className="text-slate-400">{sec.desc}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right 7 cols: Adapter Python Implementation & Native Payload Preview */}
        <div className="lg:col-span-7 space-y-6">
          {/* Python Adapter Code */}
          <div className="border border-slate-800 bg-[#111827] rounded-xl overflow-hidden">
            <div className="px-5 py-3.5 border-b border-slate-800 flex items-center justify-between bg-[#0B0F19]">
              <div className="flex items-center gap-2 text-xs font-mono text-emerald-400">
                <Layers className="w-4 h-4" />
                <span>v2.0 双向适配器核心实现 ({activeSpec.id}_adapter.py)</span>
              </div>
              <button
                onClick={() => handleCopy(activeSpec.pythonAdapterCode, `${activeSpec.id}-py`)}
                className="flex items-center gap-1.5 text-xs font-mono text-slate-400 hover:text-white transition-colors"
              >
                {copiedKey === `${activeSpec.id}-py` ? (
                  <>
                    <Check className="w-3.5 h-3.5 text-emerald-400" />
                    <span>已复制代码</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3.5 h-3.5" />
                    <span>复制适配器代码</span>
                  </>
                )}
              </button>
            </div>
            <pre className="p-5 text-xs font-mono text-slate-200 overflow-x-auto leading-relaxed">
              <code>{activeSpec.pythonAdapterCode}</code>
            </pre>
          </div>

          {/* Compiled Native Payload Preview */}
          <div className="border border-slate-800 bg-[#111827] rounded-xl overflow-hidden">
            <div className="px-5 py-3.5 border-b border-slate-800 flex items-center justify-between bg-[#0B0F19]">
              <div className="flex items-center gap-2 text-xs font-mono text-sky-400">
                <FileText className="w-4 h-4" />
                <span>编译后的终端原生数据结构预览 (Native Rich Payload / Note)</span>
              </div>
              <button
                onClick={() => handleCopy(activeSpec.payloadPreview, `${activeSpec.id}-payload`)}
                className="flex items-center gap-1.5 text-xs font-mono text-slate-400 hover:text-white transition-colors"
              >
                {copiedKey === `${activeSpec.id}-payload` ? (
                  <>
                    <Check className="w-3.5 h-3.5 text-emerald-400" />
                    <span>已复制</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3.5 h-3.5" />
                    <span>复制载荷示例</span>
                  </>
                )}
              </button>
            </div>
            <pre className="p-5 text-xs font-mono text-amber-200/90 overflow-x-auto leading-relaxed">
              <code>{activeSpec.payloadPreview}</code>
            </pre>
          </div>
        </div>
      </div>
    </div>
  );
};
