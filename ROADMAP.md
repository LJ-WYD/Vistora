# Vistora 原始优化路线（唯一权威定义）

原始 O 编号不可因技术拆分、实现顺序或协调层批次而更改。工程内部如需拆分，只能使用 `BATCH-*`，不得把内部批次称为 STEP 或 O，也不得重编号、压缩或扩写原始任务。本文的 O1–O32 定义来自用户提供的两张原始清单截图转录，是路线含义的唯一权威来源。

Definitions digest: `sha256:143850f88a50bf6b43137723cff42c4f1f9132b2a12cceda369c659db5c5d618`

定义文字只能在有 `change_request`、变更理由和用户明确批准记录时修改。普通实现提交只能更新 [roadmap-status.json](roadmap-status.json) 的状态、提交和验证证据，不能修改下列原文。

## 权威原文

- O1 读取并梳理现有项目结构、导演 Agent、剪辑 Agent、时间线、原子工具、前端和渲染链路。
- O2 固化现有导演方案、时间线项目文件、剪辑执行计划和原子工具的输入输出格式，并补充版本字段。
- O3 为现有主流程建立回归样例：素材分析 → 导演方案 → 用户确认 → 剪辑执行 → 导出验证。
- O4 在不修改现有执行逻辑的前提下，新增只读时间线数据接口。
- O5 新增时间线可视化窗口：视频轨、音频轨、字幕轨、片段、时间码、播放头和素材预览。
- O6 新增缩略图、音频波形和片段详情展示。
- O7 建立“导演方案条目 ↔ 时间线片段 ↔ 原始素材证据”的双向定位。
- O8 新增方案差异预览：展示导演方案将新增、删除、裁剪、移动、变速和处理哪些片段。
- O9 新增方案版本、用户确认状态、执行记录和回退记录。
- O10 建立原子化剪辑能力注册表，并统一每项能力的参数校验、预览、执行、撤销和测试接口。
- O11 补齐基础剪辑原子能力：分割、裁剪、删除、移动、排序、多轨、静音、音量、淡入淡出、变速、倒放、冻结帧。
- O12 补齐基础画面原子能力：缩放、位置、旋转、裁切、不透明度、画幅适配和多规格导出。
- O13 补齐字幕与文字能力：字幕轨、词级时间、文字样式、标题、图片和贴纸。
- O14 补齐基础音频能力：背景音乐、音效、音量包络、自动闪避和响度标准化。
- O15 补齐基础调色与画面包装能力：亮度、对比度、饱和度、色温、曲线、LUT、模糊、锐化、发光、阴影、圆角和混合模式。
- O16 补齐转场、关键帧、蒙版、羽化、反转蒙版和蒙版关键帧能力。
- O17 让导演 Agent 按新增能力生成结构化、参数化的剪辑方案；让剪辑 Agent 增加对应能力与参数校验。
- O18 新增时间线受控微调：用户的手动调整统一转换为原子操作，并保存为用户修订方案。
- O19 新增创作委托入口：导演 Agent 先对话澄清需求，维护创作简报，并判断何时进入正式规划。
- O20 新增导演 Agent 的素材状态判断：素材齐全、素材不完整、完全无素材。
- O21 新增无素材模式下的“素材需求方案”：由导演 Agent 输出所需镜头、旁白、音乐、图形、特效、来源、优先级和替代方案。
- O22 新增创作规划 Agent：将素材需求方案细化为分镜、资产任务、生成规格、参考要求、提示词策略和验收标准。
- O23 新增素材生产 Agent：执行 AI 图片、AI 视频、AI 配音、AI 音乐、素材检索、录制任务和用户补素材请求。
- O24 将新生成或收集的素材统一入库、代理、转码、分析、打标签和质检。
- O25 素材完成后，自动回到现有导演 Agent，由它基于真实素材输出最终剪辑方案。
- O26 新增“缺素材反馈循环”：剪辑或审阅时发现素材不足，返回导演 Agent 生成补素材需求，再回到创作规划与生产流程。
- O27 建立云端 AI 包装任务模型：镜头、时间段、对象、遮罩、跟踪、风格参考、提示词、模型、参数和验收标准。
- O28 先接入高价值 AI 包装能力：背景替换、对象移除、局部重绘、风格化、补帧、生成式转场、生成式 B-roll、AI 配音、音乐和音效。
- O29 将 AI 生成结果作为标准视频片段、透明图层或效果层回填到统一时间线。
- O30 新增 AI 生成任务的候选版本、成本、进度、失败重试、局部重做、替换、回退和缓存。
- O31 新增成片自动质检：时长、画幅、编码、音轨、黑帧、静帧、响度、字幕和完整解码检查。
- O32 完成多规格输出、项目版本比较、品牌风格包、用户偏好和完整交付流程。

