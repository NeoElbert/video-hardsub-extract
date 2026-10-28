# 第三方组件与来源

本源码采用 MIT，仅覆盖本项目自行实现的代码与文档。第三方代码、模型、运行库保持各自许可证，不因通过安装器下载而变为 MIT。源码 ZIP 和 Skill ZIP 不分发第三方依赖二进制、模型权重或 Python 环境。

## 已核对的直接运行组件

| 组件 | 实测版本 | 核验信息 |
|---|---|---|
| PaddlePaddle CPU / GPU | 3.2.2 | Apache-2.0；GPU 所需 NVIDIA 运行库有独立条款 |
| PaddleOCR | 3.4.0 | 安装元数据及官方 LICENSE：Apache-2.0 |
| PaddleX | 3.4.3 | 安装元数据：Apache-2.0 |
| opencv-contrib-python | 4.10.0.84 | Apache-2.0，另含 LICENSE-3RD-PARTY.txt |
| NumPy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| Pillow | 13.0.0 | MIT-CMU |
| psutil | 7.2.2 | BSD-3-Clause |
| yt-dlp | 2026.10.26 | Unlicense |
| yt-dlp-ejs | 0.8.0 | Unlicense AND MIT AND ISC |

以上是实际安装元数据的核对，不表示全部传递依赖或未来版本都采用同一许可。若今后分发免安装环境、FFmpeg 或 GPU 二进制，须按实际包含文件另外核对和携带完整许可，不能直接沿用本源码包结论。

官方依据：[PaddleOCR LICENSE](https://github.com/PaddlePaddle/PaddleOCR/blob/v3.4.0/LICENSE)、[PaddlePaddle LICENSE](https://github.com/PaddlePaddle/Paddle/blob/v3.2.2/LICENSE)、[PaddleX LICENSE](https://github.com/PaddlePaddle/PaddleX/blob/v3.4.3/LICENSE)、[yt-dlp LICENSE](https://github.com/yt-dlp/yt-dlp/blob/2026.10.26/LICENSE)。

## 模型与外部工具

[PP-OCRv5_server_det](https://huggingface.co/PaddlePaddle/PP-OCRv5_server_det) 和 [PP-OCRv5_server_rec](https://huggingface.co/PaddlePaddle/PP-OCRv5_server_rec) 官方模型卡均标注 Apache-2.0。首次识别由 PaddleX 下载到用户工作目录，不放入发布 ZIP。

FFmpeg 由用户自备，具体构建可能采用 LGPL/GPL 并含其他组件；Node.js 由用户自备，采用其官方许可。两者均不随本包分发。用户视频和平台内容不因本工具提供下载功能而获得再分发授权。

## 技术路线参考

- [YaoFANGUK/video-subtitle-extractor](https://github.com/YaoFANGUK/video-subtitle-extractor)，参考提交 `85746f7df5bf85978fd05f3ca6ce66e321a87a72`，Apache-2.0。本项目独立实现 CLI、预览、时间线和资料库，不包含该项目 GUI、打包资源和清理代码。
- [zyipeng/video-downloader](https://github.com/zyipeng/video-downloader)，参考提交 `ebdbf9e444ea4a18fab2442b50b519ed2b268615`，MIT，仅作为下载选型参考。

更多已验证平台限制见技能 `references/sources.md` 和 `references/limits.md`。
