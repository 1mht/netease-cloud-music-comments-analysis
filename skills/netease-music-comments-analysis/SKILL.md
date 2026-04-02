---
name: netease-music-comments-analysis
description: >
  网易云音乐评论深度分析系统。触发时机（满足任意一条即激活）：
  用户提到"分析评论"、"评论区"、"网易云评论"、"歌曲评论分析"、"评论分布"、
  "听众反馈"、"分析听众"、"用户评价"、"评论趋势"时，使用此 skill。
  核心能力：歌曲搜索入库 → 评论采样 → 五层渐进式分析（概览/六维度信号/验证样本/关键词验证/原始评论）。
---

# 网易云音乐评论分析

## 检查安装

```bash
ncm-analysis --version
```

如果命令不存在，提示用户安装：

```
git clone <仓库地址>
cd netease-music-comments-analysis
pip install -e .
cp -r skills/netease-music-comments-analysis ~/.claude/skills/
```

---

## 工作流

### 第一步：搜索歌曲

```bash
ncm-analysis search "<歌曲名>"
```

返回 `session_id` 和 `choices` 列表。

**决策**：
- 将候选列表展示给用户，等待用户选择序号，**不能自行决定**
- 用户表示没有想要的结果时，取下一页：`ncm-analysis search "<歌曲名>" --offset 10`
- 搜索结果为空（`status: "no_results"`）时，建议用户简化关键词或只搜歌名

---

### 第二步：确认选择

```bash
ncm-analysis select <session_id> <序号>
```

返回 `song_id`，后续所有命令使用此 ID。

**决策**：直接进入第三步入库。

---

### 第三步：入库

```bash
ncm-analysis add <song_id>
```

收集元数据、热门评论（50条）、最新评论（20条）。

**决策**：入库完成后直接进入采样。

---

### 第四步：采样

```bash
ncm-analysis sample <song_id> --level standard
```

| 级别 | 评论数 | 耗时 |
|------|--------|------|
| quick | 200 | ~30s |
| standard | 600 | ~60s |
| deep | 1000 | ~2min |

**默认始终使用 `standard`**。

采样返回关键字段：

| 字段 | 含义 |
|------|------|
| `actual` | DB 中该歌曲评论总量（可用于分析）|
| `api_total` | API 真实总评论数 |
| `sample_rate` | 覆盖率（actual / api_total）|
| `coverage.years_span` | 歌曲年份跨度 |
| `coverage.years_sampled` | 本次实际覆盖年份数 |

**决策**（你来判断，不是机械阈值）：

- `actual < 200` → 数据太少，建议先看原因（冷门歌 / 采样失败）
- `api_total < 500`（冷门歌）→ 标记为**冷门歌模式**，分析框架切换：不看社交动力学，重点看真实听感（评论内容是否反映直接听感而非社交跟风）
- 用户目的是**时间趋势分析**，且 `sample_rate < 3%` 或 `years_sampled` 明显少于 `years_span` → 询问是否升级到 `deep`
- 用户只是**浏览评论风格 / 看热评** → `actual > 200` 即够，不主动提升级别
- `coverage.years_span <= 2`（新歌）→ 告知用户时间维度分析受限
- 用户主动要求更深入 → 使用 `--level deep`

---

### 第五步：分层分析

分层的核心原则：**每层都是对上一层发现的回应，不是固定流水线**。

---

#### Layer 0：数据概览

```bash
ncm-analysis overview <song_id>
```

**决策**：

- `status: "must_sample_first"` → 回到第四步重新采样
- `status: "success"` → 向用户说明数据边界，继续 Layer 1：
  - 告知 `db_count` / `api_total` / `coverage`（让用户知道结论的可信度）
  - `coverage_ratio < 0.01`（覆盖率 < 1%）→ 在最终报告中标注抽样偏差风险
  - `years_covered <= 1` → 告知时间维度分析受限
  - `year_distribution` 中某年份评论量远超其他年份（如近期评论堆积）→ 注意时间分布不均

---

#### Layer 1：六维度信号

```bash
ncm-analysis signals <song_id>
```

六个维度及置信度：

| 维度 | 内容 | 置信度 | 注意 |
|------|------|--------|------|
| sentiment | 情感分布 | 0.5–0.7 | 算法常误判叙事体/苦情体为负面 |
| content | TF-IDF 关键词 | 0.7 | 权重高 ≠ 高频，需 Layer 2.5 验证 |
| temporal | 按年趋势 | 0.7 | 年跨度 ≤ 2 时参考价值有限 |
| structural | 长度分布 | 0.9 | 若 `data_sufficiency.level: limited`，降低置信度 |
| social | 点赞集中度（基尼系数） | 0.85 | 基尼 > 0.6 = 精英控场，近期评论影响力极低 |
| linguistic | 评论类型 | 0.6 | Meme 占比高说明歌曲有强传播梗 |

**路由决策**（可多条同时触发，按优先级处理）：