## 首次能力审计矩阵

机器可读的完整提交、实现路径、测试证据和剩余范围见 [roadmap-status.json](roadmap-status.json)。本表只给出首次治理基线的人工可读结论；`complete` 必须同时具备远程提交、实现路径和测试证据。

| 原始项 | 状态 | 已有主要证据 | 尚缺内容 |
| --- | --- | --- | --- |
| O1 | complete | `4748261`；`ARCHITECTURE.md`；架构边界测试 | 无 |
| O2 | complete | `a18ed15`；versioned contracts；contract tests | 无 |
| O3 | complete | `8564094`；deterministic reference workflow | 无 |
| O4 | complete | `9dcc93d`；timeline snapshot service/tests | 无 |
| O5 | complete | `d133444`、`a16d060`；timeline/subtitle browser tests | 无 |
| O6 | complete | `7f43954`；thumbnail/waveform/inspector tests | 无 |
| O7 | complete | `83ded7d`；trace/query tests | 无 |
| O8 | complete | `78c9fa0`；detached plan-review tests | 无 |
| O9 | complete | `94105aa`；workflow/rollback tests | 无 |
| O10 | complete | `9a93653`；registry/gateway/CLI tests | 无 |
| O11 | complete | `eba5bdb`、`a0a4f75`、`5c9b73e`、`352ebf3`；timeline edit/render/reference tests | 无 |
| O12 | complete | `80a460e`、`d93bdee`；visual/multi-spec export/reference tests | 无 |
| O13 | partial | `a16d060` | 词级时间、标题、图片、贴纸仍缺 |
| O14 | partial | `5c9b73e` | 背景音乐/音效的专用语义与自动闪避仍缺 |
| O15 | partial | `80a460e`、`d160892` | 曲线、LUT、发光、阴影、圆角、可渲染混合模式仍缺 |
| O16 | complete | `5d9a5a7`、`b1f75d2`、`d160892`；transition/automation/mask tests | 无（自动跟踪属于后续能力，不是本项原文） |
| O17 | complete | `d281fcd`、`24e4a87`、`9a93653`；Director/EditingAgent tests | 无 |
| O18 | complete | `d133444`、`83ded7d`、`eba5bdb`；manual-edit/provenance tests | 无 |
| O19 | complete | `24e4a87`、`1a17f6e`；Director/product-entry tests | 无 |
| O20 | partial | `24e4a87`、`759afcc` | “素材不完整”需成为明确、可审计状态并进入产品流程 |
| O21 | complete | `759afcc`；material-requirements tests | 无 |
| O22 | complete | `222645d`；creation-planning tests | 无 |
| O23 | partial | `acdab74`；provider-neutral production tests | AI 图片/视频/配音/音乐、检索、录制和补素材请求的明确能力编排仍不完整；默认仍无真实 provider |
| O24 | partial | `acdab74`；staging/catalog/media validation tests | 代理、转码、分析、标签和统一质检链仍不完整 |
| O25 | complete | `acdab74`；no-material-to-Director reference workflow | 无 |
| O26 | missing | 无 | 缺素材检测、回到 Director、再规划/生产的闭环 |
| O27 | missing | 无 | 云端 AI 包装意图/任务/验收模型 |
| O28 | missing | 无 | 列出的高价值 AI 包装能力编排；默认不得虚报真实 provider |
| O29 | missing | 无 | 标准 clip/透明 layer/effect layer 回填边界 |
| O30 | missing | 无 | 候选、成本、进度、重试、局部重做、替换、回退、缓存 |
| O31 | missing | 无 | 成片自动质检报告与定位 |
| O32 | missing | 无 | 多规格交付、项目版本比较、品牌包、偏好和完整交付 |

## 执行门

1. 开始功能工作前，把目标 O 项设为唯一 `in_progress`；不得跳过更早的 `partial`/`missing`，除非 `roadmap-status.json` 有绑定该目标、理由和用户明确批准记录的豁免。
2. 完成一项时先完成完整验证、独立实现提交、推送和远程 SHA 核对，再用单独状态更新记录远程提交和验证证据；仍缺任一原文子能力只能保持 `partial`。
3. 每次汇报固定使用：`原始 O编号 + 原始任务名 + 当前状态 + 本次补齐内容 + commit SHA + 验证 + 尚缺内容 + 下一原始 O编号`。
4. 最终 O32 只有在状态文件无 `in_progress`/`missing` 时才可宣告路线结束。任何 `partial` 必须有用户明确接受为 V1 限制的记录。

验证命令：

```powershell
python scripts/validate_roadmap.py
python -m pytest -q tests/test_roadmap_governance.py
```
