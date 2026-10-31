# 两容器部署（r12，需 NAS 验收）

适用于已经启用整理服务、使用标准 `/photos` 库的 Linux/amd64 NAS。将 index、HTTPS gateway、organizer 合并为一个 `app` 容器；Tailscale 保持独立。完成后，本程序及远程访问共两个运行容器。其他应用或遗留的停止容器仍会另外占用管理界面的名额。

这是可选迁移，普通升级不会自动合并，也不会自动启用整理服务。原有三服务部署仍可使用。r11 的降噪、看图缩放也包含在 r12 源码中；新质量模型仍未接入正式评分。

## 隔离及资源

- `/photos` 继续只读；为现有暂存/恢复流程保留 `/library` 写挂载。因此不能只用 `PhotosRW=false` 判断完整保护，必须同时通过进程沙箱测试。
- 每个子进程在执行服务前强制安装 Landlock ABI 6 以上规则。index 只能写 `/data`、`/tmp` 和 `/dev/null`；organizer 另外允许明确配置的原片目录和待删除目录。规则继承到解码及模型子进程，失败即退出，不降级运行。
- Landlock 不覆盖 chmod、时间戳等全部元数据操作。附加 x86_64 seccomp 过滤器拒绝这些操作、危险 ioctl、io_uring、跨进程取 fd 等路径。index 也不能对只读打开的原片调用 fchmod。网关需要 fchmod 写入新证书，故另加读取白名单，禁止打开照片目录或其别名；只有它允许 fchmod。新系统调用需评审后放行。
- 整理功能沿用已启用配置，仍须预览清单、人工确认、校验指纹，同盘不覆盖地暂存/恢复。不永久删除，不自动扫描或移动。
- index、organizer 仅监听容器回环接口；对外仍只有原 LAN IP 的 HTTPS 8443。原来的密码、认证 token、证书目录、数据库、模型和 Tailscale 都复用。
- 合并共享容器及进程命名空间，**不等同原来的三容器隔离**。Landlock TCP 规则按端口限制，不是按远端 IP；此方案也未提供独立容器网络对 UDP 的隔离。不是针对恶意插件或不可信扩展设计的环境，不应加入任意第三方程序。
- 一个监督进程管理三个服务；任一退出即停止其他子进程，由 Docker 整体重启。总内存上限 6 GiB、CPU 上限 2 核。模型仍按原有空闲机制释放；监督器不轮询图库。合并主要减少容器名额，不承诺推理加速或明显减少模型内存。

## 上传、迁移与检查

先等待扫描、补预览、重识别和整理任务结束；关闭正在加载原图的页面。保留一次网页下载的数据库备份。

在电脑 PowerShell 上传源码包和校验文件，替换示例用户名、IP、包所在目录：

```powershell
$packageDir = 'D:\Downloads'
scp -O -P 22 "$packageDir\bird-index-nas-culling-r12.tar.gz" "$packageDir\bird-index-nas-culling-r12.tar.gz.sha256" USER@192.0.2.10:/volume1/docker/bird-index-nas/
ssh -p 22 USER@192.0.2.10
```

输入 NAS 用户密码时不显示字符。看到 NAS 的 `USER@NAS:...$` 提示符后，才运行下列 NAS 命令；已在 NAS 提示符则跳过登录。所有步骤用 `&&` 串联，遇错停止：

```sh
cd /volume1/docker/bird-index-nas &&
sha256sum -c bird-index-nas-culling-r12.tar.gz.sha256 &&
tar -xzf bird-index-nas-culling-r12.tar.gz &&
sh deploy/with-docker-sudo.sh merge-containers &&
sh deploy/with-docker-sudo.sh verify-container
```

脚本先核对正在运行的挂载、任务状态和配置，使用 `/tmp` 合成文件验证写入/删除/改名/元数据拒绝、符号链接绕行、子进程继承、SQLite WAL/备份、网关证书写权限及整理改名恢复。绝不对真实照片试写。

随后复用本机 `bird-index-nas:0.3.0` 和 `caddy:2.11.7-alpine` 构建镜像，仅 COPY 源码和 Caddy，不运行 apt/pip、不下载模型。基础镜像缺失时应停止，不应放宽保护继续。保持原网关配置，仅将 `index:8765` 上游改为 `127.0.0.1:8765`；非常规上游配置会拒绝迁移。

备份配置及旧镜像标记后关闭旧入口，再次确认空闲、备份数据库。先移除三个已停止的旧应用容器，再创建一个新应用容器，避免迁移时额外占用第六个名额。只删除容器对象，不删除卷、绑定目录、照片或旧镜像，不操作 Tailscale。新服务健康检查验证三个角色、沙箱标记、索引接口、整理状态和 HTTPS 证书及未登录 401。

新服务未通过检查时自动尝试恢复三个旧服务。不要在失败时运行 `down -v`、清理镜像或删除任何图库/证书/Tailscale 状态目录；保留日志以排查。

成功后先用既有照片核对登录、缩略图、高清对照、标记/星级持久化、数据库备份。手动补生成一张既有照片的高清预览可验证沙箱下 RAW/图像子进程；此时无需增加扫描范围或移动原片。确认后再日常使用。

## 回退

电脑 PowerShell 输入 `ssh -p 22 USER@192.0.2.10`，输入 NAS 密码，看到 NAS 提示符后执行；如果已在 NAS SSH 中则直接执行：

```sh
cd /volume1/docker/bird-index-nas &&
sh deploy/with-docker-sudo.sh rollback-compact &&
sh deploy/with-docker-sudo.sh verify-container
```

回退使用 `config/compact-backup-*` 中的旧配置和已保留的镜像，保留当前数据库及人工修改，不还原旧数据库覆盖新结果。运行中的任务会阻止回退，应先结束或取消。回退恢复三个应用容器，因此需留足名额；Tailscale 不变。主机断电或 Docker 本身不可用时，自动回退无法保证完成，需查看容器及脚本输出后继续，不要直接删除操作锁。

## 后续更新

上传后照常校验和解压，再执行 `upgrade-culling` 与 `verify-container`。`config/compact.enabled` 会让这两个脚本走合并版；不要再执行旧版首次安装/启用整理脚本。更新前仍需空闲，保留数据库和旧镜像；更新失败尝试恢复上一个合并镜像。源码包本身不会修改运行中的容器。

本机 Windows 只能验证配置、模拟迁移/回退及应用回归。实际 Docker、Linux 沙箱、Caddy 证书更新与 NAS RAW 预览必须在 NAS 上验收，不能把这些静态检查称为已经上线验证。
