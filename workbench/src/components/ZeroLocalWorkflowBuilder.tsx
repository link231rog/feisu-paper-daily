import React, { useState } from 'react';
import {
  WorkflowBuilderConfig,
  generateGitHubWorkflowYaml,
  REFACTORED_PYTHON_BUNDLE,
} from '../data/workflowTemplates';
import { Copy, Check, Download, GitBranch, Terminal, ShieldCheck, Zap } from 'lucide-react';

export const ZeroLocalWorkflowBuilder: React.FC = () => {
  const [config, setConfig] = useState<WorkflowBuilderConfig>({
    ecosystems: {
      feishu: true,
      zotero: true,
      notion: false,
      obsidian: true,
    },
    stateBackend: 'orphan_branch',
    fullTextMode: 'ar5iv_html_targeted',
    enableAdversarialQueries: true,
    enableInlineAiThreads: true,
    onDemandWebhookTrigger: true,
    schedulePreset: 'three_times_daily',
  });

  const [activeOutputTab, setActiveOutputTab] = useState<'yaml' | 'python_bundle' | 'webhook_guide'>('yaml');
  const [copied, setCopied] = useState(false);

  const generatedYaml = generateGitHubWorkflowYaml(config);

  const toggleEcosystem = (key: keyof WorkflowBuilderConfig['ecosystems']) => {
    setConfig((prev) => ({
      ...prev,
      ecosystems: {
        ...prev.ecosystems,
        [key]: !prev.ecosystems[key],
      },
    }));
  };

  const handleCopyContent = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  const handleDownloadFile = (filename: string, content: string) => {
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  const webhookDispatchSnippet = `# 任意端触发 GitHub Actions 单篇立即精读或 @AI 追问解答 (curl / 飞书自动化 Webhook / Notion Webhook)
curl -X POST \\
  -H "Accept: application/vnd.github+json" \\
  -H "Authorization: Bearer <YOUR_GITHUB_PAT>" \\
  https://api.github.com/repos/<USERNAME>/feisu-paper-daily/dispatches \\
  -d '{
    "event_type": "inline_ai_followup",
    "client_payload": {
      "arxiv_id": "2610.14892",
      "sink": "obsidian",
      "question": "它的 16-bit Centroid 质心签名开销多大？"
    }
  }'`;

  return (
    <div className="space-y-8">
      {/* Architecture Banner */}
      <div className="border border-slate-800 bg-[#111827] rounded-xl p-6 space-y-5">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4 pb-5 border-b border-slate-800">
          <div>
            <div className="text-xs text-sky-400 font-mono mb-1">
              100% 云端自治 · Orphan 独立状态分支 (`state-store`) + 按需 `repository_dispatch`
            </div>
            <h2 className="text-2xl font-semibold text-white tracking-tight">
              05. 纯 GitHub Actions 零本地依赖工作流定制器
            </h2>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => handleDownloadFile('paper-daily-v2.yml', generatedYaml)}
              className="px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-white text-xs font-medium rounded-lg transition-colors flex items-center gap-1.5 whitespace-nowrap shrink-0"
            >
              <Download className="w-3.5 h-3.5 text-sky-400" />
              <span>下载 paper-daily-v2.yml</span>
            </button>
            <button
              onClick={() => handleDownloadFile('paper_daily_v2_core.py', REFACTORED_PYTHON_BUNDLE)}
              className="px-3.5 py-2 bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold text-xs rounded-lg transition-colors flex items-center gap-1.5 whitespace-nowrap shrink-0"
            >
              <Download className="w-3.5 h-3.5" />
              <span>下载 v2.0 Python 核心升级包</span>
            </button>
          </div>
        </div>

        {/* 3 Core Serverless Pillars */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
          <div className="p-4 rounded-lg bg-[#0B0F19] border border-slate-800 space-y-1.5">
            <div className="flex items-center gap-2 font-mono text-emerald-400 font-semibold">
              <GitBranch className="w-4 h-4" />
              <span>1. 主分支零提交污染 (Orphan Worktree)</span>
            </div>
            <p className="text-slate-300 leading-relaxed">
              利用 `git worktree add .state state-store` 将 `paper_store.json` 与 `research_state.json`
              挂载在独立 Orphan 分支，既修复了原项目 `contents: read` 导致的状态蒸发，又保证 `main` 分支永远干净、本地 `git pull` 零冲突。
            </p>
          </div>

          <div className="p-4 rounded-lg bg-[#0B0F19] border border-slate-800 space-y-1.5">
            <div className="flex items-center gap-2 font-mono text-sky-400 font-semibold">
              <Zap className="w-4 h-4" />
              <span>2. 远端全托管控制台 (Zero-Local Config)</span>
            </div>
            <p className="text-slate-300 leading-relaxed">
              日常修改关注问题、确认 AI 提议的子问题、勾选精读文献、发起 `@AI` 追问全部在飞书/Notion/Zotero/Obsidian
              客户端内完成，本地无需安装 Python 环境或维护定时脚本。
            </p>
          </div>

          <div className="p-4 rounded-lg bg-[#0B0F19] border border-slate-800 space-y-1.5">
            <div className="flex items-center gap-2 font-mono text-amber-400 font-semibold">
              <ShieldCheck className="w-4 h-4" />
              <span>3. 秒级按需精读触发 (Dispatch + Cron)</span>
            </div>
            <p className="text-slate-300 leading-relaxed">
              除了每日 09:00 / 15:00 / 19:00 定时巡检外，支持通过 `repository_dispatch` 或手动输入 `target_arxiv_id`
              即时触发单篇 `ar5iv` 全文拉取与四色精读笔记生成。
            </p>
          </div>
        </div>
      </div>

      {/* Main Builder Split: Left Interactive Configurator + Right Live YAML/Python Output */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left 5 cols: Configuration Controls */}
        <div className="lg:col-span-5 border border-slate-800 bg-[#111827] rounded-xl p-6 space-y-6">
          <h3 className="text-base font-semibold text-white pb-3 border-b border-slate-800">
            工作流参数交互配置
          </h3>

          {/* 1. Target Ecosystems */}
          <div className="space-y-2.5">
            <label className="block text-xs font-medium text-slate-300">
              1. 启用双向同步的知识库生态（可多选）
            </label>
            <div className="grid grid-cols-2 gap-2.5">
              {(
                [
                  { id: 'feishu', label: '飞书 Wiki / Docx' },
                  { id: 'zotero', label: 'Zotero 文献库' },
                  { id: 'notion', label: 'Notion 数据库' },
                  { id: 'obsidian', label: 'Obsidian Git 仓库' },
                ] as const
              ).map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => toggleEcosystem(item.id)}
                  className={`px-3 py-2.5 rounded-lg border text-xs font-medium text-left flex items-center justify-between transition-colors ${
                    config.ecosystems[item.id]
                      ? 'bg-sky-500/15 border-sky-500/60 text-white'
                      : 'bg-[#0B0F19] border-slate-800 text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <span>{item.label}</span>
                  <span className="font-mono text-[11px]">
                    {config.ecosystems[item.id] ? 'ON' : 'OFF'}
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* 2. State Persistence Strategy */}
          <div className="space-y-2.5">
            <label className="block text-xs font-medium text-slate-300">
              2. 无服务器状态持久化引擎 (`paper_store.json` & `research_state.json`)
            </label>
            <div className="space-y-2">
              <button
                type="button"
                onClick={() => setConfig({ ...config, stateBackend: 'orphan_branch' })}
                className={`w-full p-3 rounded-lg border text-left text-xs transition-colors ${
                  config.stateBackend === 'orphan_branch'
                    ? 'bg-emerald-500/15 border-emerald-500/60 text-white'
                    : 'bg-[#0B0F19] border-slate-800 text-slate-400'
                }`}
              >
                <div className="font-semibold text-emerald-400 font-mono">
                  (推荐) Orphan 独立分支 `state-store` (Git Worktree 挂载)
                </div>
                <div className="text-slate-300 mt-1">
                  永久保存且版本可追溯，完全不污染 `main` 分支 commit 历史。
                </div>
              </button>

              <button
                type="button"
                onClick={() => setConfig({ ...config, stateBackend: 'actions_cache_hybrid' })}
                className={`w-full p-3 rounded-lg border text-left text-xs transition-colors ${
                  config.stateBackend === 'actions_cache_hybrid'
                    ? 'bg-emerald-500/15 border-emerald-500/60 text-white'
                    : 'bg-[#0B0F19] border-slate-800 text-slate-400'
                }`}
              >
                <div className="font-semibold font-mono">
                  GitHub Actions Cache (`actions/cache@v4`)
                </div>
                <div className="text-slate-400 mt-1">
                  完全不产生任何分支 Git Commit，适合高频运行（注意 7 天未运行会自动过期）。
                </div>
              </button>
            </div>
          </div>

          {/* 3. AI Capabilities Toggles */}
          <div className="space-y-2.5">
            <label className="block text-xs font-medium text-slate-300">
              3. AI 主动追踪与全文靶向解析策略
            </label>
            <div className="space-y-2 text-xs">
              <label className="flex items-center justify-between p-3 rounded-lg bg-[#0B0F19] border border-slate-800 cursor-pointer">
                <span>启用对抗性反例检索 (`ADVERSARIAL_COUNTER_QUERY`)</span>
                <input
                  type="checkbox"
                  checked={config.enableAdversarialQueries}
                  onChange={(e) =>
                    setConfig({ ...config, enableAdversarialQueries: e.target.checked })
                  }
                  className="accent-sky-500"
                />
              </label>
              <label className="flex items-center justify-between p-3 rounded-lg bg-[#0B0F19] border border-slate-800 cursor-pointer">
                <span>启用文档内 `@AI` 异步追问扫描与原位解答</span>
                <input
                  type="checkbox"
                  checked={config.enableInlineAiThreads}
                  onChange={(e) =>
                    setConfig({ ...config, enableInlineAiThreads: e.target.checked })
                  }
                  className="accent-sky-500"
                />
              </label>
              <label className="flex items-center justify-between p-3 rounded-lg bg-[#0B0F19] border border-slate-800 cursor-pointer">
                <span>启用 `repository_dispatch` 跨端打星/勾选即时触发</span>
                <input
                  type="checkbox"
                  checked={config.onDemandWebhookTrigger}
                  onChange={(e) =>
                    setConfig({ ...config, onDemandWebhookTrigger: e.target.checked })
                  }
                  className="accent-sky-500"
                />
              </label>
            </div>
          </div>

          {/* 4. Cron Schedule Preset */}
          <div className="space-y-2">
            <label className="block text-xs font-medium text-slate-300">
              4. 定时巡检频率 (Cron Schedule)
            </label>
            <select
              value={config.schedulePreset}
              onChange={(e) =>
                setConfig({ ...config, schedulePreset: e.target.value as any })
              }
              className="w-full bg-[#0B0F19] border border-slate-800 rounded-lg px-3 py-2 text-xs text-white font-mono focus:outline-none focus:border-sky-500"
            >
              <option value="three_times_daily">
                每日 3 次 (09:00 全量推荐 + 15:00 & 19:00 勾选精读/@AI 巡检)
              </option>
              <option value="morning_and_evening">
                每日 2 次 (09:00 全量推荐 + 19:00 勾选精读/@AI 巡检)
              </option>
              <option value="morning_only">每日 1 次 (09:00 全流程合并执行)</option>
            </select>
          </div>
        </div>

        {/* Right 7 cols: Generated Code Output */}
        <div className="lg:col-span-7 border border-slate-800 bg-[#111827] rounded-xl overflow-hidden flex flex-col">
          <div className="px-5 py-3 border-b border-slate-800 bg-[#0B0F19] flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-1 p-1 bg-[#111827] border border-slate-800 rounded-lg">
              <button
                onClick={() => setActiveOutputTab('yaml')}
                className={`px-3 py-1 text-xs font-mono rounded transition-colors whitespace-nowrap shrink-0 ${
                  activeOutputTab === 'yaml'
                    ? 'bg-slate-800 text-sky-400'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                .github/workflows/main.yml
              </button>
              <button
                onClick={() => setActiveOutputTab('python_bundle')}
                className={`px-3 py-1 text-xs font-mono rounded transition-colors whitespace-nowrap shrink-0 ${
                  activeOutputTab === 'python_bundle'
                    ? 'bg-slate-800 text-emerald-400'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                paper_daily_v2_core.py
              </button>
              <button
                onClick={() => setActiveOutputTab('webhook_guide')}
                className={`px-3 py-1 text-xs font-mono rounded transition-colors whitespace-nowrap shrink-0 ${
                  activeOutputTab === 'webhook_guide'
                    ? 'bg-slate-800 text-amber-400'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                Webhook 按需触发指令
              </button>
            </div>

            <button
              onClick={() =>
                handleCopyContent(
                  activeOutputTab === 'yaml'
                    ? generatedYaml
                    : activeOutputTab === 'python_bundle'
                    ? REFACTORED_PYTHON_BUNDLE
                    : webhookDispatchSnippet
                )
              }
              className="flex items-center gap-1.5 text-xs font-mono text-slate-300 hover:text-white transition-colors"
            >
              {copied ? (
                <>
                  <Check className="w-3.5 h-3.5 text-emerald-400" />
                  <span className="text-emerald-400">已复制到剪贴板</span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5" />
                  <span>复制当前代码</span>
                </>
              )}
            </button>
          </div>

          <pre className="p-5 text-xs font-mono text-slate-200 overflow-x-auto max-h-[680px] leading-relaxed">
            <code>
              {activeOutputTab === 'yaml'
                ? generatedYaml
                : activeOutputTab === 'python_bundle'
                ? REFACTORED_PYTHON_BUNDLE
                : webhookDispatchSnippet}
            </code>
          </pre>
        </div>
      </div>
    </div>
  );
};
