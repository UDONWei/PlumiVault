# 验证

在仓库根目录运行：

```sh
python -B -m unittest discover -s tests -v
python -B tools/check_deployment.py
python -B tools/check_publication.py
```

环境见 DEVELOPMENT.md。测试仅生成合成照片和临时数据库；覆盖原图路径边界、只读隔离、增量清单、人工确认保留、暂存与恢复、同名冲突、编辑、预览缓存、进度、多选及分组。真实图库和私有名录快照不作为公共测试夹具。

合成测试不能证明真实 ARW 识别率、眼部对焦准确率、NAS 峰值内存或实际推理提速。Windows 无符号链接权限时，应报告跳过；缺少 Node 时部分交互测试跳过，不能称全部验证完成。

部署验收需另外检查健康状态、/photos 挂载 RW=false、显式目录选择，选择一个小目录核对候选、裁切、人工修改及数据库备份。启用 organizer 前单独核对权限和目标目录，不对真实照片试写。

2026-10-27 公开副本本机验证：146 项 Python 测试，143 通过，3 项因 Windows 无符号链接权限跳过；Node 交互检查使用显式运行时路径。部署静态检查与公开文件白名单检查通过。尚未在云端 Linux 环境重跑，也未为此副本重新构建 Docker 或部署 NAS。私有名录快照验收不属于公共测试集，名称匹配由合成案例覆盖。
