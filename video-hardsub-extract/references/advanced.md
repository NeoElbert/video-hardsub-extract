# 缓存与速度

同一个视频、同样的区域/采样率/时间范围/模型/阈值/颜色选项，且引擎与脚本版本一致时，第二次调用直接复用**完整结果**，输出目录带 `_cached` 后缀，`cache.hit=true`，`run.json` 里写明"本次没有重新识别"。

- 影响识别结果的任何参数变化都会重新识别：不同内容同名路径、不同 ROI、不同 `--sample-fps`、不同模型或阈值。
- 缓存命中前会校验产物的字节数与 SHA-256、字幕条数；产物被改动或写坏即视为未命中并重跑。
- `--refresh` 强制重新识别（仍更新缓存）；`--no-cache` 本次不读不写；`--cache-info` 列出已有条目与命中次数。
- 首次处理新视频没有缓存可命中，耗时就是真实识别耗时。提速只做确定性优化：相同裁剪像素逐帧精确复用（`pixel_reuse_frames` 记录数量），不降采样、不降模型、不跳帧。

## 参数要点

- 默认 `--mode server`（PP-OCRv5 server 检测+识别）、`--sample-fps 3`、`--device cpu`。`--mode mobile`、`--device gpu:0` 需本机实际可用，失败不冒称支持。
- 闪现字幕用 `--sample-fps 0`（逐帧）或更高值；采样间隔内的短暂字幕可能遗漏。
- 背景小字混入时，按预览核对字号后用 `--min-text-height`（占全画面高度的比例）过滤，正常数字字幕照常保留。
- 白字/黄字可比较 `--white-text`、`--white-yellow-text`，它们会隔离文字颜色并移除大块同色背景，两种都可能带来新的干扰，必须抽查原图再决定。

## 校对（可选，但不得跳过看图）

`scripts/review.py <结果目录> --workspace <workspace>` 会生成 `review-*.jpg`（上为原画面裁切、下为候选文本）与 `review.json`，只合并相邻且数字一致的标点波动。逐张看完后写 `edits.json`（`source_sha256` 为 `review.json` 哈希，`groups[].reason` 必填，所有候选 ID 按顺序各覆盖一次），再 `--apply` 得到校对版。**没有看图就不能说已校对**，校对版也不等于自动 OCR 零错误。

`scripts/refine.py` 可在已保存识别框的基础上按字幕带重排或筛选，不改写文字，原结果保留。

## 链接与平台边界

`hardsub.py` 收链接时先 `scripts/download.py` 的 `fetch()` 下载，再在同一进程内识别（模型只初始化一次）。平台实际可用性以 [limits.md](limits.md) 的实测记录为准：

- 抖音本地视频识别可用，但**直接下载链接常需新的 Cookie**；需要登录/验证码时交给用户，在专用浏览器里完成，不导出他人浏览器凭据。
- 快手、YouTube、B 站、X 各有样本下载成功，但**没有任何平台可以承诺所有链接都能下载**。
- B 站样本存在 74–77.4 秒筛选漏段，未通过质量门；X 的媒体文件 ID 与帖子 ID 映射待核实。
- 画面本身没有字幕就不会有输出；平台字幕轨（`--platform-subs`）是另一回事，不等于画面 OCR。

不要绕过访问控制，不要把别的视频或缓存视频当作目标链接成功。下载失败就如实报错并停止，不反复重试同一失败链接。

## 目录结构

```
<workspace>/
  output/hardsub/<run>/        字幕.srt 文字稿.txt cues.json frames.jsonl run.json（review 另有对照图）
  output/platform-download/    链接下载的原文件与 result.json
  tools/hardsub-venv/          工作目录内的 Python 环境（不随包分发）
  tools/cache/hardsub/<key>/   完整结果缓存（含产物哈希清单）
  tools/cache/paddlex/         PP-OCRv5 模型缓存（首次运行下载）
  tools/temp、tools/user       临时文件与任务专用 HOME/APPDATA
```

## 不做的事

不发布到市场、不改写识别文字以外的内容、不用语音补齐缺失字幕、不承诺五平台任意链接可用或自动零错。发布前需要发布者资料、素材权利与平台审核。
