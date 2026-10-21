# 练习题来源核查与扩充指南

这份文档记录「还能去哪里找题」的核查结论，以及每条结论的原文证据。
目的不是替使用者找盗版教材，而是把**可以合法使用的来源**和
**不可以使用的来源**分开说清楚，让扩充题库这件事有据可依。

核查日期：2026-10-22。下文的「实测」数字都是当时抓取原文后统计的结果。

## 结论速览

1. **官方题目不能入库。** ETS 与 IIBC 的条款都明确排除再分发，
   只能做「外链跳转 + 手动播放」。
2. **可再分发的增量只有开放许可数据。** 目前经核实可用的是
   TOEIC 词汇库（CC BY 4.0 / CC BY-SA 4.0）。
3. **MIT 许可的题库要逐题筛。** 许可证覆盖代码，不自动覆盖题目内容；
   实测发现其中 336 题逐字取自 ESL Lounge，而该站条款禁止转载。
4. **本项目自带的 2000 题只能本地自用。** 仓库公开不等于取得授权。

## 一、官方来源：只能外链，不能入库

### IIBC 官方样题页（含音频）

- 页面：<https://www.iibc-global.org/toeic/toeic_program/sample_all.html>
- 分页：`sample01.html` ~ `sample04.html`（Part 1–4）、
  `sample05.html`、`sample06.html`、`sample07_01.html` ~ `sample07_04.html`（Part 5–7）
- 实测：Part 1–7 全覆盖，共 60 题；官方 MP3 直链可达。
- 页脚原文：

  > TOEIC Programのディレクション並びにサンプルテストの著作権は ETSに帰属しています。
  > この著作物をETSの許可なく無断で複製して使用することは法律で禁じられています。
  >
  > All copyrights to the TOEIC Program directions are owned by ETS.
  > The directions may not be reproduced in any form without the express written permission of ETS.

- 另一处实测：样题页只有「正解」，**没有文字解析**（`解説` 计数为 0）。

**结论**：可以做外链入口让用户自己去做，不要把题面或音频打包进本项目。

### ETS 官方 Sample Test PDF

- 地址：<https://www.ets.org/content/dam/ets-org/pdfs/toeic/toeic-listening-reading-sample-test.pdf>
- 实测：34 页，2.4 MB，第 3 页印
  `COPYRIGHT © 2016 BY EDUCATIONAL TESTING SERVICE. ALL RIGHTS RESERVED.`，
  第 4–21 页每页页脚印 `Unauthorized copying or reuse of this page is illegal.`
- 内容质量高（200 题 + 听力脚本 + 答案表），但**法律上不可复制进本项目**。

### ETS 许可政策

- <https://www.ets.org/legal/permissions/licensing.html>
- 实测：该页只有 GRE 的许可政策，未找到 TOEIC 专属许可路径。
  若要合法使用 ETS 题目，只能走 `permissions@ets.org` 申请。

### 其他官方入口（同样只做外链）

| 来源 | 地址 | 说明 |
| --- | --- | --- |
| 中国大陆官方站 | <https://www.test-toeic.cn/experience.aspx> | ETS 授权运营，样题体验 + 下载中心，条款与 ETS 全球一致 |
| 官方 YouTube | <https://www.youtube.com/user/TOEICjapan> | 2020 年官方 200 题模考视频，音频在视频流里 |
| 官方每周一练 | <https://www.iibc-global.org/toeic/support/exercise_pr.html> | 每周邮件一题填空，含答案与简析，需注册会员 |

## 二、开放许可数据：唯一可安全再分发的增量

### TOEIC 词汇库（CC BY 4.0 / CC BY-SA 4.0）

| 数据集 | 许可 | 词条 | 链接 |
| --- | --- | --- | --- |
| `LEE-WHITE/toeic-vocab-tw` | **CC BY 4.0** | 9,537 | <https://huggingface.co/datasets/LEE-WHITE/toeic-vocab-tw> |
| `kknono668/toeic-vocab-tw` | CC BY-SA 4.0 | 11,154 | <https://huggingface.co/datasets/kknono668/toeic-vocab-tw> |

两者内容同源，CC BY-SA 版本多出 `exam_tips` 逐词考点解析。

