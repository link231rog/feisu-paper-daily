# {{ title }}

> 今日精选 {{ papers|length }} 篇前沿学术文献，附研究问题进展与多模态架构解析。

{% if question_briefs %}
## ❓ 今日问题进展
{% for brief in question_briefs %}
### {{ loop.index }}. {{ brief.question }}
- **核心进展**：{{ brief.summary }}
- **收敛状态**：`{{ brief.status }}`
{% if brief.counter_evidence %}- **反例依据**：{{ brief.counter_evidence }}{% endif %}
{% if brief.gap %}- **待验证缺口**：{{ brief.gap }}{% endif %}

{% endfor %}
{% endif %}

{% if trending_items %}
## ⚡ AI 动态与开源热点
{% for item in trending_items %}
### [{{ item.title }}]({{ item.url }})
{{ item.summary }}

{% endfor %}
{% endif %}

## 📚 今日推荐论文
{% for paper in papers %}
### {{ loop.index }}. [{{ paper.tier_badge }}] {{ paper.title }}
- **作者**：{{ paper.authors_str }}
- **原文链接**：[{{ paper.url }}]({{ paper.url }})
{% if paper.code_url %}- **开源代码**：[{{ paper.code_url }}]({{ paper.code_url }}){% endif %}
{% if paper.project_url %}- **项目主页**：[{{ paper.project_url }}]({{ paper.project_url }}){% endif %}

{% if paper.poster_cid %}
![方法架构与核心流程图](cid:{{ paper.poster_cid }})
*▲ 方法架构与核心流程图 (Framework / Pipeline Overview)*
{% endif %}

{% if paper.has_digest %}
> **[审稿评级]**：**{{ paper.review_badge }}** *(复用度: {{ paper.r_grade }} | 证据支撑: {{ paper.s_grade }} | 基线公平: {{ paper.f_grade }})*
{% if paper.rubric_summary %}> **[四维评分]**：{{ paper.rubric_summary }}{% endif %}
> - **核心增量 (Delta)**：{{ paper.delta }}
> - **方法链路 (Mechanism)**：`{{ paper.pipeline }}`
{% if paper.core_formula and paper.core_formula != 'N/A' and paper.core_formula != 'N/A (需查正文)' %}> - **核心公式**：`{{ paper.core_formula }}`{% endif %}
{% if paper.symbol_dict and paper.symbol_dict != 'N/A' and paper.symbol_dict != 'N/A (需查正文)' %}> - **符号释义**：{{ paper.symbol_dict }}{% endif %}
> - **实验真相 (Truth & Cost)**：{{ paper.truth_metrics }}
{% if paper.truth_costs %}> - **代价与边界**：{{ paper.truth_costs }}{% endif %}
> - **启发与待查**：{{ paper.action_or_check }}
{% else %}
- **核心摘要**：{{ paper.tldr }}
{% if paper.judge_reason %}- **推荐理由**：{{ paper.judge_reason }}{% endif %}
{% endif %}

{% if paper.annotated_markdown %}
{{ paper.annotated_markdown }}
{% endif %}

---
{% endfor %}

> 由 Feishu Paper Daily 自动生成，请核验论文原文。
