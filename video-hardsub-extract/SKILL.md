---
name: video-hardsub-extract
display_name: 视频画面字幕提取
display_name_en: Video Hard-Subtitle OCR
description: 按时间逐条提取视频画面文字，分开标注底部字幕与其他位置的文字、字框和可确认的样式；导出时间线文字稿 TXT 和字幕 SRT。支持本地视频、可访问链接，以及 D 盘本地批量资料库的保存、查阅、导出与删除。
description_zh: 按时间逐条提取视频画面文字，分开标注底部字幕与其他位置的文字、字框和可确认的样式；导出时间线文字稿 TXT 和字幕 SRT。支持本地视频、可访问链接，以及 D 盘本地批量资料库的保存、查阅、导出与删除。
description_en: Extract burned-in video subtitles as full TXT and timed SRT. Supports local videos, accessible share links, region previews and caching, plus a local batch library to save, browse, export and delete managed videos and results. Reads pixels, not audio.
version: 0.2.0-rc9
author: 超哥
examples_zh:
  - "提取这条视频的全部画面文字，按时间逐条展示，区分底部字幕与其他位置，导出 TXT 和 SRT"
  - "提取我上传的视频字幕，使用当前专属工作目录，先预览确认字幕区域"
  - "帮我在 D 盘创建本地字幕工具，能批量导入视频，保存、查看、导出和删除结果"
examples_en:
  - "Extract burned-in subtitles from D:/videos/demo.mp4 into SRT, workspace D:/work/hardsub, preview the subtitle band first"
  - "Run a dependency self-check, then OCR these subtitles and tell me where the SRT is"
  - "Re-run the same extraction and report whether the cached result was reused"
---

# 视频画面字幕提取

读取画面文字，输出按时间和位置逐条排列的完整文字稿与 SRT。首次安装看 [安装与依赖](references/install.md)；环境就绪直接运行，避免重复安装、自检、加载模型和另写计时报告。

## 两种使用方式

用户只说“使用视频字幕工具”时，简短提供两个选择：

1. **直接提取**：在 WorkBuddy 发视频或可访问链接，由 WorkBuddy 调用代码和工具识别，在对话展示按时间排列的全文并提供 TXT、SRT。
2. **安装本地软件**：从本项目已核实的 GitHub 固定版本安装本地工具，以后双击打开，批量导入、识别、保存、查看、导出和按需删除。

用户已发视频并要求提取时直接走第一种；明确说安装、本地软件或批量资料库时走第二种，不重复询问。两种方式共用本包的 PaddleOCR 识别核心与时间线格式。“大模型跑”在这里指 WorkBuddy 调用代码执行；不得宣称由纯大模型视觉完成识别。无需另接付费 API。

第二种先读 [固定版本安装](references/github-install.md)，使用 NeoElbert/video-hardsub-extract 的固定发布及外部 SHA256 清单，验证后安装；如资产不可用须停止并说明，不虚报安装成功。

## 日常调用

1. 在用户选定工作目录内，用该目录的 `tools/hardsub-venv/Scripts/python.exe`（其他系统为 `bin/python`）运行 `scripts/job.py <视频或链接> --workspace <目录> --roi 0,0,1,1`。需要识别底部之外的文字时必须全画面，不能沿用旧底部裁剪。已自检的显卡环境可用 `tools/hardsub-gpu-venv/Scripts/python.exe` 和 `--device gpu:0`。
2. 程序一次完成下载、识别、样式候选、计时及时间线输出。每条显示开始/结束时间、原文字、区域、位置和字框信息；相同文字在不同位置独立保留，文字变化另起一条。**不要合成段落，不要删掉时间和位置，也不必再次调用模型排版。**
3. 直接把完整时间线和返回的 TXT/SRT 链接交给用户。JSON、日志、缓存报告留后台。默认 SRT 保留全部已识别画面文字及其时间轴，位置和样式解释在 TXT 中。

示意（Bash）：
```bash
"$PY" "$SKILL/scripts/job.py" "$VIDEO" --workspace "$WORKSPACE" --roi 0,0,1,1
```

运行前把 shell 的 TEMP/TMP/TMPDIR 与任务用户目录设在该工作目录的 tools/temp、tools/user；脚本再配置全部工具缓存。由技能管理的文件写入工作目录，宿主程序启动脚本之前的自身临时文件不由本技能控制。

## 保真与交付

