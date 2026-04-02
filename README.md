# 🎵 NetEase Music Comments Analysis

<div align="center">

![Version](https://img.shields.io/badge/version-0.9.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.8+-blue.svg)

**让 Claude 1分钟读懂几十万条网易云评论**

[快速开始](#-快速开始) • [技术亮点](#-核心技术亮点)

</div>

---

> **传统方式：** 手动翻200万条评论？需要几天时间
> **使用本工具：** 60秒采样 + AI分析，直接看到核心洞察

---

## ✨ 为什么选择这个工具？

| 对比维度 | 传统方式 | 本工具 |
|---------|---------|--------|
| **速度** | 手动翻几小时 ⏱️ | 60秒自动分析 ⚡ |
| **覆盖** | 只能看热评 📌 | 热评+最新+历史（20年跨度）📊 |
| **深度** | 主观印象 💭 | 六维度量化分析 📈 |
| **可信度** | 无法验证 ❓ | 透明采样+原文引用 ✅ |

---

## 🚀 核心技术亮点

### 1️⃣ 智能分层采样
- **挑战**：200万条评论，AI无法全部处理
- **方案**：60秒采样 600-1000 条代表性评论
- **策略**：热评(15) + 最新(175) + 历史(410)，三维度覆盖
- **创新**：发现并利用 API 的 cursor 参数，突破 offset 限制，实现跨年份时间跳转

### 2️⃣ 六维度深度分析
不只是情感分析，而是全方位理解评论区：

| 维度 | 分析内容 | 置信度 |
|-----|---------|--------|
| 😊 **情感维度** | 正面/负面/中性分布 | 0.5-0.7 |
| 💬 **内容维度** | TF-IDF 关键词 + 出现率（doc_ratio） | 0.7 |
| ⏰ **时间维度** | 评论区活跃度和氛围随时间的变化 | 0.7 |
| 📏 **结构维度** | 长评/短评分布特征 | 0.9 |
| 👥 **社交维度** | 点赞集中度（基尼系数） | 0.85 |
| 🗣️ **语言维度** | 玩梗/故事/乐评类型分类 | 0.6 |

### 3️⃣ 算法盲区纠偏
- **问题**：SnowNLP 情感分析对"感伤式金句"误判为负面
  - 例如："我失去了最好的朋友，这首歌是我们的回忆"
- **方案**：提供对比样本（高赞低分评论），让 AI 阅读原文自行判断
- **结果**：AI 可以发现并纠正算法误判

### 4️⃣ 白盒设计理念
- ✅ 透明告知采样数量、覆盖率、时间范围
- ✅ 明确标注每个维度的置信度和局限性
- ✅ 提供原始评论样本，AI 可以验证
- ✅ 工具提供证据，不下结论 - 让 AI 自己判断

---

## 📦 快速开始

### 前置要求
- Python 3.8+

### 1. 安装

```bash
git clone https://github.com/1mht/netease-music-comments-analysis.git
cd netease-music-comments-analysis
pip install -e .
```

### 2. 安装 Skill

```bash
# macOS / Linux
cp -r skills/netease-music-comments-analysis ~/.claude/skills/

# Windows (PowerShell)
Copy-Item -Recurse skills\netease-music-comments-analysis $env:USERPROFILE\.claude\skills\
```

### 3. 验证

```bash
ncm-analysis --version
# → analysis, version 0.9.0
```

完成！在 Claude Code 中直接说"帮我分析《晴天》的评论区"，Claude 会自动触发 Skill 完成完整流程。

### 手动 CLI 用法

```bash
ncm-analysis search "晴天"
ncm-analysis select <session_id> 1
ncm-analysis add <song_id>
ncm-analysis sample <song_id> --level standard
ncm-analysis overview <song_id>
ncm-analysis signals <song_id>
ncm-analysis samples <song_id>
ncm-analysis search-comments <song_id> "青春" --limit 30
ncm-analysis raw <song_id> --year 2020 --min-likes 100
```

---

## 🛠 技术栈

- **NLP 处理**: jieba 分词 + SnowNLP 情感分析
- **数据存储**: SQLite
- **API 逆向**: 网易云音乐 weapi
- **CLI**: Click

---

## 🗂 代码结构

```
netease_analysis/        # 核心分析逻辑
├── tools/
│   ├── search.py            # 搜索 + session 管理
│   ├── data_collection.py   # 入库（元数据/热评/最新评论）
│   ├── sampling.py          # 三级采样（quick/standard/deep）
│   ├── pagination_sampling.py  # offset + cursor 分页采样
│   ├── layered_analysis.py  # 五层分析入口（Layer 0-3）
│   ├── dimension_analyzers.py  # 六维度算法实现
│   ├── comprehensive_analysis.py  # Layer 3 原始评论查询
│   ├── sample_selector.py   # 验证样本选取策略
│   ├── cross_dimension.py   # 跨维度关联分析
│   ├── data_transparency.py # 数据透明度报告
│   └── workflow_errors.py   # 错误类型定义
├── schemas/             # 数据结构定义
└── knowledge/           # 平台知识库（文化背景/触发规则）

netease_cloud_music/     # 网易云 API 层
analysis_cli/            # CLI 入口（Click）
skills/                  # Skill 定义文件
```

### 分析流程

```
search → select → add → sample
                           ↓
          Layer 0: 数据边界（评论量/覆盖率/时间跨度）
          Layer 1: 六维度信号（情感/内容/时间/结构/社交/语言）
          Layer 2: 验证样本（锚点样本 + 对比样本）
          Layer 2.5: 关键词检索（DB 内验证）
          Layer 3: 原始评论（按年份/点赞数筛选）
```

**设计原则**：工具提供数据和样本，ai负责判断且每层透明标注置信度和局限性。

---