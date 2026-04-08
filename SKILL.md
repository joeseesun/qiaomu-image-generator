---
name: qiaomu-image-generator
description: Use when user requests image generation for articles, papers, covers, or social media. Triggers on "配图", "生成封面", "illustration", "小红书配图", "公众号封面", "X封面", or when other skills need images.
---

# 统一配图生成器

为文章、论文、小红书、公众号封面、X 封面等多场景生成配图。

## 核心设计

```
用户请求
    ↓
Claude（智能层）
    ├── 理解意图，选择场景模板
    ├── 处理覆盖指令（风格、比例等）
    └── 生成 visual_config.json
    ↓
执行脚本（执行层）
    ├── 加载风格模板
    ├── 多线程调用 API
    └── 保存图片并插入文章
    ↓
输出结果
```

**原则**：Claude 做决策，脚本做执行。JSON 是唯一契约。

---

## 场景模板

| 场景 | 模板名 | 默认风格 | 比例 | 像素 |
|------|--------|----------|------|------|
| 文章配图 | `article` | minimalist | 16:9 | 1920×1080 |
| 公众号封面 | `wechat_cover` | paper-watercolor-cover | 2.35:1 | 900×383 |
| 小红书 | `xiaohongshu` | colorful_sketch | 3:4 | 1242×1660 |
| X 封面 | `x_cover` | paper-watercolor-cover | 5:2 | 1500×600 |
| 论文配图 | `paper` | newyorker | 16:9 | 1920×1080 |

---

## 风格选择指南

共 **49 种风格**，每种风格都有 `use_cases` 字段标注适用场景。

### 按场景推荐

| 场景 | 推荐风格 |
|------|----------|
| 知识科普 | `minimalist`, `vintage-scientific`, `line-art`, `chalkboard` |
| 技术解析 | `vintage-scientific`, `isometric`, `low-poly`, `geometric-abstract` |
| 产品设计 | `flat-illustration`, `flat-simple`, `minimal-icon`, `soft-geometric` |
| 文艺创作 | `watercolor`, `ink-painting`, `morandi`, `soft-watercolor` |
| 轻松趣味 | `cartoon`, `children-book`, `paper-cut`, `newyorker` |
| 传统文化 | `ink-painting`, `woodcut`, `retro-poster`, `screen-print` |

### 常用风格速查

| 风格ID | 中文名 | 特点 | 适用场景 |
|--------|--------|------|----------|
| `minimalist` | 极简线条 | 单色/双色，减法美学 | 知识分享、思考类文章 |
| `newyorker` | 纽约客 | 黑白钢笔+朱红点缀 | 观点评论、文化分析 |
| `pen-sketch` | 钢笔速写 | 手绘松弛质感 | 叙事文章、旅行笔记 |
| `flat-illustration` | 平面插画 | 纯色填充，无阴影 | 产品推介、科技新闻 |
| `vintage-scientific` | 复古科学插图 | 老式教科书质感 | 科学原理、技术解析 |
| `morandi` | 莫兰迪色系 | 极低饱和度灰调 | 文艺评论、设计分享 |
| `children-book` | 儿童绘本 | 温暖柔和色彩 | 儿童科普、亲子教育 |
| `isometric` | 等距视图 | 30度角斜视，立体感 | 技术架构、产品设计 |

**完整风格列表**：见 `config/styles.json`，每种风格包含：
- `name`: 中文名
- `description`: 简短描述
- `prompt`: 风格前缀
- `suffix`: 风格后缀
- `use_cases`: 适用场景数组（供 AI 参考选择）

---

## 封面生成（标准化流程）

**所有内容创作都应生成封面图**，工作流程：

```
读取文章
    ↓
提炼核心关键词（1-3个关键词概括主题）
    ↓
选择封面风格（默认 paper-watercolor-cover）
    ↓
生成 visual_config.json（cover 节点）
    ↓
调用生图脚本
    ↓
插入文章开头（作为 cover image）
```

### 封面配置格式

```json
{
  "cover": {
    "enabled": true,
    "filename": "cover.png",
    "style": "paper-watercolor-cover",
    "aspect_ratio": "16:9",
    "description": "关键词1 关键词2 关键词3",
    "retry_count": 2
  }
}
```

### 关键词提炼原则

- 从文章主题中提取 1-3 个核心概念
- 避免过长，控制在 20 字以内
- 示例：`Qwen3-TTS 语音合成 3秒克隆`

### 封面风格推荐

| 场景 | 推荐风格 |
|------|----------|
| 公众号/X 封面 | `paper-watercolor-cover`（默认） |
| 论文解读封面 | `paper-watercolor-cover` |
| 技术文章封面 | `vintage-scientific` |
| 轻松话题封面 | `newyorker` |

---

## 工作流程

### Step 1: 分析文章/需求

读取文章，识别：
- 场景类型（文章配图/封面/小红书等）
- H2 章节数量
- 用户的覆盖指令（如"用水彩风格"）

### Step 2: 创建输出目录

```bash
# 文章配图
mkdir -p "{文章目录}/{文章名}.assets"

# 封面类
mkdir -p "{输出目录}"
```

