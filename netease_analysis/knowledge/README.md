# 知识库架构说明

## 🎯 设计理念

**配置与代码分离 + 可扩展**

- ✅ 所有知识存储在JSON文件（非Python代码）
- ✅ 非技术人员也能编辑知识
- ✅ 支持热更新（无需重启服务器）
- ✅ 向后兼容旧接口

---

## 📁 目录结构

```
knowledge/
├── __init__.py                      # 导出统一接口
├── knowledge_loader.py              # 加载器（单例模式+缓存）
├── platform_knowledge.py            # 兼容层（已废弃）
├── config/                          # 📦 JSON知识库
│   ├── platform_knowledge.json      # 平台知识
│   ├── cultural_context.json        # 文化背景
│   └── [future]_xxx.json            # 未来可扩展
└── README.md                        # 本文档
```

---

## 🔧 使用方式

### 1. 基础用法

```python
from netease_analysis.knowledge import get_platform_domain_knowledge

# 获取平台知识
knowledge = get_platform_domain_knowledge()
print(knowledge['platform'])  # "netease_cloud_music"
```

### 2. 高级用法

```python
from netease_analysis.knowledge import KnowledgeLoader

loader = KnowledgeLoader()

# 获取艺术家背景
artist_info = loader.get_artist_context("周杰伦")
print(artist_info['cultural_impact'])

# 获取网络用语定义
slang = loader.get_slang_definition("网抑云")
print(slang['definition'])

# 热更新知识（无需重启）
loader.reload_knowledge('cultural_context')
```

### 3. 向后兼容

```python
# 旧代码仍然有效
from netease_analysis.knowledge import get_platform_domain_knowledge
knowledge = get_platform_domain_knowledge()  # ✅ 正常工作
```

---

## 📝 如何扩展知识

### 方式1：编辑现有JSON文件

编辑 `config/cultural_context.json`，添加新艺术家：

```json
{
  "artist_backgrounds": {
    "artists": {
      "你的新艺术家": {
        "era": "2020s",
        "fan_base": "00后",
        "cultural_impact": "...",
        "representative_songs": ["歌1", "歌2"]
      }
    }
  }
}
```

保存后调用 `loader.reload_knowledge('cultural_context')` 即可生效。

### 方式2：新增知识类型

1. 创建新JSON文件：`config/my_new_knowledge.json`
2. 添加加载方法到 `knowledge_loader.py`：

```python
def get_my_new_knowledge(self) -> Dict[str, Any]:
    return self.load_knowledge('my_new_knowledge')
```

3. 在 `__init__.py` 中导出：

```python
from .knowledge_loader import get_my_new_knowledge
__all__ = [..., 'get_my_new_knowledge']
```

---

## 🔍 现有知识库内容

### platform_knowledge.json
- 平台特征
- 评论数分布统计（百分位数）
- 时间跨度模式
- 文化现象知识
- 采样考虑因素

### cultural_context.json
- 平台黑话/网络用语（网抑云、emo等）
- 艺术家背景知识（周杰伦、陈奕迅等）
- 歌曲年代标记（1980s-now）
- 评论区文化模式

---

## ⚡ 性能优化

- **缓存机制**：首次加载后缓存在内存
- **单例模式**：全局只有一个加载器实例
- **按需加载**：只加载需要的知识类型

---

## 🎓 设计哲学

```
❌ 旧版：硬编码在Python代码中
if "周杰伦" in artist_name:
    return {"status": "华语乐坛天王"}  # 难以维护

✅ 新版：JSON配置文件
{
  "周杰伦": {
    "status": "华语乐坛天王"
  }
}
```

**优势：**
1. 数据与逻辑分离
2. 非程序员可编辑
3. 易于版本控制
4. 支持多语言（未来可i18n）

---

## 🚀 未来扩展方向

- [ ] 情感词典（positive/negative keywords）
- [ ] 音乐流派知识
- [ ] 地域文化差异（如粤语歌文化）
- [ ] 时代事件关联（如疫情期间的歌曲）
