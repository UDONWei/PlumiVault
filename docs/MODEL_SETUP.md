# 模型准备

源码不含模型权重、文本特征和第三方私有名录。准备阶段可以下载公开依赖；日常识别使用本地文件，容器设置离线模式。

1. 安装 requirements-linux.lock.txt 中的 CPU 依赖（Windows 见 DEVELOPMENT.md）。创建独立的 `offline` 目录。
2. 从 BioCLIP 官方固定修订下载 [open_clip_pytorch_model.bin](https://huggingface.co/imageomics/bioclip/resolve/ce901ab3c6a913f9e9ef94ce6d27761069f4f01c/open_clip_pytorch_model.bin)，放入 offline。复制 docs/model-bioclip-v1.example.json 为 offline/model.json。程序读取时会验证权重 SHA-256，不能跳过或随意修改该校验值。
3. 运行 `python -B tools/prepare_detector.py --model-dir offline` 下载并校验固定 SSDLite 权重，同时生成 detector-ssdlite.json。
4. 在仓库根目录运行以下命令生成文本特征，仅处理标签文字，不读取照片。此步骤可能耗时数分钟。

```sh
python -B -c "import sys; from pathlib import Path; sys.path.insert(0,'tools'); from stage1_probe import LocalBioCLIP; LocalBioCLIP(Path('offline'),Path('docs/china-birds-ioc12.1-probe.json'),save_features=Path('offline/text_features.pt'))"
```

NAS 的 models 目录应包含 model.json、BioCLIP 权重、detector-ssdlite.json、SSDLite 权重、text_features.pt。可从自己的准备电脑上传这些文件至自己的 NAS，但不要提交 Git 或公开发布。更换标签或模型后必须重新生成匹配的文本特征。

标签文件以字节 SHA-256 绑定文本特征缓存；.gitattributes 对该文件禁用换行转换，保留原 NAS 使用的文件字节。不要因格式化或换行转换而无意修改标签文件。若曾按初次 GitHub 清理版生成文本特征，更新到 r9 后需按第 4 步重建一次；已有 NAS 的原版缓存保持兼容。

taxonomy_snapshot 默认 null。可选名录需要使用者另行合法取得，并在私人配置中填写容器内路径。仓库不附带中国观鸟记录中心名录或派生表；没有此文件也能使用历史 CC0 标签进行识别。

模型卡、代码许可和训练数据条款各自适用，见 SOURCES.md。下载失败时保留校验结果排查，不用不同模型冒充同一权重。
