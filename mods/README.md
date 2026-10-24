# 柒葱桌宠 · 模组（Mod）开发文档

本目录是模组根目录。**每个子文件夹 = 一个模组**，文件夹名就是模组 ID。

```
mods/
├─ README.md              ← 本文档
├─ example_hello/         ← 示例模组（可直接参考 / 开启体验）
│  ├─ mod.json            ← 可选：元信息
│  └─ main.py             ← 必需：入口文件
├─ url_proxy/             ← 网址加速 · 代理跳转：把网址拖给桌宠 → 自动拼前缀打开
└─ 你的模组名/
   ├─ mod.json
   ├─ main.py
   └─ (可选) 你自己的图片等素材
```

### 自带模组

| 文件夹 | 作用 |
|---|---|
| `example_hello` | 演示菜单/定时器/气泡/粒子/配置/状态机，照着改就能写自己的模组 |
| `url_proxy` | **网址加速**：把打不开的网址拖给桌宠，自动拼成 `https://net.cqc.cn.eu.org/<原地址>` 并用默认浏览器打开；右键「🔗 加速网址…」可手动粘贴，前缀可在「⚙️ 设置加速前缀」里改 |

只要文件夹里有 `main.py`（也兼容 `mod.py`）就会被识别。启用后桌宠启动时自动加载。

---

## 一、快速开始

1. 在 `mods/` 下新建文件夹，例如 `mods/my_mod/`。
2. 在里面新建 `main.py`：

```python
def setup(api):
    api.log("我的模组加载了！")

    def hi():
        api.say("这是来自我的模组的问候～")
        api.add_particle("★", color=(120, 200, 255))

    api.add_menu_action("👋 打个招呼", hi)   # 注册右键菜单项
    api.every(30, hi)                        # 每 30 秒自动执行
```

3. 右键桌宠 →「🧩 模组管理器」→ 勾选启用 → 确定（**立即热重载生效**，无需重启）。

---

## 二、`mod.json`（可选）

```json
{
  "name": "我的第一个模组",
  "version": "1.0.0",
  "author": "你的名字",
  "description": "这个模组会做一件很酷的事"
}
```

可选字段还有一个 `entry`（入口文件名，默认 `main.py`）。不写 `mod.json` 也能跑。

---

## 三、生命周期

在 `main.py` 顶层定义（都可选）：

| 函数 | 调用时机 |
|---|---|
| `setup(api)` | 模组被加载时（桌宠启动 或 管理器里启用/重载后） |
| `teardown(api)` | 模组被关闭 / 重载前（做清理） |

> 兼容写法：`on_load(api)` / `on_unload(api)` 也会被调用（当没有 setup/teardown 时）。

---

## 四、`api` 接口参考

### 4.1 全权控制桌宠本体

`api.pet`（等价于 `api.app`）就是桌宠实例，**可以读写它的任何属性、调用任何方法**：

```python
p = api.pet
p.hunger, p.mood, p.hyg, p.health      # 养成数值 0~100
p.exp, p.level                         # 经验 / 等级
p.state                                # 当前状态，如 "idle"/"walk"/"eat"/"peek"
p.src                                  # 全部素材 QPixmap 字典（可替换）
p.W, p.H, p.x(), p.y()                 # 尺寸与位置
p.feed("团子 🍡"); p.start_walk(); p.bath_now(); p.save()
```

修改属性没有任何限制，请自行注意别破坏存档结构。

### 4.2 常用方法

```python
api.log(*args)                      # 打印日志（自动带 [MOD] 前缀）
api.say(text, life=3.0)             # 气泡说话
api.add_particle(text, x=None, y=None, **kw)
                                    # 粒子；x/y 省略时默认角色中部
                                    # kw 可含 color/size/life/vy/vx
api.set_state(name)                 # 切换状态
api.get_state()                     # 当前状态
api.get_stat(key) / api.set_stat(key, value)   # 读写任意属性（安全版）
api.save()                          # 手动存档
api.add_lines(key, [句子, ...])      # 往某个台词分类追加台词
```

### 4.3 注册右键菜单

```python
api.add_menu_action("🎮 我的功能", 回调函数)   # 回调无参数
```

会集中显示在右键菜单的「🧩 模组」子菜单里。

### 4.4 事件钩子

