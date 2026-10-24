# -*- coding: utf-8 -*-
"""柒葱桌宠 · 示例模组
=========================
把本文件当模板改就行。启用方式：
右键桌宠 →「🧩 模组管理器」→ 勾选「示例 Mod · 打招呼」→ 确定（立即生效）。

入口文件必须叫 main.py（也兼容 mod.py）。
可选生命周期：setup(api) / teardown(api)
"""

DEFAULT_CFG = {
    "greet": "嗨～我是被模组叫出来打招呼的柒葱♪",
    "interval": 90,          # 自动打招呼间隔（秒）
    "times": 0,              # 招呼次数（演示配置持久化）
}


def setup(api):
    """模组被加载时调用（桌宠启动 or 在管理器里启用）。"""
    api.log("示例模组已加载，目录：%s" % api.dir)

    cfg = api.load_config(DEFAULT_CFG)
    for k, v in DEFAULT_CFG.items():     # 兼容老配置
        cfg.setdefault(k, v)
    api.save_config(cfg)

    # ---------- 1) 气泡 / 粒子 ----------
    def hello():
        cfg["times"] += 1
        api.save_config(cfg)
        api.say("%s（第 %d 次）" % (cfg["greet"], cfg["times"]), 3.0)
        api.add_particle("★", color=(120, 200, 255), size=22, life=1.5)

    # ---------- 2) 「🧩 模组」子菜单项 + 定时器 ----------
    api.add_menu_action("👋 打个招呼", hello)
    api.every(cfg["interval"], hello)

    # ---------- 3) 顶层菜单项（直接铺在右键菜单上）----------
    def dance():
        api.set_state("hello_dance")
        api.say("看我跳个舞～♪")

    api.add_top_menu("✨ 跳个舞（顶层菜单）", dance)

    # ---------- 4) 自定义状态机 ----------
    # 注册状态 hello_dance：进入 3 秒后自动结束，绘制用 happy 立绘
    api.register_state(
        "hello_dance",
        sprite="happy",                       # 该状态用哪个素材绘制（可换成你自己的）
        duration=3.0,                         # 3 秒后自动回 idle
        enter=lambda p: api.log("进入 hello_dance"),
        update=lambda p, dt: None,            # 每帧可改 p.dy / p.rot 做动画
        exit=lambda p: api.log("离开 hello_dance"),
    )

    # ---------- 5) 素材控制 ----------
    # 把本模组目录下的图片注册成新素材（有 icon.png 才注册，不动原有立绘）
    if api.asset("icon.png") is not None:
        api.load_sprite("mod_icon", "icon.png")
        api.log("已注册自定义素材 mod_icon")

    # 想替换原有立绘就这样（谨慎）：
    #   api.load_sprite("idle", "my_idle.png")      # 替换待机立绘
    #   api.set_sprite("idle", None)                # 删除某素材
    #   api.set_sprite("eat", QPixmap("D:/x.png"))  # 直接塞 QPixmap

    # ---------- 6) 事件钩子 ----------
    api.on("caps", lambda upper: api.log("大小写切换 ->", "大写" if upper else "小写"))
    api.on("peek", lambda side: api.log("探头方向 ->", side))
    api.on("state_change", lambda old, new: api.log("状态变化 ->", old, "→", new))


def teardown(api):
    """模组被关闭 / 重载前调用，做清理。"""
    api.unregister_state("hello_dance")
    api.log("示例模组已卸载，下次见～")
