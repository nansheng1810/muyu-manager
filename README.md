# 牧鱼 · AstrBot 多机管理台

本地运行的 Windows 桌面管理台，用一套界面管理多台 AstrBot 实例与 NapCat QQ 机器人：建机器人、装运行环境、装插件、看监控、跑自动化。

当前版本：**v1.23.12**

## 功能

- **一键部署**：首屏只需填 API Key，自动识别可用模型并测试连接；一键创建机器人，并自动安装 AstrBot 运行环境、Python 3.12、NapCat 与 19 个插件套装。
- **多实例管理**：创建 / 导入 / 发现实例，启停与重启、端口分配、Dashboard 免密直达、NapCat 状态与自动重连。
- **运行监控**：舰队总览、健康检查、告警、任务调度、审批、备份与运维面板。
- **消息中心**：QQ / B 站消息收件箱、自动回复与人工审核、双机对话、群聊增强。
- **拟人化能力**：长期记忆、人物档案、在场状态、心情与行为节奏、人格风格、表情包、看图接话。
- **自动化**：定时任务、DSH Bridge、发布检查、效果评估。
- **PWA**：浏览器访问同样可用，支持添加到桌面。

## 运行要求

- Windows 10 / 11
- Python 3.12（源码模式）
- Microsoft Edge WebView2（Win11 自带；缺失时自动回退到 Edge App 或默认浏览器）
- Node.js 18+（仅用于运行前端测试）

## 快速开始

### 方式一：打包版

下载 Release 中的 `牧鱼` 目录，双击 `牧鱼.exe` 即可。首次启动会在 `127.0.0.1:7311` 拉起本地服务并打开桌面窗口，端口被占用时自动顺延。

### 方式二：源码运行

双击 `启动管理器.bat`，脚本会自动创建 `.venv`、安装依赖并启动。

也可以手动执行：

```bat
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe launcher.py
```

### 首次使用

1. 没有机器人时，界面只显示「一键部署」。
2. 选择厂商或自定义接口，填入 API Key；失焦后会自动拉取模型列表，也可手动点「检测模型」「测试连接」。
3. 点击创建机器人，按提示完成环境、NapCat 与插件安装（下载失败会自动切换镜像）。
4. 安装完成后进入控制台，后续在「实例」页继续管理。

## 数据与安全

运行数据统一存放在：

```
%LOCALAPPDATA%\AstrBot舰队管理器\data
```

其中 `instances.json` 含实例的 Dashboard 密码、WS Token 等敏感信息，`fleet_ops.sqlite3` 含运行记录。仓库已通过 `.gitignore` 排除 `data/`、`instances/` 与日志，请勿手动提交或公开截图。

用户填写的模型 API Key 写入对应 AstrBot 实例的配置，不保存在本仓库。

## 测试

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
node --test "tests/*.test.js"
```

当前基线：Python 428 项、Node 98 项。

## 打包

```bat
.venv\Scripts\python.exe -m pip install pyinstaller
.venv\Scripts\python.exe -m PyInstaller manager.spec
```

产物为 `dist\牧鱼\`，整个目录即客户端。升级时替换 exe 与 `_internal` 即可保留 `%LOCALAPPDATA%` 中的数据。

## 目录结构

```
launcher.py              桌面外壳：FastAPI 服务 + pywebview 窗口
manager.spec             PyInstaller 打包配置
requirements.txt         运行依赖
启动管理器.bat            源码模式一键启动
server/                  后端（实例、部署、监控、记忆、自动化等）
web/                     前端页面与资源
web/assets/plugin_suite.zip  内置的 12 个插件（离线安装用）
tests/                   Python unittest 与 Node 内置测试
```

## 第三方插件

`web/assets/plugin_suite.zip` 内置 12 个 AstrBot 插件，随包保留各自许可证：

| 插件 | 许可证 |
|---|---|
| `astrbot_plugin_qzone` | GPL-3.0 |
| `astrbot_plugin_qqprofile` | AGPL-3.0 |
| `astrbot_plugin_dsh_bridge` | MIT |
| 其余 9 个 | 本项目作者编写 |

二次分发时请保留插件目录内的 `LICENSE` 与版权声明。

## 免责声明

本项目为非官方工具，与腾讯、AstrBot 上游无关联。QQ 自动化存在账号被风控或封禁的风险，请自行评估并遵守平台条款。

## 许可证

本项目自有代码采用 [MIT License](LICENSE)。内置第三方插件仍按其各自许可证分发。
