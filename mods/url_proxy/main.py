#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
网址加速 · 代理跳转 🔗
=================================
把打不开的网址交给柒葱，她帮你套上加速前缀再用浏览器打开。

用法一（推荐）：把链接 / 网址文本 **拖到桌宠身上**
    https://github.com/hicccc77/WeFlow/releases
    github.com/hicccc77/WeFlow/releases
    →  https://net.cqc.cn.eu.org/github.com/hicccc77/WeFlow/releases  并自动打开

用法二：右键桌宠 →「🔗 加速网址…」手动粘贴（默认填好剪贴板内容）

前缀可在右键菜单「⚙️ 设置加速前缀」里改，记录保存在本模组 config.json。
"""

import random
import re
import time

DEFAULT_CFG = {
    "prefix": "https://net.cqc.cn.eu.org/",   # 加速前缀
    "history": [],                            # 最近加速记录
    "max_history": 20,
}

# 形如 http:// https:// ftp:// 的协议头
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")
# 域名（含端口）+ 路径，用来判断这串东西到底像不像网址
_HOST_RE = re.compile(
    r"^(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}"
    r"(?::\d{1,5})?(?:/|$|\?|#)")

OK_LINES = [
    "帮你搭好桥啦，冲～🚀",
    "这回应该打得开了，快去～",
    "哼，又是打不开的链接？交给我吧",
    "加速完毕，别太感动喵～",
    "桥搭好了，浏览器我叫应啦🔗",
]
GITHUB_LINE = "GitHub 我熟，桥搭好了，冲🚀"
ALREADY_LINE = "这本来就是加速链接嘛，直接开～"


def _extract(raw, prefix_host):
    """从拖进来的文本里解析出网址。

    返回 (去掉协议后的地址, 是否已经是加速链接)；不像网址则返回 None。
    """
    if not raw:
        return None
    s = str(raw).strip()
    if not s or len(s) > 2048:
        return None

    # 多行 / 多段文本：取第一个非空行、第一个空白前的片段（网址不含空白）
    line = ""
    for ln in s.splitlines():
        if ln.strip():
            line = ln.strip()
            break
    seg = line.split()
    s = seg[0] if seg else ""
    s = s.strip().strip("\"'<>“”‘’()[]{}，,。;；、")
    if not s:
        return None

    low = s.lower()
    if low.startswith(("mailto:", "file:", "data:", "javascript:", "about:")):
        return None

    already = bool(prefix_host) and prefix_host in low
    rest = _SCHEME_RE.sub("", s)          # 去掉 http:// https:// ...
    rest = rest.lstrip("/")
    if not rest:
        return None
    if "\\" in rest:                      # Windows 路径不是网址
        return None
    if not _HOST_RE.match(rest):          # 必须长得像 域名/路径
        return None
    return rest.rstrip("/"), already


def setup(api):
    cfg = api.load_config(DEFAULT_CFG)
    for k, v in DEFAULT_CFG.items():      # 兼容老配置缺字段
        cfg.setdefault(k, v)
    cfg["history"] = list(cfg.get("history") or [])

    def prefix_host():
        p = str(cfg.get("prefix") or DEFAULT_CFG["prefix"])
        return _SCHEME_RE.sub("", p).lstrip("/").split("/")[0].lower()

    def open_url(url):
        """用系统默认浏览器打开。"""
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            if QDesktopServices.openUrl(QUrl(url)):
                return True
        except Exception as ex:
            api.log("Qt 打开失败，改用 webbrowser：%s" % ex)
        try:
            import webbrowser
            return bool(webbrowser.open(url))
        except Exception as ex:
            api.log("打开失败：%s" % ex)
            return False

    def remember(rest, url):
        cfg["history"].insert(0, {"from": rest, "url": url, "t": time.time()})
        try:
            n = int(cfg.get("max_history", 20))
        except Exception:
            n = 20
        cfg["history"] = cfg["history"][:max(1, n)]
        api.save_config(cfg)

    def accelerate(raw):
        """核心：解析 → 拼前缀 → 开浏览器。返回 True 表示已接管这次拖放。"""
        got = _extract(raw, prefix_host())
        if got is None:
            return False                   # 不是网址，交回主程序处理
        rest, already = got

        if already:
            url = "https://" + rest
            line = ALREADY_LINE
        else:
            url = str(cfg.get("prefix") or DEFAULT_CFG["prefix"]) + rest
            line = GITHUB_LINE if rest.lower().startswith("github.com") \
                else random.choice(OK_LINES)

        ok = open_url(url)
        remember(rest, url)

        if not ok:
            api.say("唔…浏览器没叫应，链接我先记下了喵", 2.8)
            return True

        show = rest if len(rest) <= 36 else rest[:33] + "..."
        api.add_particle("🚀", color=(120, 200, 255), vy=-34, size=22, life=1.6)
        api.say(line + "\n" + show, 3.4)
        api.log("加速打开：%s" % url)
        return True

    # ---------- 右键菜单：手动粘贴 / 改前缀 / 看记录 ----------
    def _ask(title, label, default=""):
        from PySide6.QtWidgets import QInputDialog, QLineEdit
        text, ok = QInputDialog.getText(api.pet, title, label,
                                        QLineEdit.Normal, default)
        return (text or "").strip(), ok

    def ask_manual():
        try:
            from PySide6.QtWidgets import QApplication
            clip = (QApplication.clipboard().text() or "").strip()
        except Exception:
            clip = ""
        text, ok = _ask("网址加速", "把打不开的网址贴进来：", clip)
        if not ok or not text:
            return
        if not accelerate(text):
            api.say("这串不像网址喵…要 github.com/xxx 这样的", 3.0)

    def set_prefix():
        text, ok = _ask("加速前缀", "加速前缀（网址会拼在它后面）：",
                        str(cfg.get("prefix") or ""))
        if not ok or not text:
            return
        p = text.strip()
        if "://" not in p:
            p = "https://" + p
        if not p.endswith("/"):
            p += "/"
        cfg["prefix"] = p
        api.save_config(cfg)
        api.say("前缀改成 %s 啦喵" % p.split("://")[-1], 3.0)

    def show_history():
        h = list(cfg.get("history") or [])
        if not h:
            api.say("还没加速过任何网址喵", 2.6)
            return
        out = []
        for it in h[:5]:
            u = str(it.get("url", "")).replace("https://", "")
            out.append("· " + (u if len(u) <= 42 else u[:39] + "..."))
        api.say("最近加速的：\n" + "\n".join(out), 4.6)

    def copy_last():
        h = list(cfg.get("history") or [])
        if not h:
            api.say("还没有记录喵", 2.2)
            return
        try:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(str(h[0].get("url", "")))
            api.say("上一条加速链接已复制～", 2.4)
        except Exception as ex:
            api.log("复制失败：%s" % ex)
            api.say("复制失败了喵…", 2.2)

    # 拖放网址 → 核心功能
    api.on("drop", accelerate)
    # 顶层菜单：手动输入
    api.add_top_menu("🔗 加速网址…", ask_manual)
    # 「🧩 模组」子菜单
    api.add_menu_action("⚙️ 设置加速前缀", set_prefix)
    api.add_menu_action("📜 最近加速记录", show_history)
    api.add_menu_action("📋 复制上一条链接", copy_last)

    api.log("网址加速模组已加载，前缀：%s" % cfg.get("prefix"))


def teardown(api):
    api.log("网址加速模组已卸载")
