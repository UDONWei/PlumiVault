# 来源与许可边界

r12 合并方案参考 [Linux Landlock 文档](https://docs.kernel.org/userspace-api/landlock.html)、[seccomp BPF 文档](https://docs.kernel.org/userspace-api/seccomp_filter.html)、[Linux 6.18 x86_64 系统调用表](https://github.com/torvalds/linux/blob/v6.18/arch/x86/entry/syscalls/syscall_64.tbl) 和 [Docker 多进程容器说明](https://docs.docker.com/engine/containers/multi-service_container/)。Landlock 不覆盖全部元数据操作，代码另加 seccomp 限制；Caddy 证书存储需要 fchmod，因此网关另有读取白名单。运行时仍复用既有 Caddy 2.11.7 与 CPU 依赖，不增加模型或第三方库。

| 组件或数据 | 固定基线与来源 | 说明 |
| --- | --- | --- |
| BioCLIP 初代 | [imageomics/bioclip](https://huggingface.co/imageomics/bioclip)，修订 ce901ab3c6a913f9e9ef94ce6d27761069f4f01c | 模型配置与 SHA-256 在 model-bioclip-v1.example.json；权重不分发。官方模型卡标示 MIT，使用前核对上游条款。 |
| pybioclip | [Imageomics/pybioclip](https://github.com/Imageomics/pybioclip)，2.1.6 | MIT；生产依赖固定在锁文件。 |
| OpenCLIP / PyTorch | open-clip-torch 2.32.0 / torch 2.7.1 CPU | 依赖分别遵循上游许可。 |
| 主体检测 | torchvision 0.22.1，SSDLite320 MobileNetV3 Large | 代码 BSD-3-Clause；预训练权重的训练数据条款另行适用，权重不分发。 |
| RAW 解码 | rawpy 0.25.1 / LibRaw | rawpy MIT，LibRaw LGPL/CDDL；声明见 third-party。 |
| 中国鸟类参考数据 | [Zhang 等（2022），BDJ 10:e93606](https://doi.org/10.3897/BDJ.10.e93606)，IOC 12.1 | 1481 种历史参考，数据 CC0；论文文字 CC BY 4.0。仓库含标签与地理分布数据及内嵌来源，不是当前完整名录。 |
| 行政区划 | [modood/Administrative-divisions-of-China](https://github.com/modood/Administrative-divisions-of-China)，c49d495b40ac73eb1a66f6eeae5f8fd10696f035 | WTFPL v2，数据日期 2023-06-30；见 locations-reference.json 元数据。 |
| 拼音 | pypinyin 0.55.0 | MIT。 |

中国观鸟记录中心的郑四版名录、其快照、名称对照表及未对齐清单不随本仓库分发。需要匹配该名录时，由使用者合法取得资料并私下配置 taxonomy_snapshot；学名精确匹配和人工核对机制保留。不把旧 CC0 数据宣称为该中心最新名录。

实验鸟眼模型不参与生产评分；其权重和个人评估图像不发布，参见 QUALITY_MODEL_EVALUATION.md。项目代码尚未指定整体许可；第三方许可证不会自动给项目整体或模型附带授权。
