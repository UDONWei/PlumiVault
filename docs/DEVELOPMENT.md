# 本地与云端开发

使用 Python 3.12、Node.js 22 或兼容版本、POSIX sh（Windows 可使用 Git for Windows 附带的 sh）。源码和合成测试可在云端开发，不需要连接 NAS 或上传照片。

Linux 开发环境：

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-linux.lock.txt
python -B -m unittest discover -s tests -v
python -B tools/check_deployment.py
python -B tools/check_publication.py
```

Windows 可使用 requirements-windows-stage1.lock.txt，并补充 pypinyin、PyYAML（版本见 Linux 锁文件）；Node/sh 需加入 PATH，也可设置 BIRD_NODE、BIRD_SH 指向可执行文件。不要使用真实照片目录作为测试临时目录。

推理运行还需另外准备模型，合成单元测试不下载或加载真实模型。云端环境只进行代码修改、合成测试和审查，不存储 NAS 密码、私网地址或图库。GitHub 托管完成不代表已创建云端计算环境。

本地试运行：复制 config.example.json 为被忽略的 config.local.json，填入已有只读照片路径并完成模型准备，执行 `python -B -m bird_index serve --config config.local.json --port 8765`。仅在受信任本机使用直连端口，NAS 使用鉴权网关。

发布前检查 git diff、运行公开文件检查。PUBLICATION_FILES.json 是经过审查的文件白名单，新增文件需人工确认再添加。它与 .gitignore 共同防止误提交，不能替代人工秘密检查。
