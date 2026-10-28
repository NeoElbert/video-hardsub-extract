# 可选显卡加速

适用于 Windows NVIDIA 显卡；是否可用以本机真实识别自检为准。其他显卡仍可使用普通 CPU 方式，尚未适配其显卡加速。

先完成普通环境配置，并确保已有 PP-OCRv5 server 检测与识别模型。然后用当前工作目录的普通 Python 环境运行：

```bash
"$PY" "$SKILL/scripts/setup_gpu.py" --workspace "$WORKSPACE"
```

此步骤在当前目录的 `tools/hardsub-gpu-venv` 建立独立显卡环境，复用普通环境的通用依赖；普通环境需保留。安装固定匹配的 Paddle 3.2.2 CUDA 12.9 版及其 NVIDIA 计算库，可能下载数 GB。首次配置耗时不属于视频提取耗时。不会安装或更换系统显卡驱动。

安装后实际执行显卡矩阵运算和同一 server 模型的文字识别自检，成功才生成就绪记录。重新打开本地工具，已验证的环境默认勾选“显卡加速”；取消勾选可运行 CPU。未经配置或自检失败时显示“显卡未配置”，不得声称已经启用。提取失败会保留错误，不静默切换模型或降低采样率。

处理模型与采样参数保持不变，当前进程设置 `NVIDIA_TF32_OVERRIDE=0` 避免以 TF32 加速 FP32 运算。CPU 和 GPU 的计算数值仍可能略有差别，不承诺逐字节完全一致；用用户实际样本比较文字与时间轴，遇到差异需看原画面。速度也随显卡、画面文字量和视频长度变化。[NVIDIA 对该精度开关的说明](https://docs.nvidia.com/cuda/cutensor/2.8.0/user_guide.html)。

所有安装、计算缓存与结果归用户工作目录；CUDA 缓存显式设置到 `tools/cache/cuda`。批量删除记录不会删除共享环境和模型。

官方依据：[Paddle Windows 安装说明](https://github.com/PaddlePaddle/docs/blob/develop/docs/install/pip/windows-pip_en.md)、[CUDA 12.9 版安装包索引](https://www.paddlepaddle.org.cn/packages/stable/cu129/paddlepaddle-gpu/)、[NVIDIA CUDA 兼容性说明](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html)。驱动兼容性存在功能边界，必须以本机运行结果判断。
