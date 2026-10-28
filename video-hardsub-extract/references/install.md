# 安装与依赖

安装只做一次，全部写进 `<workspace>/tools`。技能包**不包含** Python 环境、模型、视频或缓存。

## 环境要求

| 项 | 要求 |
|---|---|
| 操作系统 | Windows 10/11（主要验证环境）；macOS/Linux 需自行提供 Python 3.10+，脚本本身无盘符假设 |
| Python | 3.10+，建议 3.12（实测 3.12.14） |
| 内存 | ≥ 8 GB（server 模型 CPU 推理；实测机器 31.2 GB） |
| 磁盘 | 预留 ≥ 3 GB（venv 约 0.9 GB + 模型约 0.17 GB + 缓存与结果） |
| FFmpeg | 仅链接下载需要，加入 PATH 或用 `--ffmpeg-dir` |
| Node.js | 仅个别站点（含抖音/B 站浏览器通道）需要，用 `--node` 指定 |
| GPU | 非必需；`--device gpu:0` 只在 Paddle 实际可用时成立 |

## 安装命令

```bash
python scripts/setup.py --workspace <workspace> --python <基础Python路径>
# Windows 便捷封装（等价）：
powershell -File scripts/setup.ps1 -Workspace <workspace> -Python <基础Python路径>
```

- 已存在 `tools/hardsub-venv` 时复用；必需包版本满足 requirements 且都能 import 时**跳过安装**，不反复 pip 安装。需要强制重装用 `--force`。
- 检查环境而不安装任何东西：`<venv python> scripts/hardsub.py --check --workspace <workspace>`。

## 依赖与体积（实测，Windows 11 / Ryzen 9 7845HX / 24 线程 / 31.2 GB）

| 项 | 实测值 |
|---|---|
| `pip install -r scripts/requirements.txt` | **9 分 07 秒**（全新 venv，含下载） |
| pip 下载缓存体积 | 220 MB（`tools/cache/pip`） |
| venv 落盘 | 859.3 MB / 28,054 文件 |
| PP-OCRv5 server det 模型 | 84.3 MB |
| PP-OCRv5 server rec 模型 | 81.3 MB |
| 模型合计 | 165.6 MB（`tools/cache/paddlex`） |

模型由 PaddleX 官方源在**首次识别时**自动下载到 `tools/cache/paddlex`。本机验收时该缓存已由前一阶段预先放入，因此"首次下载耗时"本轮**没有实测**，不在此给数字；体积以上表为准。可用 `--model-dir` 指向已下载的模型目录，避免重复下载。

版本（实测通过）：paddlepaddle 3.2.2、paddleocr 3.4.0、paddlex 3.4.3、yt-dlp 2026.10.26、Python 3.12.14。
PaddlePaddle 3.3 + oneDNN 在本机复现 `ConvertPirAttribute2RuntimeAttribute` 兼容错误；遇到同类报错请退回 3.2.2，而不是改模型或降采样。

## 缓存与临时文件

`scripts/runtime.py` 在导入 OCR 库之前把 `TEMP/TMP/TMPDIR`、`HOME/USERPROFILE`、`APPDATA/LOCALAPPDATA`、`PIP_CACHE_DIR`、`XDG_CACHE_HOME`、`HF_HOME`、`PADDLE_HOME`、`PADDLE_PDX_CACHE_HOME` 全部指向 `<workspace>/tools` 下，并设置 `PYTHONDONTWRITEBYTECODE=1`。

Windows 的 setup.py、install_local.py 和本地资料库默认使用 D:/视频字幕工具；拒绝系统盘及磁盘根目录。已有专属 D 盘目录时传入该目录复用。D 盘不存在时应选择其他数据盘，不回退 C。命令行识别入口仍需显式传入选定目录。浏览器下载设置和宿主程序自身记录不由脚本控制。
