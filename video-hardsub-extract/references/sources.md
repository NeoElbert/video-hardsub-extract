# 来源、依赖与授权

本包可以独立运行，不需要原项目文件；下列上游只作为技术路线与依赖来源，代码为本项目重新实现。

## 技术路线参考

- **video-subtitle-extractor**（YaoFANGUK），提交 `85746f7df5bf85978fd05f3ca6ce66e321a87a72`，Apache-2.0。<https://github.com/YaoFANGUK/video-subtitle-extractor>
  本项目使用同系列 PP-OCRv5 检测/识别模型，重新实现 CLI、预览、时间轴合并与证据导出；**不包含**上游 GUI、清理逻辑与打包资源。

- **video-downloader**（zyipeng），提交 `ebdbf9e444ea4a18fab2442b50b519ed2b268615`，MIT。<https://github.com/zyipeng/video-downloader>
  仅作为在线下载选型参考；本项目重新实现 Windows 路径与调用，不执行其默认下载目录、macOS 安装或浏览器 Cookie 导出步骤。

- 另有 **Janusilver/multiplatform-downloader** 保留所有权利并禁止商用，**未**纳入本包任何代码或资源。

## 运行时依赖

| 依赖 | 版本（实测通过） | 许可 |
|---|---|---|
| PaddlePaddle | 3.2.2 | Apache-2.0 |
| PaddleOCR | 3.4.0 | Apache-2.0 |
| PaddleX（模型下载/推理） | 3.4.3 | Apache-2.0 |
| OpenCV（opencv-contrib-python） | 见 `--check` 输出 | Apache-2.0 |
| NumPy | 实测 2.5.4 | 包元数据为 BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0；包含第三方许可 |
| Pillow | 实测 13.0.0 | 包元数据为 MIT-CMU |
| psutil | 实测 7.2.2 | BSD-3-Clause |
| yt-dlp-ejs | 实测 0.8.0 | Unlicense AND MIT AND ISC |
| yt-dlp | 2026.10.26 | 上游为 Unlicense，具体分发组件以原许可证为准 |
| FFmpeg（外部，不随包） | 用户自备 | LGPL/GPL（按用户所选构建） |
| Node.js（外部，仅个别站点） | 用户自备 | MIT |

依赖通过正规软件包源安装，**发布包不包含**模型权重、Python 环境、依赖二进制、浏览器资料、账号凭据、样本视频或校对答案。

模型权重由 PaddleX 官方源在首次识别时下载到工作目录。官方 [server det 模型卡](https://huggingface.co/PaddlePaddle/PP-OCRv5_server_det) 和 [server rec 模型卡](https://huggingface.co/PaddlePaddle/PP-OCRv5_server_rec) 均标注 Apache-2.0。此处不表示全部传递依赖和 GPU 运行库都采用同一许可；NVIDIA 运行库以其单独条款为准，不随本包分发。

## 兼容性记录

- PaddlePaddle 3.3 + oneDNN 在 Windows CPU 上可复现 `ConvertPirAttribute2RuntimeAttribute`；同一模型在 3.2.2 上通过静音测试片。遇到同类报错请退回 3.2.2，而不是改模型或降采样。<https://github.com/PaddlePaddle/Paddle/issues/77340>
- Windows PowerShell 5.1 读取无 BOM 的 UTF-8 脚本会按本地代码页解析；本包的 `setup.ps1` 为纯 ASCII 输出并转调 `setup.py`，避免该问题。

## 声明

本包为独立实现，不使用他人账号、Cookie 或私有接口凭据；下载功能只处理用户显式提供的链接或文件。**未在市场上架**，ZIP 生成不代表通过审核；上架前需补齐发布者/入驻主体资料、示例素材授权与平台审核。
