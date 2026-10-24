# 柒葱桌宠（QiCong Pet）

> 一只常驻 Windows 桌面的桌面宠物，站在任务栏上陪你写代码、摸鱼、发呆。

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/GUI-PySide6%20(Qt6)-41cd52)](https://pypi.org/project/PySide6/)
[![Version](https://img.shields.io/badge/Version-1.6.2-orange)]()
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

**柒葱**是一个透明、置顶、无边框的小窗口看板娘。她会散步、眨耳、发呆、说话，可以被**拖拽抛掷**（带重力掉落与弹跳）、**双击摸头**、**滚轮换大小**；内置 QQ 宠物式的养成数值、24 节气 + 节日皮肤、音乐节奏灯、桌面便签、番茄钟、任务栏系统监控面板，以及一套**可热加载的模组（Mod）系统**。纯 Python + PySide6 实现，可一键打包为单文件 exe。

---

## ✨ 功能特性

### 🎭 看板娘本体
- **透明置顶小窗**：无边框、可穿透点击，稳稳「站」在任务栏上方，不抢焦点。
- **丰富动画**：待机、散步、眨耳、发呆、说话、睡觉、洗澡、生病、上厕所、吃药，以及三种吃相（团子 / 曲奇 / 便当）。
- **物理拖拽**：按住可抛掷，头随鼠标、身子滞后摆动，落地带重力与弹跳。
- **互动彩蛋**：双击摸头、戳泡泡、炸毛、屏幕四角探头反应、大小写锁定提示。

### 🐣 QQ 宠物式养成
- 四项数值：**饱食度 / 心情 / 清洁 / 健康**，随时间离线衰减（关掉也会饿肚子）。
- **经验 / 等级** 成长体系，喂食、玩耍、摸摸头都能升级。
- **羁绊好感系统**：好感度分阶段成长，解锁专属台词。
- 数据自动保存到 `pet_save.json`，随时断点续玩。

### 🎏 节日 / 节气皮肤
- 内置 **24 节气** + 春节、元宵、中秋、圣诞等**节日皮肤**，按当天日期自动换装。
- 支持**自定义导入**皮肤图片（PNG/JPG/WebP/BMP），一键还原。

### 🎵 音乐节奏灯
- 后台采集**系统回环音频**，实时计算节拍能量与 8 个对数频段。
- 角色切换「打碟」立绘，跟着鼓点、镲片一起律动，可调高低频灵敏度、指定输出设备。

### 🍅 桌面便签 + 番茄钟 + 摸鱼监测
- **桌面便签**：随手记，贴在桌宠身上。
- **番茄钟**：长条电子钟倒计时，到点提醒你起来动一动。
- **摸鱼监测 + 久坐提醒**：别一坐一整天，柒葱会催你休息。

### 📊 任务栏系统监控
- 嵌入式小面板，实时显示 **网速（上/下行）/ CPU / 内存 / 开机累计流量**。
- 面板可拖拽、锁定、调透明度，自动避开托盘图标区。

### 🧩 模组（Mod）系统
- 每个子文件夹即一个模组，**热加载生效**，无需重启桌宠。
- 提供完整的 `api` 接口：菜单、气泡、粒子、定时器、事件钩子、自定义状态机、立绘替换、配置持久化。
- 自带模组：
  | 模组 | 作用 |
  |---|---|
  | `headpat_counter` | 摸头计数器：每次摸头飘字计数，每满 10 次触发特别台词 |
  | `url_proxy` | 网址加速：把打不开的网址拖给桌宠，自动拼加速前缀并用浏览器打开 |
  | `example_hello` | 示例模组：演示菜单 / 定时器 / 气泡 / 粒子 / 配置 / 状态机 |

  详细开发文档见 [`mods/README.md`](mods/README.md)。

### 🖱️ 右键菜单
喂食 / 玩耍 / 摸摸头 / 睡觉 / 大小 / 透明度 / 置顶 / 开机自启 / 隐藏到托盘 / 桌面便签 / 番茄钟 / 皮肤 / 模组管理器 / 状态 / 退出。

---

## 🚀 快速开始

### 方式一：直接运行 exe（推荐，无需装 Python）
下载 Release 中的 `qicong-pet.exe`，双击即可。首次启动会在 exe 目录下解出 `assets/` 与 `mods/` 文件夹。

### 方式二：源码运行
```bash
# 1. 安装依赖
pip install PySide6
# 可选：音乐模式 / 网速监控
pip install numpy soundcard psutil

# 2. 运行（无黑窗）
pythonw pet.py
# 或
python pet.py
```

### 方式三：一键启动脚本
双击 `start_pet.bat`，脚本会自动检测 / 安装依赖（优先使用 `tools/wheels/` 离线包，其次走清华镜像），然后唤出桌宠。

> **最低要求**：Python 3.9+（开发环境为 3.13）。仅运行桌宠本体只需 `PySide6`。

---

## 📦 打包为单文件 exe

```bash
pip install pyinstaller pillow   # pillow 用于生成图标，可省略

# 生成多尺寸图标（可选）
python -c "from PIL import Image; im=Image.open('assets/tray.png').convert('RGBA'); im.save('tools/icon.ico', sizes=[(s,s) for s in (16,24,32,48,64,128,256)])"

pyinstaller --noconfirm --clean --onefile --windowed \
  --name "qicong-pet" \
  --icon "tools/icon.ico" \
  --add-data "assets;assets" \
  --add-data "mods;mods" \
  --hidden-import numpy --hidden-import soundcard --hidden-import psutil \
  pet.py
```

产物在 `dist/qicong-pet.exe`。程序已适配 PyInstaller 的 frozen 运行模式：
- 以 **exe 所在目录**为工作目录（存档 / 模组 / 皮肤都可写）；
- 首次启动自动把内置 `assets/`、`mods/` 解压到 exe 目录，之后以磁盘上的内容为准。

---

## 📁 目录结构

```
qicong-pet/
├── pet.py                # 桌宠主程序（单文件，含全部逻辑）
├── bootstrap.py          # 依赖自检引导器（一键启动时调用）
├── start_pet.bat         # Windows 一键启动脚本
├── assets/               # 82 张立绘 / 皮肤素材（PNG，透明通道）
├── mods/                 # 模组根目录（每个子文件夹 = 一个模组）
│   ├── README.md         # 模组开发文档
│   ├── headpat_counter/  # 摸头计数器
│   ├── url_proxy/        # 网址加速 · 代理跳转
│   └── example_hello/    # 示例模组
├── tools/                # 开发 / 打包辅助脚本
│   ├── fetch_wheels.py   # 拉取离线 wheel 包
│   ├── fetch_audio_wheels.py
│   ├── process_*.py      # 素材切边 / 皮肤处理脚本
│   └── icon.ico          # exe 图标
└── LICENSE               # MIT 协议
```

---

## 🧩 模组开发速览

在 `mods/` 下新建文件夹，写一个 `main.py`：

```python
def setup(api):
    api.say("我的模组加载了！")

    def hi():
        api.say("来自模组的问候～")
        api.add_particle("★", color=(120, 200, 255))

    api.add_menu_action("👋 打个招呼", hi)   # 注册右键菜单
    api.every(30, hi)                        # 每 30 秒执行
```

右键桌宠 →「🧩 模组管理器」→ 勾选启用即可**热加载**。完整接口（自定义状态机、立绘替换、拖放钩子、事件、配置持久化）见 [`mods/README.md`](mods/README.md)。

---

## 📝 版本记录

| 版本 | 更新内容 |
|---|---|
| 1.6.2 | 修复拖文件给桌宠时明明删掉了却提示「吃不下」 |
| 1.6.1 | 新增模组 `drop` 拖放钩子，内置「网址加速 · 代理跳转」模组 |
| 1.6.0 | 移除「鼠标穿透」，保留便签与隐藏到托盘 |
| 1.5.0 | 桌面便签、隐藏到托盘；节日/节气皮肤补齐至全覆盖 |
| 1.4.0 | 羁绊好感系统、摸鱼监测 + 久坐提醒、互动彩蛋 |
| 1.3.0 | 修复皮肤切边、重绘节气皮肤、节日皮肤按日期排序 |
| 1.2.0 | 节日/节气皮肤体系、皮肤导入免 PIL、拖拽物理 |
| 1.1.0 | 音乐模式高低频灵敏度分离 + 打碟立绘、一键启动脚本 |

---

## 📜 许可证

本项目采用 [MIT License](LICENSE) 开源，可自由使用、修改、商用，保留版权声明即可。

---

## ⚠️ 说明

- 模组是**本地 Python 代码**，会被直接执行，请只加载你信任的模组。
- 首次启动后会在运行目录生成 `pet_save.json`（存档）与 `mods/*/config.json`（模组配置），请勿提交个人数据。
- 音乐模式依赖 `soundcard` + `numpy`，网速监控依赖 `psutil`，缺失时不影响桌宠本体运行。