实测结构（`LEE-WHITE` 版本）：`metadata` + `vocabulary_by_importance`
（5 星到 1 星五档），每条含 `english_word`、`chinese_definition`、
`star_rating`、`category`、`parts_of_speech`、`word_forms`、`examples`。
`kknono668` 版本每条另含 `exam_tips`（常见搭配、易混词辨析、听读考点）。

许可原文关键句（CC BY 4.0）：

> You are free to: Share — copy and redistribute the material in any medium or format;
> Adapt — remix, transform, and build upon the material for any purpose, even commercially.
> Under the following terms: Attribution — You must give appropriate credit,
> provide a link to the license, and indicate if changes were made.

**注意**：CC BY-SA 4.0 有 ShareAlike 传染性。若并入本项目，该部分需按
CC BY-SA 4.0 发布并署名；**CC BY 4.0 版本没有这个问题**，对现有许可最干净。

**它能补什么、不能补什么**：能补「词义 + 例句 + 考点」这块，正好喂给
本项目的生词本；**不能**补听力音频、不能补模拟题、没有 part 标注
（只在 `exam_tips` 文字里点到 Part 2/5/6/7）。

## 三、MIT 题库：许可证覆盖代码，不自动覆盖题目

候选：`kdeppaei/toeic-question-ocean`（<https://github.com/kdeppaei/toeic-question-ocean>）

仓库是 MIT（Copyright (c) 2026 Chun-Hsiung Luo），许可原文允许再分发。
**但 MIT 只能覆盖作者有权许可的部分。**

### 实测统计

按该仓库 `index.html` 的真实加载顺序（31 个 `question-bank*.js` + 模块文件）
复原题库，得到 **1443 题**，与其自带校验器 `validate-bank.js` 的期望值一致：

| Part | 题数 | 有 passage | 有 audioText | 有解析 |
| --- | --- | --- | --- | --- |
| 1 | 25 | 0 | 25 | 25 |
| 2 | 109 | 0 | 109 | 109 |
| 3 | 90 | 0 | 90 | 90 |
| 4 | 78 | 0 | 78 | 78 |
| 5 | 448 | 0 | 0 | 448 |
| 6 | 240 | 240 | 0 | 240 |
| 7 | 453 | 453 | 0 | 453 |
| **合计** | **1443** | 693 | 302 | 1443 |

选项数：4 选 1 共 1334 题，3 选 1 共 109 题（**全部是 Part 2**）。
答案索引全部有效。

### 阻断项一：336 题逐字取自 ESL Lounge

这 336 题带 `sourceType: "user"`、`sourceUrl` 指向 `esl-lounge.com`，
由 `modules/part5-exercise-bank.js` 与 `modules/reading-exercise-bank.js`
直接 `push` 进题库。

ESL Lounge 版权声明原文（<https://www.esl-lounge.com/copyright.php>）：

> Information received through this website may be displayed, reformatted,
> and printed for your personal, noncommercial use only. You may not reproduce
> or retransmit the materials, in whole or in part, in any manner, without the
> prior written consent of esl-lounge.com …
> Reproduction of any or all of the pages on esl-lounge.com onto another web
> site not under the esl-lounge domain name is expressly forbidden.

实测逐字核对：`toeic-045-reading-part-five-1.php` 页面上
`The factory implemented ______ measures to reduce waste and improve overall
efficiency across all production lines.` 与该库题干逐字相同。

该仓库的 README 对 ESL Lounge 与第三方内容**零提及**，也没有上游授权证明。
这 336 题（Part 5/6/7 各占一部分）**不可用**。

### 阻断项二：即便剔除，结构也对不上

剔除后剩 **1107 题**（Part 1–7 = 25 / 109 / 90 / 78 / 328 / 120 / 357），
实测与本项目的 md 格式存在硬冲突：

| 冲突 | 说明 |
| --- | --- |
| 听力无音频 | 仓库里 **零个** `.flac/.mp3/.wav/.srt`。本项目 Part 1–4 强制要求录音登记与逐句字幕，302 题全部无法落地 |
| Part 6 结构相反 | 本项目要求**一段材料 4 个空位**（`blanks` + `{{blank:N}}`）；该库每题各带一份独立 passage，四题四段 |
| Part 7 缺 `passage_type` | 本项目强制 `single/double/triple`，且 double/triple 必须是 5 题。该库 8 个 5 题组各只有 1 段 passage，需拆组 |
| Part 2 是 3 选 1 | 本项目 Part 2 恰好也是 3 选 1，兼容 |
| Part 1 图片 | 该库用 `.jpg`，本项目要求 `assets/img-<20hex>.png` 并登记 sha256 |

