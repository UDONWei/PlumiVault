# NAS 部署

适用 Linux/amd64、Docker Engine 与 Docker Compose。默认 CPU 上限 2、索引容器内存上限 6GiB。公开示例 IP `192.0.2.10` 仅用于文档，必须改成自己的 NAS 局域网 IP。

## 首次安装

1. 将源码放到独立安装目录，例如 `/volume1/docker/bird-index-nas`。不要安装在照片目录内。按 MODEL_SETUP.md 准备 models 目录；照片保持在已有目录。
2. 以普通 SSH 用户进入安装目录。默认脚本采用 `/volume1/照片/未处理`。如果你的路径不同，先调整 setup-nas.sh 的目录检查与 .env 中 BIRD_PHOTOS_PATH；启用整理服务前还需核对父目录约束。
3. 执行 `sh deploy/with-docker-sudo.sh setup-nas`。脚本交互设置网页用户 bird 的密码，生成本机凭据和配置，不开始扫描。只对 Docker 命令提权，避免把运行 UID 设成 root。
4. 编辑 `.env`，把 BIRD_BIND_IP 改为自己的 NAS IP，确认照片路径、UID/GID。保留密码哈希的单引号，别把 .env 上传仓库。setup 重试保留已有配置。
5. 联网构建并核对：

```sh
sh deploy/with-docker-sudo.sh start-nas &&
sh deploy/with-docker-sudo.sh verify-container
```

下载慢时用 NAS_OFFLINE_BUILD.md 的离线构建。启动后浏览器访问 `https://你的NAS地址:8443`。Caddy 使用本地 CA，须从自己的网关证书存储核对并安装根证书信任；不要长期忽略证书错误。索引端口 8765 不对外发布，网关提供 HTTPS 和 Basic Auth。

确认服务 healthy、`/photos` 挂载 `RW=false`、`RequireFolderSelection=True`。首次先手选小目录检查变更并确认；`ScanLimit: unlimited` 不会自动选择整库。不要用写原图来测试挂载。

## 后续更新

停止或完成待处理任务，保留数据库备份和原配置。源码更新后，在安装目录合并执行：

```sh
sh deploy/with-docker-sudo.sh upgrade-culling &&
sh deploy/with-docker-sudo.sh verify-container
```

脚本先检查只读挂载与进行中的任务，备份数据库、保留旧镜像，再构建并更新已启用的服务。失败即停止核对日志。不会启动扫描，也不会自动启用 organizer。不要用示例配置覆盖现有 config/config.json 或 .env。

## 可选整理与外网

需要暂存和恢复时，先阅读 USER_GUIDE.md，确认同盘目录、备份与写权限，再显式执行 `sh deploy/with-docker-sudo.sh enable-curation`。它使独立 organizer 获得受控父目录写权限，index 的 /photos 保持只读。启用本身不移动照片；网页逐批预览确认后才移动。此脚本按默认中文目录布局设计，其他布局需先适配，不能直接照搬。

外网建议使用个人 VPN 等私有连接，限制到图库端口；本仓库不包含个人 VPN 配置。不要直接公开索引服务或无鉴权服务。GitHub 发布不会改变现有 NAS、防火墙或网络路由。
