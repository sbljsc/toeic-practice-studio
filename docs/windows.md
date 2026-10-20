# Windows 10/11 x64 便携版指南

本指南面向只想使用练习功能的 Windows 用户。便携包不需要管理员权限，也不需要另行安装 Python、Node.js 或运行组件。

## 下载正确文件

打开 [TOEIC Practice Studio v0.1.0 Release](https://github.com/sbljsc/toeic-practice-studio/releases/tag/v0.1.0)，在 **Assets** 中下载：

```text
TOEIC-Practice-Studio-0.1.0-windows-x64.zip
```

不要使用 GitHub 自动生成的 “Source code (zip)” 或 “Source code (tar.gz)”。源码压缩包没有完成便携运行所需的组装，也不是本指南面向的下载项。

当前便携包面向 Windows 10/11 x64。包内按发行约定包含固定版本的官方 CPython 3.14.8 嵌入式运行时、锁定并随包提供的 Python 依赖、构建后的 React 网页、题库资源，以及本程序和依赖的许可证与权利声明。目标使用流程不需要联网安装运行时，也不要求 `PATH` 中已有 Python 或 Node.js。

## 解压与启动

1. 将下载的 ZIP **完整解压**到一个可写的普通文件夹。
2. 解压后的顶层目录固定为 `TOEIC-Practice-Studio`。进入该目录，确认其中同时存在 `Start.cmd`、`apps/`、`content/` 和便携运行时目录；不要只取出 `Start.cmd`。
3. 不要直接在 ZIP 预览窗口中运行文件。先用 Windows 解压功能或可信的解压工具解压。
4. 双击 `Start.cmd`。保持随后出现的启动窗口打开。
5. 默认浏览器会自动打开 [http://127.0.0.1:8765](http://127.0.0.1:8765)。
6. 结束时回到启动窗口按 `Ctrl+C`。关闭启动窗口也会停止本机服务。

服务只监听 `127.0.0.1`，供当前电脑上的浏览器访问。它不是公网服务，不应通过端口转发、反向代理或其他方式向外部开放。

### 可选参数

在解压目录打开命令提示符或 PowerShell 后执行：

```powershell
.\Start.cmd --port 8766
.\Start.cmd --no-browser
```

`--port 8766` 用于默认端口 `8765` 已被其他程序占用的情况。地址随端口变化，例如 `http://127.0.0.1:8766`。

`--no-browser` 只阻止自动打开浏览器；服务仍会运行，需要手动访问 `http://127.0.0.1:8765`。两个参数可以同时使用：

```powershell
.\Start.cmd --port 8766 --no-browser
```

双击启动时不能直接附加参数。

## 学习数据、备份与升级

便携版默认把学习数据库、历史、生词和界面备份写入解压目录下的 `.data/`。发行 ZIP 不包含 `.data/`，首次启动时会从空数据开始。

服务运行时不要只复制 SQLite 主文件。请在界面「设置」中创建学习数据备份；需要时可以选择包含题库。恢复前程序会另建恢复前备份，正在进行的练习会阻止恢复。

升级前按以下顺序操作：

1. 在旧版本的界面「设置」中创建并确认学习数据备份。
2. 回到启动窗口按 `Ctrl+C`，确认服务已经停止。
3. 保留原有 `.data/`，不要用空目录、旧包文件或其他版本覆盖、删除或替换它。
4. 推荐把新 ZIP 解压到另一个可写文件夹并启动新版，然后通过界面恢复刚创建的备份。也可在原目录更新程序文件，但必须避开 `.data/`。

升级不会自动迁移或合并不同目录中的数据库。若新版无法恢复备份，先不要删除旧目录和原始 `.data/`，保留启动窗口中的错误信息以及所用 ZIP 资产名，便于排查。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 双击后浏览器没有自动打开 | 保留启动窗口，查看是否已显示监听地址；手动打开 `http://127.0.0.1:8765`。若使用了 `--no-browser`，这是预期行为 |
| 页面提示无法连接 `127.0.0.1:8765` | 启动窗口可能已经关闭或服务未成功启动。重新双击 `Start.cmd`，并保留窗口 |
| 默认端口已被占用 | 在解压目录执行 `Start.cmd --port 8766`，再访问 `http://127.0.0.1:8766` |
| 提示缺少 Python、Node.js、`.venv` 或网页构建 | 这通常表示下载了源码 ZIP、没有完整解压，或者文件缺失。重新下载 Release 中的 `TOEIC-Practice-Studio-0.1.0-windows-x64.zip` 并完整解压；便携版用户不需要安装这些开发工具 |
| 解压或启动时无法写入文件 | 换到一个当前用户可写的普通文件夹后重新完整解压 |
| Windows 显示安全提示 | 只从上述官方 Release 下载并核对资产名。项目没有提供签名的自定义安装器，也不保证各台电脑上的 SmartScreen 提示行为一致 |
| 服务窗口被关闭后页面失效 | 这是预期行为；双击 `Start.cmd` 重新启动即可，已有学习数据仍在原 `.data/` 中 |

如问题仍存在，请保留所用资产名、Windows 版本、完整错误信息和可复现步骤。提交反馈时不要附带 `.data/`、个人数据库、备份、凭据或私人路径。

## 源码运行方式

需要修改代码或参与开发时，从源码运行。该方式与便携包不同，要求：

| 项目 | 源码要求 |
| --- | --- |
| Python | 3.12 或更新版本 |
| Node.js | 24 或更新版本，包含 npm |
| 网络 | 首次建立环境、安装锁定依赖和构建网页时需要 |

```powershell
git clone https://github.com/sbljsc/toeic-practice-studio.git
cd toeic-practice-studio
.\Setup.cmd
.\Start.cmd
```

Python 不在 `PATH` 中时，可将解释器路径传给安装脚本：

```powershell
.\Setup.cmd "Python安装目录\python.exe"
```

完成安装后，`Start.cmd` 同样支持 `--port` 与 `--no-browser`。便携版使用者不需要执行本节命令。

## 维护者构建便携包

构建机必须满足以下条件：

| 项目 | 构建要求 |
| --- | --- |
| 系统 | Windows x64 |
| Python | CPython 3.14 x64；应使用该解释器建立 `.venv`，锁定依赖的二进制 wheels 也必须支持 CPython 3.14 |
| Git | 可在 `PATH` 中使用；构建从已审查、已提交且没有未提交或未跟踪更改的源码运行 |
| Node.js | 24 或更新版本，包含 npm；打包器会自动执行 `npm ci` 与 `npm run web:build` |
| 网络 | 首次准备源码环境、获取固定运行时以及安装要随包提供的锁定依赖时需要 |

如尚未准备 CPython 3.14 的 `.venv`，先从仓库根目录运行安装脚本；之后直接运行打包器：

```powershell
.\Setup.cmd "CPython314安装目录\python.exe"
.venv/Scripts/python.exe tools/build_windows.py --version 0.1.0
```

打包器会校验 `--version` 与 `package.json` 及 `apps/api/pyproject.toml` 中的版本一致；三处必须同时改为待发布版本。它随后自动安装网页依赖并构建网页，不需要另外手动执行 `npm ci` 或 `npm run web:build`。打包器默认调用 Git，并拒绝脏工作树。构建过程使用固定版本的官方 CPython 3.14.8 嵌入式运行时和锁定、随包提供的 Python 依赖；构建机首次安装依赖和获取运行时需要网络，组装后的便携包面向用户运行时不需要联网安装。

包内 `build-info.json` 记录源码提交、Node 与 npm 版本、网页资产哈希、运行时信息、依赖版本及题库哈希，供发行复核。ZIP 内全部文件位于固定顶级目录 `TOEIC-Practice-Studio/`。

默认输出目录为 `dist/releases/`。Release 上传项只有以下两个文件：

```text
TOEIC-Practice-Studio-0.1.0-windows-x64.zip
TOEIC-Practice-Studio-0.1.0-windows-x64.zip.sha256
```

发布前应检查包内包含构建后的网页、同一份 2000 道题题库、完整运行时和依赖、启动文件、许可证及第三方声明；不得包含 `.data/`、个人数据库、备份、凭据或原始资料准备证据。本页只记录构建入口和发行约定，不表示某个 ZIP 已经通过下载、解压或浏览器验收。

## 验证范围与权利说明

当前便携目标为 Windows 10/11 x64。验收设计使用现有 Windows 主机，并在 `PATH` 中没有 Python / Node.js 的条件下模拟便携使用；这不等同于全新 Windows 虚拟机验收。项目没有签名的自定义安装器，不保证所有系统上的 SmartScreen 提示、企业策略或安全软件行为一致。

便携包与源码使用同一份题库。第三方练习内容仍归各自权利人；维护者目前未提供覆盖这些内容的再分发许可证或授权证明。自有代码仅按[使用条款](../LICENSE.md)作受限的个人非商业许可，不是 OSI 认可的开源许可证。第三方软件继续适用其原许可证，详见[软件依赖声明](../THIRD-PARTY-NOTICES.txt)。

请同时阅读[项目说明](../README.md)和[内容权利说明](../CONTENT-NOTICE.md)。