- 继续使用 server 模型、3 fps；默认 CPU，已通过实际自检的 NVIDIA 环境可用显卡 Python 运行并传入 `--device gpu:0`。不为加快响应而降低模型/采样率、裁短视频或丢弃句子。闪现字幕可按需要提高采样或逐帧。所有原有高级选项继续通过 job.py 转交给识别入口。
- ROI 为 `x0,y0,x1,y1` 比例。新视频区域未知时先用 `hardsub.py <视频> --workspace <目录> --preview` 看不同时间点；已确认范围直接运行。默认底部范围不是所有视频都适用。可选建议区域、颜色过滤和精校详见 [高级使用](references/advanced.md)。
- 时间线仅合并相邻帧中同位置、完全相同的文字，文字变化、数字变化、不同位置和空白后的再次出现均分开记录；不把逐字动画改写成猜测的完整句子。SRT/逐帧证据保持原始识别结果。
- 字体家族、字重、描边和实际字号未通过视觉核对时写“未确认”。字框像素高度不是字体字号；边缘主色含描边和背景，不冒充确定字色。位置分类是几何候选，不能仅因处于底部就断言它是口述字幕。详见 [时间线输出](references/timeline.md)。
- 默认在对话直接展示**按时间逐条排列的全文**，标明自动稿未精校；最后仅提供文字稿 TXT 与字幕 SRT。JSON、日志、哈希和测试报告留后台。遇平台实际长度限制可分条展示，不自行截断。
- 程序计时不包含模型思考和聊天回复等待；不能当成用户收到全文的时间。复用缓存要明确告知。重跑验收用 `--refresh`，不得拿旧结果冒充新识别。

## 生成用户本地工具

用户希望以后不经过聊天直接导入视频时，用同一个 venv 运行：

```bash
"$PY" "$SKILL/scripts/install_local.py" --workspace "$WORKSPACE"
```

安装后提供实际返回的 `local-tool/打开字幕工具.cmd`。用户双击 → 导入多个视频或文件夹 → 确认识别范围 → 提取所选/全部待处理。界面显示进度、耗时和完整时间线文字稿；每个视频自动保存副本与 TXT/SRT，关闭后再打开仍可查看。支持名称搜索、全选当前列表、批量导出、选择连视频一起导出、批量删除和完成当前后暂停。失败视频保留供重试，队列继续处理其余视频。详见 [批量资料库](references/library.md)。

首次新建工具默认 `D:/视频字幕工具`；已有用户指定的 D 盘专属工作目录时优先复用，不另建重复工具。`setup.py` 和 `install_local.py` 省略 workspace 使用上述默认目录；Windows 禁止把工具和资料库安装到系统盘，D 盘不存在时让用户选择其他数据盘，不回退 C 盘。先设置命令进程的 TEMP/TMP/TMPDIR 与用户目录到选定目录再运行。浏览器下载目录及宿主自身记录不由技能控制，不承诺完全零 C 盘写入。

新导入视频默认全画面识别。字幕位置不同的视频分别预览设置范围，避免统一裁切漏字。批量任务依次执行，沿用 server 模型、3 fps，可选 CPU 或已自检的显卡，每项保存独立结果，共享模型文件。已安装模型后，本地视频识别不需聊天模型或上传视频。首次下载模型需要网络。导出仅提供 TXT/SRT（可选视频），JSON 留后台。删除操作有明确确认，仅删除资料库管理的副本、结果和该记录缓存，不删除导入前原文件、已导出文件或共享模型。

本地自动稿按观察到的文字变化逐条记录，不再默认生成大段文章。这不等于视觉纠错或语义校对；全画面会包含标题、角色名和装饰文字，花体/竖排/手写小字需复核。旧阅读排版功能保留供明确要求时使用，不覆盖新时间线。首次创建工具先确认当前 venv 能导入 tkinter；Windows 是已验证目标，其他系统需单独适配启动入口。

## 按需参考

- [安装与依赖](references/install.md)：第一次配置或依赖报错才读。
- [可选显卡加速](references/gpu.md)：本地 Windows NVIDIA 电脑处理较慢时，独立配置并实际识别自检，通过后启用；保留原模型和采样参数。
- [高级使用](references/advanced.md)、[参数用法](references/usage.md)：缓存、ROI、参数、原帧校对、重排和目录结构。
- [平台验证与限制](references/limits.md)：链接下载与字幕准确度分别判断。不保证五平台任意链接都可下载；失败即如实说明，不冒用其他视频。原 B 站样本漏段和 X 身份映射待核实记录保留。

未看原画面不能称已精校。没有画面字幕时不以音频或平台字幕冒充 OCR。此技能不自动发布市场。
