# 视频画面字幕提取

一个 Skill，两种入口：在 WorkBuddy 中直接提取视频画面文字，或安装 Windows 本地批量字幕资料库。两者共用 PaddleOCR、PP-OCRv5 server 模型和同一套时间线格式。

当前版本：`0.2.0-rc9`，发布候选。源码采用 MIT；依赖和模型各自保留原许可证。官方仓库：https://github.com/NeoElbert/video-hardsub-extract 。固定版本和下载校验流程见 video-hardsub-extract/references/github-install.md。

## 入口一：WorkBuddy 直接提取

将发布包中的 `video-hardsub-extract` 文件夹作为 Skill 交给 WorkBuddy，读取其中 `SKILL.md`。用户提供本地视频或可访问链接，由 WorkBuddy 调用代码执行，展示按时间排列的全文并交付 TXT、SRT。JSON、日志和识别缓存留在后台。

首次让 WorkBuddy 按 `references/install.md` 设置专属工作目录并安装依赖。之后可以说：“提取这条视频的全部画面文字，按时间逐条展示，区分底部字幕和其他位置，导出 TXT 和 SRT。”

这里的聊天模型负责调用代码，实际识别在本地 PaddleOCR 中进行；不是纯大模型视觉识别，不要求购买或配置付费模型 API。WorkBuddy 的订阅和工具权限仍由原产品管理。

## 入口二：Windows 本地软件

要求现有 Python 3.12（带 tkinter），准备可用的数据盘目录。解压本源码包后，在 PowerShell 中运行：

```powershell
powershell -File .\Install.ps1 -Workspace 'D:\视频字幕工具' -Python '你的Python完整路径\python.exe'
```

安装器将临时目录、用户目录和缓存放在工作目录内，复用匹配依赖，创建 `local-tool/打开字幕工具.cmd`。首次识别会下载模型，需要联网。源码包不内置 Python、模型、虚拟环境或 GPU 运行库，因此不是免安装 EXE。

双击启动文件，导入多个视频或文件夹，按需设置范围，点击“提取所选”或“提取全部待处理”。每项自动保存视频副本、全文和字幕；可搜索、关闭重开、批量导出以及确认后删除资料库内的记录和副本。原视频、已有导出和共享模型不随记录删除。

默认全画面、server 模型、3fps。CPU 可用；NVIDIA 加速须按 `video-hardsub-extract/references/gpu.md` 独立安装并验证，不能直接假定每台电脑可用。更新时先等任务结束，保留旧版本及启动入口，不覆盖资料库。

## 时间线与准确度

TXT 逐条显示起止时间、原识别文字、位置、区域和可确认样式候选。同词不同位置、文字变化、消失后再出现分别记录。SRT 为标准字幕时间轴。

3fps 的采样间隔约333毫秒，不能精确定位每个字的真实出现时间；闪现文字、手写字、花体、竖排和小字可能漏识别或误识别。位置分类不证明文字就是口述字幕。字体名称、字重和真实字号未确认时不编造。结果是待复核自动稿。

## 链接与系统边界

本地视频识别不依赖平台登录。链接下载取决于平台、网络、原链接和用户权限，不能保证任意链接可用。抖音样本因 Cookie 要求跳过；既有 B 站样本存在漏段，X 帖子媒体映射仍待核实，详见 `video-hardsub-extract/references/limits.md`。本地短片验收不证明所有平台已通过。

Windows 是已验证平台。其他系统的 CLI 和桌面启动流程未完成验收。软件自身数据在用户选定目录内；宿主和浏览器自己的记录不受本工具控制。

## 验证与发布

- `docs/VALIDATION.md`：实际完成的验证和局限。
- `docs/THIRD_PARTY.md`：依赖、模型与来源说明。
- `tests/test_release.py`：不加载 OCR 的离线包校验测试。
- `release.json`：版本、技能包校验值及尚未确定的线上仓库信息。
- `tools/build_release.py`：按固定文件清单生成 Skill ZIP；新增文件需同步清单。

开发测试先将 TEMP/TMP/TMPDIR 指到项目 `tools/temp`，再运行 `python -B tests/test_release.py`。发布前运行 `python -B tools/build_release.py --output <输出目录>` 并核对 SHA256。固定版本下载工具只在真实仓库和 tag 已发布后使用，不使用虚构链接或浮动 main ZIP。

源码包不包含私人视频、输出、资料库、登录资料、机器日志、模型或环境。发布者确定真实仓库后，只上传本目录审核清单中的内容；不要将运行工作目录整体公开。
