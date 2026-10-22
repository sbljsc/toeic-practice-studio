# Markdown 题库存储格式（v2）

本文档定义 TOEIC Practice Studio 的题目存储格式。目标是让题目以**明文可读、
可手工编辑、可按组导入导出**的文件形式存在，同时保持现有 HTTP API 契约不变。

## 1. 目录结构

```
content/question-pool/
  manifest.json                    # 资产登记表 + 版本 + 校验和
  pool.json                        # 旧格式快照，仅供生成器与往返比对使用
  parts/
    part-1/
      g-04e92fcdf5be1747d409.md     # 单题组：一个 md 文件
      g-04e92fcdf5be1747d409.srt    # 同名兄弟文件：逐句字幕（仅听力组）
    part-3/
      g-00ea73de7ccc7aed4f34.md    # 多题组：一个 md 文件（组内多题同屏）
      g-00ea73de7ccc7aed4f34.srt   # 同名兄弟文件：逐句字幕（仅听力组）
  assets/
    img-a49bfeeb88d2ed80014f.png   # 共享图片池（按内容哈希命名，可被多组引用）
  audio/
    audio-04e92fcdf5be1747d409.flac # 录音原件，按资产 id 命名
```

规则：

- **一个题组 = 一个 md 文件**，可选同名 `.flac` / `.srt` 兄弟文件。
- 同 basename 的文件属于同一题组，导入导出按 basename 成组处理。
- 图片是**共享池**，放在 `assets/`，由 md frontmatter 按 asset id 引用，
  不随组复制。
- 每个 Part 一个子目录 `parts/part-N/`。
- 录音放在 `audio/` 下按资产 id 命名，md 的 frontmatter 只登记资产 id，
  因此复制一个题组目录不会重复占用几十兆的音频。

## 2. md 文件结构

```markdown
---
group_id: g-04cef8991f3d486e23c2
part: 7
section: reading
passage_type: single
audio_asset: null
subtitles: null
explanation_verbatim: true
questions:
  - id: q-b90e6164990c88a0e479
    index: 1
  - id: q-3f1c2d4e5a6b7c8d9e0f
    index: 2
---

## 原文

##### Material 1

共享材料或图片。Part 1 的图片题写成 `![题目图片](/api/assets/img-xxx)`；
Part 3/4 的材料用 `##### Material K`，Part 7 用 `##### Passage K`。
图片若带有文字说明（地图方位、图表数据），紧跟其后写 `###### 图片文字`
 与正文，读回时作为该图片材料的 `text`。

##### Passage 1

Harold Rimes [10:11 A.M.]
Great news, everyone. The owner of the building at 465 Washington Avenue
agreed to rent the space to us.

##### Passage 2

...

## 选项

##### 第 1 题

What are the writers mainly discussing?

- A. The success of their coffee shop
- B. The comments by an inspector
- C. The contract they need to sign
- D. The plans for a new business

##### 第 2 题

...

## 答案 / 题解

### 第 1 题

**答案：D**

这些作者主要在讨论什么？

- A. 他们的咖啡店的成功
- B.  检查员提出的意见
- C. 他们需要签署的合同
- D. 他们开展新业务的计划

解析：（原文10:13提到……）
```

### 2.1 frontmatter 字段

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `group_id` | 是 | 全局唯一题组 ID，`g-` + 20 位 hex |
| `part` | 是 | 1–7 |
| `section` | 是 | `listening`（Part 1–4）/ `reading`（Part 5–7） |
| `passage_type` | Part 7 必填 | `single` / `double` / `triple` |
| `audio_asset` | 听力组必填 | 录音资产 id，如 `audio-04e92fcdf5be1747d409`，否则 `null` |
| `subtitles` | 听力组可选 | 同 basename 的 `.srt` 文件名，或 `null` |
| `explanation_verbatim` | 是 | 题解正文按教材原文原样保留 |
| `questions` | 是 | 组内题目列表，按显示顺序 |
| `blanks` | Part 6 必填 | 逻辑空位到题目的映射，见 §4 |

### 2.2 三个章节

固定三章，标题文字固定为 `## 原文`、`## 选项`、`## 答案 / 题解`：

- **原文**：题组共享的材料。Part 1 的图片题用 `![题目图片](/api/assets/img-xxx.png)`
  单行引用；Part 3/4/7 的长文本材料按排版后的段落写入；Part 6 的填空题材料
  使用 `{{blank:N}}` 逻辑空位标记（见 §4）。听力组另有两个固定小节：
  `##### Transcript`（英文原文）与 `##### Transcript (zh)`（中文对照）；
  教材复盘文本写在 `##### Review`。
- **选项**：每个子标题 `##### 第 N 题` 下的题干与选项列表（`- A. …`）。
  题干为空时（Part 6）只写选项。
- **答案 / 题解**：每个子标题 `##### 第 N 题` 下的 `**答案：X**`、
  中文题干/选项与解析文字。

