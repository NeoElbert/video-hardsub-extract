# GitHub 固定版本安装

官方仓库：https://github.com/NeoElbert/video-hardsub-extract
固定发布：https://github.com/NeoElbert/video-hardsub-extract/releases/tag/v0.2.0-rc9
技能包：https://github.com/NeoElbert/video-hardsub-extract/releases/download/v0.2.0-rc9/video-hardsub-extract-0.2.0-rc9.zip
校验清单：https://github.com/NeoElbert/video-hardsub-extract/releases/download/v0.2.0-rc9/SHA256SUMS.txt

先读取固定发布页与外部 SHA256SUMS.txt，取得技能 ZIP 的64位SHA256。发布尚未就绪或资产不存在时停止并如实说明，不回退到未知来源。校验值放在包外以避免ZIP自身哈希循环。

设置 TEMP/TMP/TMPDIR、HOME/USERPROFILE、APPDATA/LOCALAPPDATA 到用户选定数据盘工作目录 tools 下，然后运行本技能 scripts/fetch_release.py --workspace <目录> --repository NeoElbert/video-hardsub-extract --tag v0.2.0-rc9 --asset video-hardsub-extract-0.2.0-rc9.zip --sha256 <从发布清单取得的值>。

脚本下载、验证并解压，不执行代码。只有返回verified后，才用现有Python运行已解压版本scripts/setup.py --workspace <目录>，再用工作目录tools/hardsub-venv/Scripts/python.exe运行同版scripts/install_local.py --workspace <目录>。提供生成的local-tool/打开字幕工具.cmd。首次识别会下载模型；不把下载成功当成OCR验收成功。

更新前等任务完成，备份启动入口、保留旧版本，不覆盖资料库。默认server模型、3fps和全画面；GPU须另行验证。GitHub网络不可用时可使用本机已校验包，并注明本地来源。