### Step 3: 生成 visual_config.json

**配置格式**：

```json
{
  "task_id": "article_20260120_143052",
  "template": "article",
  "source": "/path/to/article.md",
  "output_dir": "/path/to/article.assets/",

  "cover": {
    "enabled": false,
    "style": "colorful_sketch",
    "aspect_ratio": "2.35:1",
    "description": "视觉描述...",
    "retry_count": 2
  },

  "illustrations": [
    {
      "index": 1,
      "h2_title": "章节标题",
      "style": "minimalist",
      "aspect_ratio": "16:9",
      "description": "视觉描述..."
    }
  ],

  "defaults": {
    "style": "minimalist",
    "aspect_ratio": "16:9",
    "provider": "jimeng",
    "retry_count": 2
  }
}
```

### Step 4: 调用生成脚本

```bash
python ~/.claude/skills/qiaomu-image-generator/scripts/generate.py \
  /path/to/visual_config.json \
  --workers 3
```

**参数说明**：
- `--workers 3`: 并发线程数（默认 3）
- `--dry-run`: 只打印不执行
- `--no-insert`: 不自动插入到 Markdown
- `--output result.json`: 输出结果到文件

---

## 风格模板编写规范

**核心原则**：风格模板只定义**如何渲染**，不定义**渲染什么**。

### 设计哲学

```
用户输入 = 主体内容（description）
风格模板 = 渲染方式（prompt + suffix）

最终提示词 = prompt + description + suffix
```

**职责分离**：
- **description（主体词）**：描述具体内容（人物、场景、物体、动作）
- **prompt/suffix（风格词）**：定义风格特征（材质、色彩、笔触、构图）

### ✅ 风格模板应该包含

**1. 材质质感**
- 磨砂玻璃、纸张、胶片颗粒、水彩晕染
- 丝网印刷、木刻纹理、半调网点

**2. 色彩处理**
- 红橙渐变、莫兰迪灰调、高饱和度纯色
- 冷暖对比、单色调、有限色板

**3. 笔触技法**
- 精致线条、交叉线纹理、素描笔触
- 色块拼接、剪影轮廓、模糊颗粒

**4. 构图方式**
- 极简留白、拼贴层次、对称/非对称
- 中心/边缘、动态/静态、前景/背景关系

**5. 光影处理**
- 边缘光、通透光、柔和光影
- 高对比、渐变过渡、明暗表现方式

**6. 艺术风格**
- Moebius、Matisse、波普艺术、野兽派
- 工笔重彩、丝网印刷、数字艺术

### ❌ 风格模板不应包含

**1. 具体人物**
- ❌ "重金属摇滚电吉他手"
- ❌ "飘逸长发、戴墨镜"
- ❌ "人物轮廓"

**2. 具体场景**
- ❌ "上海外滩场景"
- ❌ "山水意境"
- ❌ "热带森林"

**3. 具体物体**
- ❌ "植物花朵"、"每片叶子"
- ❌ "家具、小物件"
- ❌ "街景路牌和建筑碎片"

**4. 具体元素**
- ❌ "英文字母和单词"
- ❌ "蘑菇"、"松树"

### 示例对比

#### ❌ 错误示例（混入具体内容）

```json
{
  "prompt": "工笔重彩绘画风格，植物花朵的纹理细腻，热带植物和蘑菇森林...",
  "suffix": "每片叶子每朵花都有独特纹理，奇幻森林秘境..."
}
```

**问题**：指定了"植物"、"蘑菇"、"森林"等具体内容，限制了风格的通用性。

#### ✅ 正确示例（只有风格特征）

```json
{
  "prompt": "工笔重彩绘画风格，每一根线条都极其精致入微，纹理细腻到极致...",
  "suffix": "极繁主义的细节密度，每个元素都有独特纹理，奇幻秘境的浪漫感..."
}
```

**优点**：只定义渲染方式，可以应用到任何主体（人物、建筑、动物、抽象概念）。

### 测试方法

创建风格后，用不同的 description 测试：

```
同一个风格 + 不同主体 = 都应该合理

例如 "minimalist-dreamy-blur" 风格：
- description: "一只猫" → 应该生成朦胧模糊的猫
- description: "城市建筑" → 应该生成朦胧模糊的建筑
- description: "抽象情绪" → 应该生成朦胧模糊的抽象形态
```

如果某个 description 搭配风格后感觉奇怪，说明风格模板可能混入了具体内容。

### 常见错误

1. **从用户描述中提取具体元素加入风格**
   - 用户说："电吉他手" → 不要把"电吉他"写进风格
   - 只提取风格特征："半调网点"、"剪影"、"高对比"

2. **用场景来定义风格**
   - ❌ "上海外滩场景的磨砂玻璃风"
   - ✅ "磨砂玻璃材质 + 红橙渐变 + 极简构图"

3. **混淆风格与内容**
   - 风格："工笔重彩、精致线条"（可以画任何东西）
   - 内容："植物、蘑菇、森林"（具体画什么）

---

## visual_description 写作规范

**🎬 像导演拍默片一样思考**：
- 演员不能说话、没有字幕
- 用**纯视觉语言**传递信息