文件自身的结构标记一律用 `#####` 或更深，**比任何材料内标题都深**，
因此材料内部的标题可以**保持原级别不变**（`##` 仍是 `##`），读回时不需要
任何还原，也不存在把内容标题误认成结构标记的可能。加载器按标记的**确切
文字**（`Material N`、`Passage N`、`第 N 题`）切分，而不是只按级别。

`##### 第 N 题` 中的 N 是**组内序号**（1 起），与 frontmatter `questions[].index`
一致；`questions[].id` 是**全局题 ID**，两者共同确定一道题。

### 2.3 Part 7 多 passage

Part 7 一个题组含 1–5 段材料。`## 原文` 下每个材料用 `##### Passage K`
分隔（K 从 1 起，按题库中的材料顺序）；`## 选项` 与 `## 答案 / 题解` 的
`##### 第 N 题` 按题目顺序排列，题号即组内序号。

`passage_type` 记录的是题组题型（`single` / `double` / `triple`），**不是**
passage 数量；材料段数由 `##### Passage K` 的实际条数决定。

## 3. 听力组

听力组（Part 1–4）除 md 外还有：

- `audio/<audio_asset>.flac`：整段录音，16 kHz / 单声道 / 16 bit。
- `<group_id>.srt`：逐句字幕。SRT 序号从 1 起，时间为**该段内相对时间**，
  格式：

  ```
  1
  00:00:00,200 --> 00:00:02,610
  M: Do you know why Ms. Sato called a meeting for 11?

  2
  00:00:02,610 --> 00:00:05,100
  W: She was, but she delayed her trip a couple of days.
  ```

  一句可以跨多行（换行用 `\n` 连接）；中文字幕不进 SRT，另存于
  md 的 `##### Transcript (zh)` 之后由前端按需显示。

逐句字幕必须与 `##### Transcript` 的英文原文**逐句对应**：加载器会按与
`valid_sentences` 相同的规则切分原文并校验时间轴，任何一句对不上，
整个题库都不可用。

## 4. Part 6 逻辑空位

Part 6 材料的空位在 md 中写作 `{{blank:N}}`，N 是**该 passage 内的空位序号**
（从 1 起），不含任何具体题号。组卷时后端把当前轮次的题号填回：

```
{{blank:1}}  ->  (38)
```

因此同一份 md 在任何一轮组卷中都能正确显示题号。

## 5. 导入导出

- **导出（按组）**：把一个题组的 md + 同名 `.flac` / `.srt` + 其引用的
  图片（若图片不在共享池中）打包成一个目录。
- **导入（按组）**：读取上述目录，分配**新 ID** 以避免与已有题库冲突：
  - 新组 ID：`g-` + `sha256(来源组ID + ":" + 来源md内容)[:20]`
  - 新题 ID：`q-` + `sha256(来源题ID + ":" + 新组ID)[:20]`
  - 图片资产：`img-` + `sha256(图片字节)[:20]`（内容寻址，天然去重）
- 导入后组内题目顺序、答案、选项文本、音频与字幕必须**逐字节等价**。
- 导入前先用题库自己的读取器校验这份 md，题库读不了就直接拒绝，
  不写入任何文件。
- 录音与字幕随组改名（`新组ID.srt`），新资产登记回 `manifest.json`。
- 因为新组 ID 由内容推导，同一份包再次导入会被识别为「已导入」，
  不会产生第二份，也不会报冲突。

## 6. 与旧格式的关系

`content/question-pool/pool.json` 与排版索引、图片转录表是 v1 的产物。
v2 用 md 取代它们：

- `pool.json` → `parts/part-N/*.md`
- 排版索引（2.9 MB 的全文索引，原 `apps/web/src/domain/textLayouts.ts`）→
  直接内联进 md 的 `## 原文`；索引本身**移到 `tools/bank-source/textLayouts.json.ts`**，
  只作为生成器的输入，不再随网页发布
- 图片转录表（原 `apps/web/src/domain/materialTranscripts.ts`）→ 内联进 md 的
  `###### 图片文字` 段；该表与当前题库的图片资产**无交集**，已停用并移到
  `tools/bank-source/` 作为历史留存
- `manifest.json` 保留，资产登记与 sha256 校验不变

`manifest.json` 的 `schema_version` 改为 `3` 时，后端按 md 题库加载；
`pool.json` 仍然保留，作为生成器的输入和往返比对的基准。

**前端不再携带这两张表。** 排版已在生成阶段固化进 md，
`parseMaterialMarkdown` 不再查表；图片文字说明由 md 直接提供。
因此网页产物从约 2.8 MB 降到约 380 KB，且渲染结果逐字节不变。

## 7. 生成与校验

- `tools/build_md_pool.py` 从 `pool.json` 与 `tools/bank-source/textLayouts.json.ts` 生成 md 树。
  它不修改任何题目内容、答案、选项、题组成员、录音或字幕。
- `tools/test_build_md_pool.py` 与 `tests/api/test_md_pool.py` 覆盖格式、
  往返一致性和失败场景。
- 往返校验：把 md 树加载回题库后，与 `pool.json` 的 2000 题 / 1030 组
  **逐字段比对**。允许的差异只有排版层面——标题标记、软换行与汉字间空格；
  文字本身必须逐字相同。