```python
api.on("tick",         lambda dt: None)                 # 每帧（约 25fps）
api.on("state_change", lambda old, new: None)           # 状态切换
api.on("click",        lambda part: None)               # 点击部位 ear/face/tummy/skirt/feet
api.on("draw",         lambda painter: None)            # 每帧绘制末尾，可自定义叠加画面
api.on("caps",         lambda upper: None)              # 大小写锁定切换（True=大写）
api.on("peek",         lambda side: None)               # 进入边缘探头：-1左 1右 2上
api.on("drop",         lambda text: True)               # 拖放文本/网址到桌宠：返回 True = 已接管
```

也提供等价的具名方法：`api.on_tick(fn)`、`api.on_state_change(fn)`、`api.on_click(fn)`、`api.on_draw(fn)`、`api.on_drop(fn)`。

> `drop` 钩子在文件「被吃掉」**之前**触发。返回 `True` 表示这次拖放已被模组接管（主程序不再执行吞文件逻辑）；返回 `False`/`None` 则继续走原本的拖文件行为。
> 桌宠同时接受**文件拖入**和**纯文本/网址拖入**（`text/plain` 与 `text/uri-list`）。

### 4.5 定时器

```python
api.every(60, 回调函数)      # 每 60 秒执行一次
```

### 4.6 配置读写（存到本模组自己的文件夹）

```python
cfg = api.load_config({"greet": "你好", "times": 0})   # 读（无则返回默认）
cfg["times"] += 1
api.save_config(cfg)                                   # 写入 <模组目录>/config.json
```

### 4.7 读取自己的素材

```python
pm = api.asset("icon.png")     # 读本模组目录下的图片，返回 QPixmap；不存在返回 None
```

---

## 四·补 — 深层控制接口

下面这几个接口可以让模组**深度接入**桌宠本体。

### 4.8 顶层菜单项（直接铺在右键菜单上）

```python
api.add_top_menu("✨ 我的顶层功能", 回调函数)
```

与 `add_menu_action`（收进「🧩 模组」子菜单）不同，`add_top_menu` 会把按钮**直接加到右键菜单顶层**。

### 4.9 素材（立绘）替换

```python
api.load_sprite("idle", "my_idle.png")     # 用本模组目录里的图替换「待机」立绘
api.set_sprite("eat", QPixmap("D:/x.png")) # 直接塞一个 QPixmap
api.set_sprite("idle", None)               # 删除某个素材
api.get_sprite("idle")                     # 取当前素材（QPixmap）
```

替换后会**自动清掉缩放缓存**，下一帧立即生效。可替换的内置素材 key：

`idle` `left` `right` `back` `chibi` `sleep` `eat` `happy`
`bath` `sick` `toilet` `medicine` `eat_dango` `eat_cookie` `eat_bento`
`peek_left` `peek_right` `peek_top` `caps_upper` `caps_lower` `pomo_alert`
`wr1..6` / `wl1..6`（走路帧）

### 4.10 自定义状态机（接入新状态）

```python
api.register_state(
    "my_state",                 # 状态名
    sprite="happy",             # 这个状态绘制用哪个素材 key
    duration=3.0,               # 多久后自动结束回 idle（None = 不自动结束）
    enter=lambda p: None,       # 进入时
    update=lambda p, dt: None,  # 每帧（可改 p.dy / p.rot / p.state_left 做动画）
    exit=lambda p: None,        # 离开时
)

api.set_state("my_state")       # 进入这个状态
api.set_state("my_state", seconds=5)   # 进入并覆盖持续时间
api.leave_state()               # 立刻离开（回 idle）
api.unregister_state("my_state")
```

注册后，模组状态与内置状态（idle/walk/eat…）**平级共存**，会被状态变化钩子（`on("state_change")`）捕获，
也会自动获得地面影子（视为站立）。

### 4.11 事件 / 状态变化

```python
api.on("state_change", lambda old, new: api.log(old, "→", new))
```

---

## 五、绘制叠加示例（进阶）

```python
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QFont

def setup(api):
    def draw(painter):
        painter.setPen(QColor(80, 200, 120))
        painter.setFont(QFont("Microsoft YaHei UI", 10))
        painter.drawText(10, 20, "我是 Mod 画的字！")
    api.on("draw", draw)
```

---

## 六、注意事项

- 模组是**本地 Python 代码**，会被直接执行，权限等同于桌宠本身。**只放你信任的模组**。
- 单个模组出错**不会**拖垮桌宠：加载失败、钩子异常都会打印日志并跳过（`[MOD] ...`）。
- 不要在 `main.py` 顶层做耗时操作，把逻辑放进 `setup(api)`。
- 改动模组后，在「🧩 模组管理器」里重新确定一次即可热重载。
- 启用状态保存在 `pet_save.json` 的 `enabled_mods` 字段。