**🌏 必须使用中文**：
- 即梦 API 对中文理解更准确

**❌ 绝对禁止**：
1. **风格指令**：极简、水墨、油画、素描（风格由 style 字段控制）
2. **产品名/公司名**：OpenAI、Claude、DeepSeek
3. **版本号/型号**：2.0、3.5、V3
4. **数字参数**：78%、152层、200美元
5. **日期时间**：2025年、12月
6. **文字/符号**：不要有任何文字

**✅ 应该用**：
1. **空间关系**：中心 vs 边缘、顶部 vs 底部
2. **大小对比**：高塔 vs 低建筑、巨大 vs 渺小
3. **动态趋势**：向上攀登、向外扩散
4. **视觉隐喻**：塔楼（地位）、攀登（追赶）

**示例**：

| ❌ 错误 | ✅ 正确 |
|--------|--------|
| "OpenAI 的 logo 在中心" | "中心矗立一座最高的塔楼，四周快速升起多座新塔" |
| "极简线条风格的猫" | "一只橘色短毛猫坐在窗台上，阳光洒落" |

---

## 覆盖指令识别

Claude 应识别用户的自然语言指令并写入 JSON：

| 用户说 | 覆盖字段 |
|--------|----------|
| "用水彩风格" | `style: "watercolor"` |
| "竖版" / "3:4" | `aspect_ratio: "3:4"` |
| "用 Z-Image" / "用通义生图" | `provider: "z-image"` |
| "用即梦" | `provider: "jimeng"` |
| "封面要活泼一点" | `cover.style: "colorful_sketch"` |

**可用 Provider：**
| Provider | 说明 |
|----------|------|
| `jimeng` | 即梦 4.5（默认），高质量生图 |
| `z-image` | 阿里通义 Z-Image-Turbo，支持 LoRA |

---

## 完整示例

### 示例 1: 文章配图

用户：「为这篇文章配图 /path/to/article.md」

**Step 1**: 读取文章，发现 5 个 H2 章节

**Step 2**: 创建目录
```bash
mkdir -p /path/to/article.assets
```

**Step 3**: 生成配置
```json
{
  "task_id": "article_20260120_150000",
  "template": "article",
  "source": "/path/to/article.md",
  "output_dir": "/path/to/article.assets/",
  "illustrations": [
    {
      "index": 1,
      "h2_title": "用Claude写战略文档",
      "description": "一个人坐在书桌前，与一面大镜子对话，镜子里是不断演变的文档轮廓"
    },
    {
      "index": 2,
      "h2_title": "用Google AI Studio做原型",
      "description": "左边陶工快速塑形已完成，右边雕刻家还在缓慢雕琢"
    }
  ],
  "defaults": {
    "style": "minimalist",
    "aspect_ratio": "16:9",
    "retry_count": 2
  }
}
```

**Step 4**: 执行
```bash
python ~/.claude/skills/qiaomu-image-generator/scripts/generate.py \
  /path/to/article.assets/visual_config.json
```

### 示例 2: 小红书配图（覆盖风格）

用户：「为这篇文章生成小红书配图，用彩色简笔画风格」

**配置**：
```json
{
  "template": "xiaohongshu",
  "defaults": {
    "style": "colorful_sketch",
    "aspect_ratio": "3:4"
  }
}
```

### 示例 3: 公众号封面

用户：「生成公众号封面」

**配置**：
```json
{
  "template": "wechat_cover",
  "cover": {
    "enabled": true,
    "style": "colorful_sketch",
    "aspect_ratio": "2.35:1",
    "description": "一只猫站在书架顶端，俯瞰书房"
  }
}
```

---

## 完成后必须输出

**每次配图任务完成后，必须输出以下信息**：

```
✅ 配图完成！

📄 文章：/完整/路径/文章名.md
📁 资源：/完整/路径/文章名.assets/
🖼️ 配图：X 张
⏱️ 耗时：约 X 秒

生成的图片：
1. 01-章节名-极简.png
2. 02-章节名-极简.png
...
```

**关键**：必须输出完整绝对路径。

---

## 配置文件位置

```
~/.claude/skills/qiaomu-image-generator/
├── SKILL.md                 # 本文档
├── config/
│   ├── styles.json          # 风格模板（可编辑）
│   ├── templates.json       # 场景模板（可编辑）
│   └── providers.json       # API 配置
└── scripts/
    └── generate.py          # 执行脚本
```

**自定义风格**：编辑 `config/styles.json` 添加新风格
**自定义场景**：编辑 `config/templates.json` 添加新场景

---

## 故障排查

### 问题 1: 风格不对

**原因**：visual_description 中包含了风格词

**解决**：检查 description 是否有"极简"、"水墨"等词，删除

### 问题 2: 生成失败

**原因**：API 超时或配额用尽

**解决**：
- 检查 `~/.claude/skills/shared-lib/config.json` 中的凭据
- 尝试减少 `--workers` 数量
- 使用 `--dry-run` 检查配置

### 问题 3: 图片没插入文章

**原因**：h2_title 与文章中的 H2 不匹配

**解决**：确保 `h2_title` 完全匹配文章中的 H2 标题文本
