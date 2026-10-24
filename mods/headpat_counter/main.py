#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
摸头计数器 🐱
点击桌宠的 face 或 ear 部位视为「摸头」，每摸一次显示一个飘字数字，
每满 10 次冒一句「再摸就赖你一辈子」。次数通过 config.json 永久保存。
"""


def setup(api):
    # 读取已有计数（首次为 0）
    cfg = api.load_config({"total": 0, "since_last_reset": 0})

    def on_click(part):
        # 把脸部/耳朵当作“摸头”部位
        if part not in ("face", "ear"):
            return

        # 计数 +1 并立即保存
        cfg["total"] += 1
        cfg["since_last_reset"] += 1
        api.save_config(cfg)

        total = cfg["total"]

        # 每次摸头飘一个当前次数的小粒子（数字上飘，更有成就感）
        api.add_particle(
            str(total),
            color=(255, 180, 80),
            vy=-35,          # 向上飘
            size=18,
            life=1.5
        )

        # 每满 10 次触发一次“大事”
        if total % 10 == 0:
            api.say("再摸就赖你一辈子～❤️", life=3.5)
            api.add_particle(
                "💕",
                color=(255, 100, 150),
                vy=-20,
                size=24,
                life=2.0
            )
        # 前几次也可以给点小反馈（可选，去掉#启用）
        # elif total == 1:
        #     api.say("第一下，好舒服～", life=2.0)
        # elif total == 5:
        #     api.say("手好软哦 😊", life=2.0)

    # 注册点击监听
    api.on("click", on_click)

    # 右键菜单查看统计
    def show_count():
        api.say(
            f"你一共摸了我 {cfg['total']} 次头！"
            f"（本次会话第 {cfg['since_last_reset']} 次）",
            life=4.0
        )

    api.add_menu_action("👋 查看摸头次数", show_count)

    api.log("摸头计数器已加载，当前总次数：{}".format(cfg["total"]))


def teardown(api):
    # 卸载/重载前不需要额外操作，因为每次点击都已调用 save_config
    api.log("摸头计数器已卸载")