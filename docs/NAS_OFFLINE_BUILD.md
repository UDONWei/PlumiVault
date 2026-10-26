# 离线构建依赖

目标为 Linux/amd64、CPython 3.12.14。Windows 的 Python 安装包不能直接给 NAS 使用。以下工具只下载公开软件包，不读取照片。

在可联网、装有 Docker 的准备电脑取得 `python:3.12.14-slim-bookworm` 和 `caddy:2.11.7-alpine`，用 docker save 导出并在 NAS 用 docker load 导入。保存 Python 镜像的包状态：

```sh
mkdir -p work
docker run --rm --entrypoint cat python:3.12.14-slim-bookworm /var/lib/dpkg/status > work/base-status.txt
python -B tools/prepare_linux_dependencies.py --output offline-build --base-status work/base-status.txt
python -B tools/verify_offline_dependencies.py offline-build
python -B tools/package_linux_offline.py --output work/linux-dependencies.tar
```

准备工具按固定 requirements-linux.lock.txt 选择 Linux wheel，核对 SHA-256、依赖闭包及 libgomp1 与基础镜像 gcc 版本。包校验失败不要继续构建。PowerShell 保存 base-status.txt 时使用 UTF-8 编码；无 Docker 的电脑可从 NAS 已有的同一镜像导出该文字文件。

上传依赖包及其 sha256 校验文件，在安装目录验证后解压；确认 offline-build/manifest.json 存在，再执行：

```sh
sh deploy/with-docker-sudo.sh start-nas-offline &&
sh deploy/with-docker-sudo.sh verify-container
```

源码、模型、基础镜像、wheel/deb 是不同部分，缺少任何必需项都会失败。离线依赖包和模型只存于自己的设备，不提交 GitHub。公开副本迁移不重新下载或验证这些大型依赖；工具的合成校验测试不能代替 NAS 实际构建。