| 发现 | 下一步 | 原因 |
|------|--------|------|
| `sentiment` 负面偏高或 cross_signal 出现高赞低分模式 | 优先进 Layer 2 读对比样本 | 验证是算法误判（叙事/玩梗）还是真实负面 |
| `content` 出现有意义关键词 | 进 Layer 2.5 验证频率 | TF-IDF 权重不代表实际高频 |
| `temporal` 有明显年份峰值 | 进 Layer 3 查该年评论 | 找峰值背后的事件/情绪原因 |
| 某维度 `data_sufficiency.level: limited` | 在报告中标注该维度结论可靠性低，不阻断流程 | |
| **无任何异常信号** | **跳过 Layer 2，直接写报告** | 快速路径，节省上下文 |
| 冷门歌模式（`api_total < 500`）| 进 Layer 2 看 anchors，重点读内容是否为真实听感，跳过 social/structural 维度结论 | 冷门歌无社交层叠，算法盲区检测意义不大 |

多条触发时：先 Layer 2 → 视情况 Layer 2.5 / Layer 3，**不要同时调用所有层**。

---

#### Layer 2：验证样本

```bash
ncm-analysis samples <song_id>
```

返回：
- **锚点样本**（不依赖算法）：最高赞、最早、最新、最长
- **对比样本**（发现算法盲区）：高赞但算法低分、低赞但长文

**决策**：

- 阅读原文，判断 Layer 1 中 `sentiment` 是否准确
- 若高赞评论明显正面但被判负面 → 以原文为准，在报告中标注算法误判
- `years_covered >= 3` → **主动输出时间线叙事**：早期评论是什么风格/话题 → 中期发生了什么变化 → 近期是什么状态（不要等用户问）
- 读完后判断是否可以写报告：
  - **可以终止** → 样本已足够支撑主要发现，写最终报告
  - **需要继续** → 样本出现无法解释的模式（如某年大量高赞评论风格突变）→ 进 Layer 3

---

#### Layer 2.5：关键词验证（按需）

当 Layer 1 的 `content` 出现有价值关键词，但不确定实际频率时使用：

```bash
ncm-analysis search-comments <song_id> "<关键词>" --limit 30
ncm-analysis search-comments <song_id> "<关键词>" --min-likes 100
```

返回 `match_total`：
- 极少（< 10）→ TF-IDF 权重高但并非真实主题，不要在报告中强调
- 较多 → 确认是真实高频主题，可作为核心发现

---

#### Layer 3：原始评论（按需）

当需要验证具体年份/点赞数范围的假设时使用：

```bash
ncm-analysis raw <song_id> --year <年份>
ncm-analysis raw <song_id> --year <年份> --min-likes 100 --limit 10
ncm-analysis raw <song_id> --min-likes 500
```

读完后可以写最终报告。**不要把 Layer 3 当成必经步骤**，只在有具体假设需要验证时才调用。

---

## 完整示例

```bash
ncm-analysis search "晴天"
# → 展示给用户选择

ncm-analysis select <session_id> 1
# → song_id: 185811

ncm-analysis add 185811
ncm-analysis sample 185811 --level standard
# → actual: 587, api_total: 12000, sample_rate: 4.89% → 继续

ncm-analysis overview 185811
# → db_count: 587, coverage: 4.89%, years_covered: 8 → 告知用户数据边界

ncm-analysis signals 185811
# → content 发现"青春"权重高，temporal 发现 2020 年峰值

ncm-analysis search-comments 185811 "青春" --limit 30
# → match_total: 87 → 确认真实高频

ncm-analysis samples 185811
# → 阅读对比样本，发现 sentiment 算法误判若干感伤评论

ncm-analysis raw 185811 --year 2020 --min-likes 100
# → 验证 2020 年峰值原因
```

---

## 最终报告结构

```
## 评论区人设
一句话定性：知识科普型 / 情感树洞型 / 玩梗社交型 / 乐评专业型 / 混合型
（根据 linguistic.type_distribution + content 关键词推断）

## 数据基础
- 样本：X 条 / API 总量 X 条（覆盖率 X%）
- 时间跨度：XXXX–XXXX（X 年）
- 局限性：[覆盖率<1% / structural 数据不足 / 新歌时间维度受限 等]

## 核心发现（2–4条）
每条：标题 + 引用原文（X 赞，日期）+ 解读

## 时间线演化（仅 years_covered >= 3 时输出）
早期 → 中期 → 近期，评论区氛围/话题发生了什么变化

## 算法误判（若有）
哪类评论被误判，实际情感是什么

## 局限性
```

---

## 设计原则

- **CLI 只返回数据**，所有工作流决策由本 Skill 定义，不依赖 CLI 输出中的引导文字
- **工具提供证据，你负责判断**：不要直接引用算法结论，要结合原文样本判断
- **渐进式**：按需深入，不要一次调用所有层
- **对比样本优先于算法分数**：Layer 2 中高赞评论的实际内容比 sentiment 分数更可信
