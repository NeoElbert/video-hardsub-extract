# 用法

## 1. 自检

```bash
<venv python> scripts/hardsub.py --check --workspace <workspace>
```

逐项打印 Python、cv2/numpy/Pillow/paddle/paddleocr、yt-dlp、FFmpeg、模型缓存、中文字体、工作目录可写、剩余空间、缓存条数。必需项缺失时退出码为 2，并说明缺哪个包；不会自动安装。

## 2. 预览并确定字幕区域

```bash
<venv python> scripts/hardsub.py <视频或链接> --workspace <workspace> --preview --suggest-roi
```

产出 `output/hardsub/<时间戳>_preview/preview.jpg`（6 个时间点，红框为当前 ROI），`--suggest-roi` 另存 `preview-suggested.jpg`（绿框为建议区域）并在 JSON 的 `suggested_roi` 给出建议值。建议值来自检测模型对若干帧文字行的聚类，仍需人眼确认。

预览分支的 `run.json` 状态是 `preview`，不会遗留 `running`。

## 3. 提取

```bash
<venv python> scripts/hardsub.py <视频或链接> --workspace <workspace> --roi 0,0.82,1,0.92
```

常用参数：

| 参数 | 说明 |
|---|---|
| `--roi x0,y0,x1,y1` | 字幕区域，画面宽高比例 |
| `--sample-fps` | 每秒识别帧数，默认 3；`0` 为逐帧 |
| `--mode server\|mobile` | 默认 server；mobile 更快但识别能力较弱，属降级选择 |
| `--device cpu\|gpu:0` | 默认 cpu；不支持时明确失败，不静默降级 |
| `--min-score` | 识别置信度阈值，默认 0.75 |
| `--min-text-height` | 按画面高度比例排除过小文字，默认 0（不过滤） |
| `--white-text` / `--white-yellow-text` | 颜色隔离，仅在核对画面后使用 |
| `--start` / `--end` | 只处理片段，默认全片 |
| `--refresh` / `--no-cache` / `--cache-info` | 强制重算 / 本次不缓存 / 查看缓存 |
| `--ffmpeg-dir` / `--node` / `--cookies` | 链接下载相关，Cookie 只接受显式文件 |

输出目录：`output/hardsub/<时间戳>_<缓存键前8位>/`

| 文件 | 内容 |
|---|---|
| `字幕.srt` | 带起止时间的字幕（UTF-8 BOM，兼容常见播放器） |
| `文字稿.txt` | 纯文本，按字幕顺序 |
| `cues.json` | `start/end/text/confidence` 数组 |
| `frames.jsonl` | 每帧时间戳、识别框、置信度、`pixel_reuse` 标记 |
| `run.json` | 参数、模型版本、状态、耗时拆解、缓存信息 |

命令最后一行是 JSON，例如：

```json
{"status":"complete","cache":{"hit":false,"key":"…","stored":true},"cues":26,
 "output":"…/output/hardsub/20261027-101500-123456_ab12cd34",
 "files":{"srt":"…/字幕.srt","txt":"…/文字稿.txt","cues":"…/cues.json"},
 "timings":{"content_hash":0.04,"cache_lookup":0.0,"ocr":38.9,"engine_init":12.1,"ocr_only":26.7,"pixel_reuse_frames":18,"total":39.2}}
```

`timings` 字段含义：`content_hash` 计算视频 SHA-256 的耗时，`cache_lookup` 校验缓存耗时，`engine_init` 模型加载，`ocr_only` 逐帧识别，`total` 进程总耗时。

## 4. 缓存规则

缓存键 = 视频内容 SHA-256 + 全部影响识别的参数（ROI、采样率、起止、模型、设备、阈值、颜色选项、像素复用开关）+ 引擎版本（paddlepaddle/paddleocr/paddlex/opencv）+ OCR 脚本哈希。

- 命中：复制产物到新目录（后缀 `_cached`），`cache.hit=true`，`run.json` 说明"本次没有重新识别"，并保留原始识别耗时 `original_run_seconds`。
- 未命中：正常识别，完成后把结果与产物哈希写入 `tools/cache/hardsub/<key>/`。
- 产物字节数或 SHA-256 不符、`cues.json` 条数不符、清单损坏 → 视为未命中并重跑（不提供半成品）。
- 只复用**完整结果**；`status` 为 `running` 的目录永远不会进缓存。

## 5. 原画面对照与校对

```bash
<venv python> scripts/review.py <结果目录> --workspace <workspace>
# 需要时：--min-text-height 0.05  --band 0.875,0.915
```

生成 `review.json` 与 `review-*.jpg`（每张 8 条：上为原画面裁切、下为候选文本），只合并相邻且数字一致的标点波动，空白后的重复字幕另列，数字/符号变化不合并。

逐张看图后写 `edits.json`：

```json
{"source_sha256":"<review.json 的 sha256>",
 "groups":[{"ids":[1,2],"text":"核对后的整句","reason":"画面为同一行，候选被拆成两段"}]}
```

所有候选 ID 必须按顺序各覆盖一次；纯背景误识别用 `"text": null` 删除并写原因。然后：

```bash
<venv python> scripts/review.py <结果目录> --workspace <workspace> --apply edits.json
```

输出 `…_reviewed/`。**没有看图不得声称已校对**；校对版不证明自动 OCR 零错误。

## 6. 只重排识别框

```bash
<venv python> scripts/refine.py <结果目录> --workspace <workspace> --subtitle-band 0.62,0.67
```

按已保存的识别框重新排序、按字幕带筛选，不改写文字，原结果保留。

## 7. 链接下载

统一入口已包含下载；也可单独调用：

```bash
<venv python> scripts/download.py <链接> --workspace <workspace> [--ffmpeg-dir <bin>] [--node <node>] [--probe] [--platform-subs]
```

`--probe` 只解析，不代表下载成功。`--platform-subs` 另存平台字幕轨（不是画面 OCR 结果）。

抖音、B 站另有无界面浏览器通道（Windows）：

```bash
<venv python> scripts/browser-download.py <链接> --workspace <workspace> --browser <Edge/Chrome 路径> --node <node> --ffmpeg-dir <bin> [--show-browser] [--reuse-browser]
```

使用工作目录内 `tools/browser-profile/hardsub/<平台>` 的独立配置；遇到登录/验证码时加 `--show-browser` 由用户本人完成，再同端口 `--reuse-browser` 重试。不复制、不导出其他浏览器的 Cookie。