### 与 ETS 真题的实际重叠：实测为 0

把该库与 **ETS 官方 Sample Test PDF 全文**做 n-gram 比对：

- 剔除非法题后，1107 题中与 ETS 样卷共享 **6 词以上连续片段**的有 12 题，
  但**逐条查看后全部是通用题干**，例如
  `What does the man ask the woman`、`the best response to the question`、
  `What is most likely true about`。
- **只看 passage 与选项**（剔除题干这一最可能撞车的字段）后，
  重合数 **0**。

结论：该库的原创部分**没有证据表明抄了 ETS 真题**。这是作者声明加本次
实测的共同结论，不等于逐题法律尽调。

### 与本项目现有 2000 题的重叠：实测为 0

1107 题的题干与本项目 md 题库共享 7 词以上片段的有 22 条，逐条查看同样
是通用题干（如 `What will the man do?`），**选项集合无一相同**，
内容层面无冲突。

## 四、本项目自带的 2000 题

来源是一套第三方托业教材，权利归出版方与作者。
仓库已移除品牌与来源标识，但这**不改变内容权利**：

- 仓库公开、允许克隆、可下载，都不代表维护者取得再分发许可。
- 免费、非营利、禁止商用声明也不免除内容权利要求。
- 因此题库随源码分发只是「便于个人自用」，使用者仍需在合法范围内使用。

详见 [内容权利说明](../CONTENT-NOTICE.md) 与 [使用条款](../LICENSE.md)。

## 五、已核查但判定不可用的来源

| 来源 | 原因 |
| --- | --- |
| `zbljli/toeic-mock-app` | README 明写「真实 TOEIC 题库接入」尚未完成；LICENSE 是 Expo 模板的 MIT，只覆盖作者代码 |
| `graykode/toeicbert` | 唯一 `test.json` 仅 3 题；README 称 7067 题集但未公开，且致谢他人收集的教材题 |
| `ninejubu/toeic-practice`、`AnhTuan2k1/Toeic`、`yukkes/toeic-dungeon` 等 | 许可证为 NONE / NOASSERTION，或只覆盖代码 |
| `SunggaP/toeic-speaking-simulator` | 许可证 NOASSERTION，无法识别，风险最高 |
| HuggingFace `dddodddiiddoddo/toeic`、`cuongtm/Toeic_hacker_vol3`、`messithanh2k/toeic` 等 | `cardData.license` 全为空；内容是教材扫描件/压缩包，无授权 |
| Kaggle 上的 TOEIC 数据集 | 未能打开 LICENSE 原文核实，按本项目标准不采纳 |
| 教育部 / 教育部考试中心公开的 TOEIC 模拟题 | moe.gov.cn 与 neea.edu.cn 可达，但**未检索到**官方发布的模拟题 |
| 来源不明的教材扫描件与盗版合集 | 明确排除 |

## 六、给使用者的实际建议

1. **想要官方题**：用上面第一节的链接，在官方页面自己做。
   本项目负责计时、统计、字幕高亮与生词归因，不复制官方内容。
2. **想要可再分发的增量**：用第二节的 CC BY 4.0 词汇库补生词本，
   保留署名与许可链接；不要用 CC BY-SA 版本，除非愿意让该部分按
   CC BY-SA 4.0 发布。
3. **想扩充模拟题**：用 `tools/group_transfer.py` 导入**自己合法取得**
   的题组（md 目录格式）。本项目只按题组 ID + 题 ID 重新分配编号来
   避免冲突，**不为来源内容做任何背书**。
4. **不要**把来源不明的题库整体塞进公开仓库——公开会放大权利风险，
   也会让本项目看起来为侵权内容背书。

## 附：核查方法

- 许可证一律打开原文抓取关键句，不依据仓库标签或二手介绍。
- 题库统计按各项目**真实的加载顺序**复原（该 MIT 仓库的
  `question-bank.js` 只是基座，其余文件是 `push` 追加）。
- 与 ETS 的重叠比对使用官方 Sample Test PDF 全文，转文本后做
  6/7/8 词 n-gram 交集，并区分「题干重合」与「passage/选项重合」。
- 未打开原文核实的来源一律标注为未核实，不列入可用。

