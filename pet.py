#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
柒葱 (QiCong) —— Windows 桌面宠物
====================================
像天选姬 / QQ宠物一样常驻桌面的看板娘：
- 透明置顶小窗，站在任务栏上，会散步、眨耳、发呆、说话
- 可以拖拽抛掷（带重力掉落和弹跳），双击摸头，滚轮换大小
- 右键菜单：喂食 / 玩耍 / 摸摸头 / 睡觉 / 大小 / 透明度 / 置顶 / 开机自启 / 状态 / 退出
- QQ宠物式养成：饱食度、心情、经验、等级，数据保存在 pet_save.json

依赖: PySide6
运行: pythonw pet.py   （或双击 start_pet.bat）
"""
import ctypes
import json
import math
import os
import random
import shutil
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import (QLockFile, QPoint, QRect, QRectF, QStandardPaths,
                            Qt, QTimer)
from PySide6.QtGui import (QAction, QColor, QFont, QFontDatabase, QFontMetrics,
                           QIcon, QImage, QPainter, QPainterPath, QPixmap, QPen,
                           QTransform)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QMenu, QMessageBox, QPushButton, QSlider,
                               QSpinBox, QSystemTrayIcon, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

_IS_FROZEN = getattr(sys, "frozen", False)
if _IS_FROZEN:
    # 单文件打包运行：以 exe 所在目录为工作目录（存档/模组/皮肤都写这里，保证可写）
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent
ASSET_DIR = BASE_DIR / "assets"
MODS_DIR = BASE_DIR / "mods"        # 模组目录：里面每个子文件夹 = 一个 mod
SAVE_FILE = BASE_DIR / "pet_save.json"


def _materialize_resources():
    """单文件打包运行时，首次启动把内置 assets/mods 解压到 exe 目录。

    这样皮肤导入、模组配置写入都落在可写目录；之后以 exe 目录内容为准，
    用户自己新增的皮肤 / 模组不会被覆盖。
    """
    if not _IS_FROZEN:
        return
    meipass = Path(getattr(sys, "_MEIPASS", ""))
    for sub in ("assets", "mods"):
        src = meipass / sub
        dst = BASE_DIR / sub
        if src.is_dir() and not dst.exists():
            try:
                shutil.copytree(src, dst)
            except Exception:
                pass
NAME = "柒葱"
VERSION = "1.6.2"      # 版本号（设置窗口展示）

# 版本迭代记录：最新的写在最前面（设置窗口底部「Ver x.y.z」可点开查看）
VERSION_LOG = [
    ("1.6.2", "修复拖文件给桌宠时明明删掉了却提示「吃不下」：改为按「已删除」判定，失败自动重试一次"),
    ("1.6.1", "新增模组 drop 拖放钩子（可把网址/文本拖给桌宠），内置「网址加速 · 代理跳转」模组"),
    ("1.6.0", "移除「鼠标穿透」功能（与桌宠交互冲突，改为保留便签与隐藏到托盘）"),
    ("1.5.0", "新增实用功能：桌面便签、隐藏到托盘；节日/节气皮肤补齐至全覆盖"),
    ("1.4.0", "新增羁绊好感系统、摸鱼监测 + 久坐提醒、互动彩蛋（炸毛 / 戳泡泡 / 四角反应）"),
    ("1.3.0", "修复皮肤切边问题并重绘全部节气皮肤；节日皮肤表格按日期排序"),
    ("1.2.0", "新增节日/节气皮肤体系、皮肤导入无需 PIL、拖拽物理（头随鼠标、身子滞后摆动）"),
    ("1.1.0", "音乐模式高低频灵敏度分离 + 打碟立绘；一键启动脚本与依赖自检"),
]

# ============ 音乐模式（节奏灯）：后台采集系统回环音频 ============
def _audio_worker(pet):
    """后台线程：采集系统回环音频，算节拍能量 + 频段能量，供角色打拍。"""
    import numpy as np
    try:
        import soundcard as sc
    except Exception as ex:
        pet.music_error = "soundcard 未安装：%s" % ex
        return
    try:
        mic = None
        if pet.music_device_name:                # 用户指定了设备
            for mm in sc.all_microphones(include_loopback=True):
                if mm.name == pet.music_device_name:
                    mic = mm
                    break
        if mic is None:
            try:
                mic = sc.default_speaker()
            except Exception:
                mic = None
        if mic is None:
            loops = sc.all_microphones(include_loopback=True)
            mic = loops[0] if loops else None
        if mic is None:
            pet.music_error = "找不到回环设备"
            return
    except Exception as ex:
        pet.music_error = "回环设备初始化失败：%s" % ex
        return
    pet.music_ready = True
    pet.music_device_used = mic.name
    sr = 48000
    chunk = 2048
    norm = chunk / 2.0        # FFT 幅度谱归一化基准
    try:
        with mic.recorder(samplerate=sr) as rec:
            while not pet._music_stop.is_set():
                data = rec.record(numframes=chunk)
                if data is None or data.size == 0:
                    continue
                mono = np.mean(data, axis=1).astype(np.float32)
                rms = float(np.sqrt(np.mean(mono ** 2)))
                pet.music_level = min(1.0, rms * 6.0)     # 总音量（显示用）
                if rms < 0.002:                            # 几乎静音
                    pet.music_beat = 0.0
                    pet.music_pitch = 0.0
                    continue
                win = np.hanning(chunk)
                spec = np.abs(np.fft.rfft(mono * win))
                freqs = np.fft.rfftfreq(chunk, 1.0 / sr)
                # 8 个对数频段（低频鼓点→高频镲片），每个频段独立 → 每个圈独立大小
                bands = []
                edges = [40, 90, 160, 300, 600, 1200, 2600, 6000, 10000]
                for a, b in zip(edges[:-1], edges[1:]):
                    seg = spec[(freqs >= a) & (freqs < b)]
                    bands.append(float(seg.mean()) / norm if seg.size else 0.0)
                # 每个频段独立软限幅：用各段自己的历史峰值归一化，避免高频天然偏小
                arr = np.array(bands)
                if pet.music_peak is None:
                    pet.music_peak = arr.copy()
                else:
                    pet.music_peak = np.maximum(pet.music_peak * 0.995, arr)
                safe = np.maximum(pet.music_peak, 1e-6)
                pet.music_bands = (np.clip(arr / safe * 0.9, 0.0, 1.0)).tolist()
                # 低频(40-180)整体 → 节拍；高频(2k-8k) → 音调
                lo = float(spec[(freqs >= 40) & (freqs <= 180)].mean()) / norm
                hi = float(spec[(freqs >= 2000) & (freqs <= 8000)].mean()) / norm
                pet.music_beat = min(1.0, lo * 12.0)       # 节拍（鼓点/贝斯）
                pet.music_pitch = min(1.0, hi * 25.0)      # 音调（人声/旋律）
    except Exception as ex:
        pet.music_error = "采集中断：%s" % ex


# ---------------- 台词 ----------------
LINES = {
    "greet": ["我回来啦！主人有没有想我呀~", "喵——柒葱上线！", "今天也要一起加油哦♪"],
    "idle": ["喵~ 主人在忙什么呀？", "写代码累了就要摸摸猫耳，这是常识喵！", "耳朵和尾巴才不是装饰呢！",
             "彩虹 Rainbow~ ♪", "无聊了…要不要陪我玩一会儿？", "主人主人，看我表演一个原地踏步！",
             "嘿嘿，你在偷偷看我吧？", "要好好吃饭好好睡觉哦~", "喵呜~ 今天心情不错呢"],
    "drag": ["哇啊——飞起来啦！", "喵！轻、轻一点啦~", "哇，从这里看好高呀！", "放我下来~才怪，好玩！"],
    "land": ["喵呜！安全着陆~", "屁股…屁股着地了啦", "毫发无伤！柒葱身手敏捷！"],
    "angry": ["再戳就咬你哦！", "哼！戳够了没有啦！", "呜——炸毛了！不理你了！"],
    "feed": ["啊呜~ 好吃！谢谢主人！", "唔——最喜欢的味道！", "吃饱饱才有力气撒娇喵♪"],
    "full": ["唔…吃不下了，肚子圆滚滚的", "刚刚才吃过啦~"],
    "hungry": ["肚子咕咕叫了…想吃东西", "主人…我好饿喵呜…", "好想吃团子啊…"],
    "play_refuse": ["肚子好饿…先给我吃的嘛", "没力气玩啦，喂饱我再说喵…"],
    "play": ["耶！再来再来！", "喵喵喵！超开心！", "接住啦！我超厉害的吧！", "运动使我快乐喵♪"],
    "pet": ["呼噜呼噜~ 最喜欢主人了", "耳朵好痒嘿嘿…再摸一下", "喵♪ 感觉元气恢复了！"],
    "sleep": ["Zzz…晚安喵…", "呼…呼…（睡着了）"],
    "wake": ["唔…我睡饱啦！", "喵？叫我了吗？我梦到在吃团子…"],
    "levelup": ["叮——升级啦！柒葱最棒了！", "等级提升！撒花✿撒花✿", "又变强了一点点喵！"],
    "sad": ["呜…主人是不是不理我了…", "心情低落喵…要抱抱…", "陪伴是最长情的告白，懂？"],
    "back": ["哼！生气了，不理你了！", "呜…背对你一会儿…"],
    # 点击部位
    "ear": ["喵呜～耳朵是敏感部位啦！", "耳朵好痒…但是好舒服嘿嘿", "耳朵才不是用来拎的喵！"],
    "face": ["唔…脸、脸不许捏啦！", "脸红什么！才、才没有开心呢", "再摸脸就要咬你了哦（小声）"],
    "tummy": ["哈哈哈好痒！哈哈哈哈停！", "肚皮挠痒痒大作战？我赢！", "噗哈哈哈…饶命喵！"],
    "skirt": ["呀——！不许掀裙子！坏主人！", "裙底是禁止区域喵！！", "再看就把你眼睛蒙上！"],
    "feet": ["痛痛痛！踩到脚了啦！", "脚脚很娇气的喵！", "呜…要吹吹才能好"],
    # 日常
    "bath": ["泡澡时间到～舒服喵！", "泡泡浴！小鸭子们我来了♪", "搓搓搓，洗得香香的！"],
    "bath_done": ["洗白白啦！香喷喷的柒葱！", "全身轻飘飘的，泡澡真棒喵♪"],
    "toilet": ["唔…有点急，借过一下…", "厕所时间，不许偷看喵！", "人在马桶上，看书勿扰。"],
    "toilet_done": ["一身轻松喵～", "解决完毕！又是元气满满的一天！"],
    "medicine": ["药好苦…但为了健康我忍！", "捏着鼻子一口闷…咕咚。", "苦啊——！快给我糖！"],
    "sick": ["唔…头好晕，浑身没力气…", "咳咳…主人…我不舒服喵…", "好想快点好起来陪主人玩…"],
    "sick_ok": ["痊愈啦！健康万岁！", "活过来了喵！谢谢你照顾我～"],
    "dirty": ["身上黏黏的…想洗澡澡了…", "喵…感觉臭臭的，要洗香香…"],
    "need_toilet": ["咕噜噜…厕所厕所在哪里…", "唔…忍不住了喵！", "急急急！膀胱要炸了！"],
    "dizzy": ["天旋地转…星星在头上转圈圈…", "晕乎乎…刚才摔得好惨喵…", "脑瓜嗡嗡的…扶我一下…"],
    # 边缘探头 / 大小写 / 吃文件
    "peek": ["嘿嘿…偷偷看主人一眼~", "喵？被发现了吗！", "扒着边边看看你在干嘛♪",
             "从边上偷瞄…主人在忙什么呀？"],
    "caps_on": ["大写锁定！A！", "锁定大写喵——抱住 A！", "注意！现在是 A 大写喵"],
    "caps_off": ["小写啦～a～", "解除大写，抱住小写 a！", "回到小写 a 喵~"],
    "eat_file": ["啊呜——吃掉啦！已经进回收站喵~", "唔姆！文件被柒葱吃进回收站了！",
                 "好吃好吃…（回收站里还能找回来哦）"],
    "pomo_done": ["时间到啦！休息一下喵~🍅", "番茄钟结束！起来动一动吧！",
                  "叮——时间到！柒葱提醒你休息♪"],
    "busy_on": ["好~主人忙吧，我自己乖乖玩♪", "明白！柒葱会自己照顾自己的~",
                "去忙吧，我不会乱跑的喵！"],
    "busy_off": ["主人忙完啦？陪我玩一会儿喵！", "终于有空啦~抱抱！"],
    "busy_care": ["（自己乖乖吃饭中…）", "（自己洗香香中…）", "（自己解决生理需求中…）"],
}
# 食物: 饱食度/心情/经验 + 专属吃相图 + 咀嚼风格
FOODS = {
    "团子 🍡":  {"stats": (30, 6, 6),  "img": "eat_dango",  "chew": 14, "amp": 0.04, "time": 1.9, "fx": "🍡"},
    "小饼干 🍪": {"stats": (20, 4, 4),  "img": "eat_cookie", "chew": 24, "amp": 0.06, "time": 1.7, "fx": "🍪"},
    "爱心便当 🍱": {"stats": (50, 10, 12), "img": "eat_bento", "chew": 9,  "amp": 0.08, "time": 2.6, "fx": "❤️"},
}

# 系统监控：可自选的显示项，以及信息框可放置的位置
SYSMON_ITEM_LABELS = {"cpu": ("🖥", "CPU"), "ram": ("💾", "RAM"),
                      "net_in": ("↓", "下载"), "net_out": ("↑", "上传"),
                      "flow": ("", "流量")}
SYSMON_POSITIONS = {"auto": "自动（跟随角色）", "left": "靠左", "right": "靠右",
                    "top": "靠上", "bottom": "靠下"}

# ============ 节日 / 节气（皮肤与提醒） ============
S_TERM_MIN = [0, 21208, 42467, 63836, 85337, 107014, 128867, 150921,
              173149, 195551, 218072, 240693, 263343, 285989, 308563,
              331033, 353350, 375494, 397447, 419210, 440795, 462224,
              483532, 504758]


def solar_term_date(year, n):
    """n=0..23（小寒→冬至）在 year 年的公历日期（通用算法，误差约±1 天）。"""
    import datetime
    base = datetime.datetime(1900, 1, 6, 2, 5)          # 1900 年小寒基准
    mins = (year - 1900) * 365.2422 * 1440.0 + S_TERM_MIN[n]
    return (base + datetime.timedelta(minutes=mins)).date()


# 24 节气：名称 / 提醒台词 / 粒子（n=0 小寒 → n=23 冬至，与 S_TERM_MIN 对应）
SOLAR_TERMS = [
    ("小寒", "小寒到，一年最冷的时候来了，注意保暖哦～", "❄"),
    ("大寒", "大寒啦，年底近了，准备过年咯～", "🧣"),
    ("立春", "立春啦！春天要来了～", "🌱"),
    ("雨水", "雨水节气，出门记得带伞哦～", "☔"),
    ("惊蛰", "惊蛰到，小虫子都醒啦～", "🐛"),
    ("春分", "春分，昼夜平分，春色正好～", "🌸"),
    ("清明", "清明时节雨纷纷，记得缅怀先人。", "🌧"),
    ("谷雨", "谷雨到，春雨贵如油～", "🌾"),
    ("立夏", "立夏啦！夏天要来了～", "☀"),
    ("小满", "小满，麦子快熟了～", "🌾"),
    ("芒种", "芒种忙种，又收又种～", "🌾"),
    ("夏至", "夏至，一年里白天最长的一天！", "🌞"),
    ("小暑", "小暑到，天气渐热，注意防暑～", "🧊"),
    ("大暑", "大暑，一年最热！多喝水喵～", "🍉"),
    ("立秋", "立秋啦，贴秋膘～", "🍂"),
    ("处暑", "处暑，暑气渐渐消啦～", "🍃"),
    ("白露", "白露，早晚温差大，加件衣服～", "🌫"),
    ("秋分", "秋分，昼夜又平分啦～", "🍁"),
    ("寒露", "寒露，露水凉了，别着凉～", "🧥"),
    ("霜降", "霜降，快入冬啦～", "❄"),
    ("立冬", "立冬啦，吃点热乎的～", "🍲"),
    ("小雪", "小雪，北方开始下雪啦～", "🌨"),
    ("大雪", "大雪！可以堆雪人了吗？", "⛄"),
    ("冬至", "冬至大如年，吃饺子还是汤圆？", "🥟"),
]

# 公历固定节日 + 农历节日（农历用近年公历日期，直接往 lunar 集合里加即可）
FESTIVALS = {
    "new_year":   {"name": "元旦", "date": (1, 1), "particle": "🎉",
                   "skin": "skin_new_year",
                   "line": "新年快乐！今年的第一个节日～"},
    "valentine":  {"name": "情人节", "date": (2, 14), "particle": "💖",
                   "skin": "skin_valentine",
                   "line": "情人节快乐～要一起过吗？"},
    "women":      {"name": "妇女节", "date": (3, 8), "particle": "🌸",
                   "skin": "skin_women",
                   "line": "女神节快乐～"},
    "april_fool": {"name": "愚人节", "date": (4, 1), "particle": "🃏",
                   "skin": "skin_april_fool",
                   "line": "嘿嘿，今天柒葱说的话要打个问号哦"},
    "labor":      {"name": "劳动节", "date": (5, 1), "particle": "🛠",
                   "skin": "skin_labor",
                   "line": "劳动最光荣！也记得休息～"},
    "youth":      {"name": "青年节", "date": (5, 4), "particle": "✨",
                   "skin": "skin_youth",
                   "line": "五四青年节，元气满满！"},
    "birthday":   {"name": "柒葱的生日", "date": (5, 28), "particle": "🎂",
                   "skin": "skin_birthday",
                   "line": "今天是柒葱的生日！放烟花庆祝啦～"},
    "children":   {"name": "儿童节", "date": (6, 1), "particle": "🎈",
                   "skin": "skin_children",
                   "line": "六一快乐！柒葱永远是小宝宝～"},
    "national":   {"name": "国庆节", "date": (10, 1), "particle": "🎊",
                   "line": "祖国生日快乐！假期愉快～"},
    "halloween":  {"name": "万圣节", "date": (10, 31), "particle": "🎃",
                   "skin": "skin_halloween",
                   "line": "不给糖就捣蛋喵！"},
    "xmas_eve":   {"name": "平安夜", "date": (12, 24), "particle": "🍎",
                   "skin": "skin_xmas_eve",
                   "line": "平安夜快乐～记得吃苹果哦"},
    "christmas":  {"name": "圣诞节", "date": (12, 25), "particle": "🎄",
                   "skin": "skin_christmas",
                   "line": "圣诞节快乐！帽子好看吗～"},
    "spring":     {"name": "春节", "particle": "🏮", "skin": "skin_spring",
                   "line": "春节快乐！柒葱提着灯笼给你拜年啦～",
                   "lunar": {(2026, 2, 17), (2027, 2, 6), (2028, 1, 26),
                             (2029, 2, 13), (2030, 2, 3)}},
    "lantern":    {"name": "元宵节", "particle": "🍡", "skin": "skin_lantern",
                   "line": "元宵节！吃汤圆了吗～",
                   "lunar": {(2026, 3, 3), (2027, 2, 20), (2028, 2, 9),
                             (2029, 2, 27), (2030, 2, 17)}},
    "duanwu":     {"name": "端午节", "particle": "🎋",
                   "line": "端午安康！要吃粽子吗～",
                   "lunar": {(2026, 6, 19), (2027, 6, 9), (2028, 5, 28),
                             (2029, 6, 16), (2030, 6, 5)}},
    "qixi":       {"name": "七夕", "particle": "💞", "skin": "skin_qixi",
                   "line": "七夕快乐～今天想见谁吗？",
                   "lunar": {(2026, 8, 19), (2027, 8, 8), (2028, 8, 26),
                             (2029, 8, 16), (2030, 8, 5)}},
    "mid_autumn": {"name": "中秋节", "particle": "🥮", "skin": "skin_midautumn",
                   "line": "中秋快乐！柒葱捧着月饼等你～",
                   "lunar": {(2026, 9, 25), (2027, 9, 15), (2028, 10, 3),
                             (2029, 9, 22), (2030, 9, 12)}},
    "chongyang":  {"name": "重阳节", "particle": "🍂", "skin": "skin_chongyang",
                   "line": "重阳节，记得关心家里的长辈哦～",
                   "lunar": {(2026, 10, 18), (2027, 10, 8), (2028, 10, 26),
                             (2029, 10, 16), (2030, 10, 5)}},
}


def today_festival(day=None):
    """今天是什么日子：返回 (key, info)。节日优先于节气；都没有返回 (None, None)。"""
    import datetime
    d = day or datetime.date.today()
    for key, info in FESTIVALS.items():
        if "date" in info:
            if (d.month, d.day) == info["date"]:
                return key, info
        elif "lunar" in info:
            if (d.year, d.month, d.day) in info["lunar"]:
                return key, info
    for n, (name, line, emo) in enumerate(SOLAR_TERMS):
        if solar_term_date(d.year, n) == d:
            return "term_%s" % name, {"name": name, "line": line,
                                      "particle": emo, "term": True,
                                      "skin": "skin_term_%s" % name}
    return None, None


def all_festival_entries():
    """调试面板用：所有日子 [(key, 显示名, 日期文本, info)]，按名称。"""
    import datetime
    out = []
    for k, info in FESTIVALS.items():
        if "date" in info:
            dstr = "%d月%d日" % info["date"]
        else:
            dstr = " / ".join("%d-%d-%d" % d for d in sorted(info["lunar"]))
        out.append((k, info["name"], dstr, info))
    for n, (name, line, emo) in enumerate(SOLAR_TERMS):
        d = solar_term_date(datetime.date.today().year, n)
        out.append(("term_%s" % name, name + "（节气）", str(d),
                    {"name": name, "line": line, "particle": emo,
                     "term": True, "skin": "skin_term_%s" % name}))
    out.sort(key=lambda e: e[1])
    return out


def pm_or_none(name: str):
    p = ASSET_DIR / name
    if p.exists():
        pm = QPixmap(str(p))
        if not pm.isNull():
            return pm
    return None


def autostart_path() -> Path:
    d = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                     "Start Menu", "Programs", "Startup")
    return Path(d) / "QiCongPet.bat"


def autostart_exists() -> bool:
    return autostart_path().exists()


def fmt_speed(bps: float) -> str:
    if bps >= 1 << 20:
        return f"{bps / (1 << 20):.1f} MB/s"
    if bps >= 1 << 10:
        return f"{bps / (1 << 10):.0f} KB/s"
    return f"{bps:.0f} B/s"


def fmt_bytes(b: float) -> str:
    """字节数 → GB / MB / KB（用于累计流量）。"""
    if b >= 1 << 30:
        return f"{b / (1 << 30):.2f} GB"
    if b >= 1 << 20:
        return f"{b / (1 << 20):.1f} MB"
    if b >= 1 << 10:
        return f"{b / (1 << 10):.0f} KB"
    return f"{b:.0f} B"


# 全局界面字体（设置里可改 → 规避字体版权风险）；数字用等宽字体
UI_FONT_FAMILY = "Microsoft YaHei UI"
UI_FONT_MONO = "Consolas"


def ui_font(size, bold=False):
    f = QFont(UI_FONT_FAMILY, size)
    f.setBold(bool(bold))
    return f


class SysMon:
    """系统监控：CPU / 内存 / 网速。
    网速优先用 psutil（32位 API 的 dwInOctets 在 Windows 上恒为 0，拿不到真实值）；
    没有 psutil 时 CPU/内存用 ctypes 兜底，网速显示不可用。"""

    IF_TYPE_LOOPBACK = 24

    def __init__(self):
        self._k32 = ctypes.windll.kernel32
        self._iphlp = ctypes.windll.iphlpapi
        self._cpu_last = None           # (idle, kernel, user)
        self._net_last = None           # (time, in_bytes, out_bytes)
        self.net_in = 0.0               # B/s
        self.net_out = 0.0
        self.net_ok = False             # 网速是否可用
        try:
            import psutil
            self.psutil = psutil
        except ImportError:
            self.psutil = None
        self._cpu_first = None

    # ---- 可选网卡列表（psutil 才有友好中文名）----
    def nics(self):
        if self.psutil is None:
            return []
        try:
            return list(self.psutil.net_io_counters(pernic=True).keys())
        except Exception:
            return []

    # ---- CPU 占用率（psutil 优先，否则 GetSystemTimes 差分）----
    def cpu(self):
        if self.psutil is not None:
            try:
                return self.psutil.cpu_percent(interval=None)
            except Exception:
                pass
        idle = ctypes.c_ulonglong()
        kernel = ctypes.c_ulonglong()
        user = ctypes.c_ulonglong()
        if not self._k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel),
                                        ctypes.byref(user)):
            return None
        cur = (idle.value, kernel.value, user.value)
        if self._cpu_last is not None:
            d_idle = cur[0] - self._cpu_last[0]
            total = (cur[1] - self._cpu_last[1]) + (cur[2] - self._cpu_last[2])
            self._cpu_last = cur
            if total > 0:
                return max(0.0, min(100.0, (1.0 - d_idle / total) * 100.0))
            return 0.0
        self._cpu_last = cur
        return None

    # ---- 内存占用：返回 (占用%, 已用GB, 总量GB) ----
    def ram(self):
        if self.psutil is not None:
            try:
                vm = self.psutil.virtual_memory()
                return (vm.percent, vm.used / (1 << 30), vm.total / (1 << 30))
            except Exception:
                pass
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_uint32), ("dwMemoryLoad", ctypes.c_uint32),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        st = MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(st)
        if self._k32.GlobalMemoryStatusEx(ctypes.byref(st)):
            used = st.ullTotalPhys - st.ullAvailPhys
            return (st.dwMemoryLoad, used / (1 << 30), st.ullTotalPhys / (1 << 30))
        return (0, 0.0, 0.0)

    # ---- 网速：nic=None 统计全部网卡，否则只统计指定网卡 ----
    def net(self, nic=None):
        if self.psutil is None:
            self.net_ok = False
            return
        try:
            if nic:
                io = self.psutil.net_io_counters(pernic=True).get(nic)
                cur = (io.bytes_recv, io.bytes_sent) if io else None
            else:
                io = self.psutil.net_io_counters()
                cur = (io.bytes_recv, io.bytes_sent)
        except Exception:
            self.net_ok = False
            return
        if cur is None:
            self.net_ok = False
            return
        now = time.time()
        if self._net_last is not None and self._net_last[1] is not None:
            dt = now - self._net_last[0]
            if dt > 0.2:
                self.net_in = max(0.0, (cur[0] - self._net_last[1]) / dt)
                self.net_out = max(0.0, (cur[1] - self._net_last[2]) / dt)
                self.net_ok = True
        self._net_last = (now, cur[0], cur[1])

    # ---- 本次开机以来网卡累计流量（等同控制面板「已发送 / 已接收 字节」）----
    def io_totals(self, nic=None):
        """返回 (已发送字节, 已接收字节)。Windows 网卡计数器开机后从 0 累计。"""
        if self.psutil is None:
            return (0, 0)
        try:
            if nic:
                io = self.psutil.net_io_counters(pernic=True).get(nic)
            else:
                io = self.psutil.net_io_counters()
            if io is None:
                return (0, 0)
            return (int(io.bytes_sent), int(io.bytes_recv))
        except Exception:
            return (0, 0)


class TaskbarMonitor(QWidget):
    """嵌在系统任务栏里的监控条（Win10 / Win11 通用）。
    定位到任务栏托盘区左侧，单行显示：网速 / CPU / 内存 / 本次开机累计流量。
    无边框、置顶、不抢焦点，让开托盘图标区。"""

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._font = QFont(UI_FONT_MONO, 8)
        self._data = ("--", "--", "--", "--", "--")
        self._text = "↑ --  ↓ --  CPU --  RAM --  流量 --"
        self._pad = 8
        self._lh = 16
        self._embedded = False
        self.allow_embed = True       # 由 Pet 按存档设置
        self.locked = False           # 锁定后不可拖动（右键切换 / 角色菜单解锁）
        self.opacity = 0.9            # 面板不透明度
        self.custom_pos = None        # 用户拖动后的屏幕坐标 (x, y)
        self.pet = None               # 由 Pet 注入，用于保存位置
        self._drag = None
        self._fit()

    # ---- 嵌入任务栏：把自己变成 Shell_TrayWnd 的子窗口 ----
    def embed(self):
        """把窗口变成系统任务栏的子窗口（真正嵌进任务栏，随其移动/隐藏）。"""
        try:
            u32 = ctypes.windll.user32
            tb = u32.FindWindowW("Shell_TrayWnd", None)
            if not tb:
                return False
            hwnd = int(self.winId())
            u32.SetParent(hwnd, tb)
            GWL_STYLE = -16
            WS_CHILD, WS_POPUP, WS_VISIBLE = 0x40000000, 0x80000000, 0x10000000
            st = u32.GetWindowLongW(hwnd, GWL_STYLE)
            st2 = ((st | WS_CHILD | WS_VISIBLE) & ~WS_POPUP) & 0xFFFFFFFF
            u32.SetWindowLongW(hwnd, GWL_STYLE, ctypes.c_int(st2).value)
            ok = (int(u32.GetParent(hwnd)) == tb)   # 真正成为子窗口才算成功
            self._embedded = bool(ok)
            self._place()
            return ok
        except Exception as ex:
            print("[TBAR] 嵌入任务栏失败：%s" % ex, flush=True)
            self._embedded = False
            return False

    def ensure_parent(self):
        """explorer 重启后任务栏窗口会重建，这里校验并重新嵌入。"""
        if not self._embedded:
            return
        try:
            u32 = ctypes.windll.user32
            tb = u32.FindWindowW("Shell_TrayWnd", None)
            if not tb or int(u32.GetParent(int(self.winId()))) != tb:
                self.embed()
        except Exception:
            pass

    def unembed(self):
        """关闭前先解除父子关系，避免影响 explorer 的任务栏。"""
        if not self._embedded:
            return
        try:
            u32 = ctypes.windll.user32
            hwnd = int(self.winId())
            u32.SetParent(hwnd, None)
            GWL_STYLE = -16
            WS_CHILD, WS_POPUP = 0x40000000, 0x80000000
            st = u32.GetWindowLongW(hwnd, GWL_STYLE)
            st2 = ((st & ~WS_CHILD) | WS_POPUP) & 0xFFFFFFFF
            u32.SetWindowLongW(hwnd, GWL_STYLE, ctypes.c_int(st2).value)
        except Exception:
            pass
        self._embedded = False

    # ---- 拖动 / 锁定 / 右键固定 ----
    def set_locked(self, on):
        self.locked = bool(on)
        if self.pet is not None:
            self.pet.tbmon_locked = self.locked     # 同步存档字段
            self.pet.save()

    def _break_embed(self):
        """自由拖动时脱离任务栏嵌入。"""
        if self._embedded:
            self.unembed()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.pos()
        elif e.button() == Qt.RightButton:
            self.set_locked(not self.locked)   # 右键单击 = 固定 / 解锁

    def mouseMoveEvent(self, e):
        if self.locked or self._drag is None or not (e.buttons() & Qt.LeftButton):
            return
        self._break_embed()
        pos = e.globalPosition().toPoint() - self._drag
        self.move(pos)
        self.custom_pos = (int(pos.x()), int(pos.y()))
        if self.pet is not None:
            self.pet.tbmon_pos = [int(pos.x()), int(pos.y())]
        self.update()

    def mouseReleaseEvent(self, e):
        if self._drag is not None and self.pet is not None:
            self.pet.save()                    # 记住位置
        self._drag = None

    def set_data(self, up, down, cpu, ram, tot):
        self._data = (up, down, cpu, ram, tot)
        self._fit()
        self.update()

    def _text_candidates(self):
        """按重要程度从高到低的内容组合；空间不够就逐级裁剪，避免压住任务栏按钮。"""
        up, down, cpu, ram, tot = self._data
        return [
            "↑ %s   ↓ %s   CPU %s   RAM %s   流量 %s" % (up, down, cpu, ram, tot),
            "↑ %s   ↓ %s   CPU %s   RAM %s" % (up, down, cpu, ram),
            "↑ %s   ↓ %s   CPU %s" % (up, down, cpu),
            "↑ %s   ↓ %s" % (up, down),
            "↑ %s" % up,
        ]

    def _fit(self):
        fm = QFontMetrics(self._font)
        self._lh = fm.height() + 2
        avail = self._avail_width()
        self._text = self._text_candidates()[-1]
        for t in self._text_candidates():
            if fm.horizontalAdvance(t) + self._pad * 2 <= avail:
                self._text = t
                break
        w = fm.horizontalAdvance(self._text) + self._pad * 2
        h = self._lh + self._pad
        self.resize(w, h)
        self._place()

    @staticmethod
    def _taskbar_free_span():
        """任务栏上未被按钮占用的水平区间 (x1, x2)；拿不到返回 None。
        Win10：开始/搜索/任务按钮在 ReBarWindow32→MSTaskSwWClass 里，
        右侧托盘为 TrayNotifyWnd / 显示桌面按钮。"""
        try:
            u32 = ctypes.windll.user32

            class RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                            ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

            def rr(h):
                r = RECT()
                u32.GetWindowRect(h, ctypes.byref(r))
                return (r.left, r.right)

            tb = u32.FindWindowW("Shell_TrayWnd", None)
            if not tb:
                return None
            tr = RECT()
            u32.GetWindowRect(tb, ctypes.byref(tr))
            left_used, right_used = tr.left, tr.right
            tray = u32.FindWindowExW(tb, 0, "TrayNotifyWnd", None)
            if tray:
                right_used = min(right_used, rr(tray)[0])
            sd = u32.FindWindowExW(tb, 0, "TrayShowDesktopButtonWClass", None)
            if sd:
                right_used = min(right_used, rr(sd)[0])
            rebar = u32.FindWindowExW(tb, 0, "ReBarWindow32", None)
            if rebar:
                task = u32.FindWindowExW(rebar, 0, "MSTaskSwWClass", None)
                left_used = max(left_used, rr(task)[1] if task else rr(rebar)[1])
            if right_used - left_used < 40:
                return None
            return (left_used, right_used)
        except Exception:
            return None

    def _avail_width(self):
        span = self._taskbar_free_span()
        return (span[1] - span[0]) if span else 10 ** 6

    @staticmethod
    def _taskbar_rects():
        """返回 (任务栏 rect, 托盘 rect)；拿不到则 (None, None)。"""
        try:
            u32 = ctypes.windll.user32

            class RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                            ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

            tb = u32.FindWindowW("Shell_TrayWnd", None)          # 主任务栏
            if not tb:
                return (None, None)
            r = RECT()
            u32.GetWindowRect(tb, ctypes.byref(r))
            tray = u32.FindWindowExW(tb, 0, "TrayNotifyWnd", None)   # 托盘区
            rt = None
            if tray:
                r2 = RECT()
                u32.GetWindowRect(tray, ctypes.byref(r2))
                rt = (r2.left, r2.top, r2.right, r2.bottom)
            return ((r.left, r.top, r.right, r.bottom), rt)
        except Exception:
            return (None, None)

    def _place(self):
        if self.custom_pos is not None:     # 用户拖动过 → 尊重自定义位置
            self._break_embed()
            try:
                u32 = ctypes.windll.user32
                u32.SetWindowPos(int(self.winId()), 0,
                                 int(self.custom_pos[0]), int(self.custom_pos[1]),
                                 self.width(), self.height(), 0x0010 | 0x0040)
            except Exception:
                self.move(int(self.custom_pos[0]), int(self.custom_pos[1]))
            return
        tb, tray = self._taskbar_rects()
        if not tb:
            scr = QApplication.primaryScreen()           # 回退：屏幕底部居中
            if scr is None:
                return
            g = scr.availableGeometry()
            self.move(g.center().x() - self.width() // 2,
                      g.bottom() - self.height() - 4)
            return
        tl, tt, tr, tbb = tb
        horizontal = (tr - tl) >= (tbb - tt)
        span = self._taskbar_free_span() if horizontal else None
        # 任务栏有空位才嵌入；没有空位就解除嵌入（子窗口无法超出父窗口），
        # 改为紧贴任务栏上/下沿悬浮，绝不遮挡任务栏图标。
        can_embed = bool(self.allow_embed and span
                         and (span[1] - span[0]) >= self.width() + 8)
        if can_embed and not self._embedded:
            self.embed()                                 # 内部会再次 _place()
            return
        if (not can_embed) and self._embedded:
            self.unembed()
        if horizontal:
            if can_embed:
                xs = max(span[0] + 4, span[1] - self.width() - 8)
                ys = tt + max(0, ((tbb - tt) - self.height()) // 2)
            else:
                xs = (tray[0] - self.width() - 10) if tray \
                    else (tr - self.width() - 160)
                scr = QApplication.screenAt(
                    QPoint((tl + tr) // 2, (tt + tbb) // 2)) \
                    or QApplication.primaryScreen()
                sg = scr.geometry()
                # 任务栏在屏幕下半 → 贴其上沿；在上半 → 贴其下沿
                ys = (tbb + 2) if tt < sg.center().y() - 10 \
                    else (tt - self.height() - 2)
        else:                                            # 垂直任务栏
            xs = tl + max(0, ((tr - tl) - self.width()) // 2)
            ys = tt + 60
        try:
            u32 = ctypes.windll.user32
            hwnd = int(self.winId())
            SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x0010, 0x0040
            if self._embedded:
                # 已成为任务栏子窗口：坐标要相对父窗口
                u32.SetWindowPos(hwnd, 0, int(xs - tl), int(ys - tt),
                                 self.width(), self.height(),
                                 SWP_NOACTIVATE | SWP_SHOWWINDOW)
            else:
                self.move(int(xs), int(ys))
                u32.SetWindowPos(hwnd, 0, int(xs), int(ys),
                                 self.width(), self.height(),
                                 SWP_NOACTIVATE | SWP_SHOWWINDOW)
        except Exception:
            self.move(int(xs), int(ys))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        p.setOpacity(max(0.15, min(1.0, self.opacity)))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(20, 20, 26, 236))
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 5, 5)
        p.setFont(self._font)
        p.setPen(QColor(235, 235, 240))
        p.drawText(self.rect(), Qt.AlignCenter, self._text)


class PomoClock(QWidget):
    """长条闹钟：番茄钟倒计时显示在这条电子钟里（替代原来的对话气泡）。"""

    CW, CH = 178, 50

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.pet = None
        self.left = 0.0
        self.total = 1.0
        self.alert = False
        self.resize(self.CW, self.CH)

    def set_left(self, left, total=None, alert=False):
        self.left = max(0.0, float(left))
        if total:
            self.total = max(1.0, float(total))
        self.alert = bool(alert)
        self.update()

    def follow(self, pet):
        """贴在角色正上方居中，并限制在屏幕内。"""
        try:
            g = pet.screen_geom()
            x = pet.x() + pet.W // 2 - self.CW // 2
            y = pet.y() + pet.H - pet.MARGIN_BOT - pet.disp_h() - self.CH - 8
            x = max(g.left() + 4, min(x, g.right() - self.CW - 4))
            y = max(g.top() + 4, min(y, g.bottom() - self.CH - 4))
            self.move(int(x), int(y))
        except Exception:
            pass

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        w, h = self.width(), self.height()
        accent = QColor(255, 96, 120) if self.alert else QColor(255, 150, 190)
        if self.alert and int(time.time() * 4) % 2 == 0:
            accent = QColor(255, 236, 120)          # 到点时闪烁
        # 外壳
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(24, 22, 28, 234))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 15, 15)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(accent, 2))
        p.drawRoundedRect(QRectF(1.5, 1.5, w - 3, h - 3), 14, 14)
        # 小番茄
        p.setFont(QFont("Segoe UI Emoji", 16))
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRect(7, 3, 28, h - 12), Qt.AlignCenter, "🍅")
        # 时间（等宽数字）
        mm, ss = divmod(int(self.left + 0.5), 60)
        hh, mm = divmod(mm, 60)
        txt = ("%d:%02d:%02d" % (hh, mm, ss)) if hh else ("%02d:%02d" % (mm, ss))
        ff = QFont(UI_FONT_MONO, 17)
        ff.setBold(True)
        p.setFont(ff)
        p.setPen(accent)
        p.drawText(QRect(36, 1, w - 44, h - 13), Qt.AlignCenter, txt)
        # 底部进度条
        ratio = 1.0 - min(1.0, self.left / self.total)
        bw = w - 22
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 48))
        p.drawRoundedRect(QRectF(11, h - 11, bw, 5), 2.5, 2.5)
        p.setBrush(accent)
        p.drawRoundedRect(QRectF(11, h - 11, bw * ratio, 5), 2.5, 2.5)


class ModAPI:
    """给 mod 用的接口。mod 通过它注册钩子、读写养成数值、加菜单/台词等，
    也可以通过 api.pet 直接访问主程序实例（全权控制）。

    可用钩子：on_tick / on_state_change / on_click / on_draw / add_menu_action
    """
    def __init__(self, pet, mod_dir=None, mod_id=None):
        self.pet = pet                 # 主程序实例（想改什么都可以）
        self.app = pet                 # 别名，方便阅读
        self.dir = mod_dir             # 本模组目录(Path)：可读写自己的素材 / 配置
        self.id = mod_id or "mod"
        self._ticks = []
        self._state_hooks = []
        self._click_hooks = []
        self._draw_hooks = []
        self._caps_hooks = []
        self._peek_hooks = []
        self._drop_hooks = []          # 拖放文本/网址：fn(text) -> True 表示已接管
        self._menu_actions = []
        self._top_menu_actions = []    # 顶层右键菜单项（不放进「🧩 模组」子菜单）
        self._timers = []              # [间隔秒, 下次触发时间, 回调]

    # ---------- 基础 ----------
    def log(self, *args):
        print("[MOD]", *args, flush=True)

    def say(self, text, life=3.0):
        self.pet.say(text, life)

    def get_state(self):
        return self.pet.state

    def set_state(self, name, seconds=None):
        """切换状态。若 name 是已注册的自定义状态，会走其 enter 钩子。"""
        pet = self.pet
        if name in getattr(pet, "mod_states", {}):
            pet.enter_state(name)
        else:
            pet.state = name
        if seconds is not None:
            pet.state_left = seconds

    def add_particle(self, text, x=None, y=None, **kw):
        x = self.pet.W / 2 if x is None else x
        y = self.pet.H - self.pet.MARGIN_BOT - 40 if y is None else y
        self.pet.add_particle(text, x, y, **kw)

    # ---------- 养成数值 ----------
    def get_stat(self, key):
        return getattr(self.pet, key, None)

    def set_stat(self, key, value):
        if hasattr(self.pet, key):
            setattr(self.pet, key, value)
            return True
        return False

    def save(self):
        self.pet.save()

    # ---------- 台词 / 菜单 ----------
    def add_lines(self, key, lines):
        """往某个台词分类追加台词，如 api.add_lines("idle", ["模组加的一句话"])"""
        LINES.setdefault(key, [])
        LINES[key].extend(lines)

    def add_menu_action(self, label, callback):
        """在右键菜单里加一项：api.add_menu_action("我的模组", lambda: ...)"""
        self._menu_actions.append((label, callback))

    # ---------- 定时器 / 统一钩子 ----------
    def every(self, seconds, callback):
        """每 seconds 秒自动调用一次 callback()。"""
        self._timers.append([float(seconds), time.time() + float(seconds), callback])

    def on(self, event, callback):
        """统一注册钩子：event ∈ tick / state_change / click / draw / caps / peek / drop"""
        table = {"tick": self._ticks, "state_change": self._state_hooks,
                 "click": self._click_hooks, "draw": self._draw_hooks,
                 "caps": self._caps_hooks, "peek": self._peek_hooks,
                 "drop": self._drop_hooks}
        if event in table:
            table[event].append(callback)
        else:
            self.log("未知事件名：%s（可用：tick/state_change/click/draw/caps/peek/drop）"
                     % event)

    # ---------- 配置 / 素材 ----------
    def config_path(self):
        return (self.dir / "config.json") if self.dir else None

    def load_config(self, default=None):
        p = self.config_path()
        if p is not None and p.exists():
            try:
                return json.loads(p.read_text("utf-8"))
            except Exception as ex:
                self.log("读取配置失败：%s" % ex)
        return dict(default or {})

    def save_config(self, cfg):
        p = self.config_path()
        if p is None:
            return
        try:
            p.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), "utf-8")
        except Exception as ex:
            self.log("保存配置失败：%s" % ex)

    def asset(self, name):
        """读取本模组目录下的图片，返回 QPixmap（不存在返回 None）。"""
        if self.dir is None:
            return None
        f = self.dir / name
        return QPixmap(str(f)) if f.exists() else None

    # ---------- 顶层菜单 / 素材替换 / 自定义状态机 ----------
    def add_top_menu(self, label, callback):
        """在右键菜单**顶层**（而非「🧩 模组」子菜单里）加一项。"""
        self._top_menu_actions.append((label, callback))

    def set_sprite(self, key, sprite):
        """替换 / 新增 / 删除立绘素材，立即生效。
        sprite 可为 QPixmap、图片路径(str/Path)，或传 None 表示删除该素材。"""
        pet = self.pet
        if sprite is None:
            pet.src.pop(key, None)
        else:
            pm = sprite
            if isinstance(sprite, (str, bytes)) or hasattr(sprite, "__fspath__"):
                pm = QPixmap(str(sprite))
            if pm is None or pm.isNull():
                self.log("素材无效：%s" % key)
                return False
            pet.src[key] = pm
        pet._scaled_cache = None       # 让缩放缓存重建，替换立绘立刻可见
        pet._popup_cache = {}
        pet.update()
        return True

    def load_sprite(self, key, filename):
        """从本模组目录加载图片并注册为素材，例如 load_sprite("eat", "my_eat.png")。"""
        pm = self.asset(filename)
        if pm is None or pm.isNull():
            self.log("找不到素材文件：%s" % filename)
            return False
        return self.set_sprite(key, pm)

    def get_sprite(self, key):
        return self.pet.src.get(key)

    def register_state(self, name, update=None, enter=None, exit=None,
                       sprite=None, duration=None):
        """注册一个自定义状态，接入桌宠状态机。
        - update(pet, dt)      该状态下每帧调用
        - enter(pet)/exit(pet) 进入 / 离开时调用
        - sprite               该状态绘制用哪个素材 key（默认与状态同名）
        - duration             自动结束的秒数（None = 不自动结束，需自己切走）
        之后用 api.set_state(name) 进入这个状态。
        """
        self.pet.mod_states[name] = {
            "update": update, "enter": enter, "exit": exit,
            "sprite": sprite or name, "duration": duration, "api": self,
        }
        self.log("已注册状态：%s" % name)

    def unregister_state(self, name):
        self.pet.mod_states.pop(name, None)

    def leave_state(self):
        """立刻离开当前自定义状态（回 idle，会调用 exit 钩子）。"""
        if self.pet.state in self.pet.mod_states:
            self.pet._leave_mod_state()

    # ---------- 钩子注册 ----------
    def on_tick(self, fn):
        """每帧调用：fn(dt)"""
        self._ticks.append(fn)

    def on_state_change(self, fn):
        """状态变化时调用：fn(old_state, new_state)"""
        self._state_hooks.append(fn)

    def on_click(self, fn):
        """点击身体部位时调用：fn(part)，part ∈ ear/face/tummy/skirt/feet"""
        self._click_hooks.append(fn)

    def on_draw(self, fn):
        """绘制末尾调用：fn(painter)，可自己往上画东西"""
        self._draw_hooks.append(fn)

    def on_drop(self, fn):
        """拖放文本/网址到桌宠时调用：fn(text)，返回 True 表示已接管"""
        self._drop_hooks.append(fn)

    # ---------- 内部：触发钩子（异常隔离，单个 mod 出错不影响主程序）----------
    def _fire(self, hooks, *args):
        for fn in hooks:
            try:
                fn(*args)
            except Exception as ex:
                print("[MOD] 钩子出错 %s: %s" % (fn, ex), flush=True)

    def fire_tick(self, dt):
        self._fire(self._ticks, dt)
        now = time.time()
        for rec in self._timers:          # 简易定时器
            if now >= rec[1]:
                rec[1] = now + rec[0]
                self._fire([rec[2]])

    def fire_caps(self, upper):
        self._fire(self._caps_hooks, upper)

    def fire_peek(self, side):
        self._fire(self._peek_hooks, side)

    def fire_state_change(self, old, new):
        self._fire(self._state_hooks, old, new)

    def fire_click(self, part):
        self._fire(self._click_hooks, part)

    def fire_draw(self, painter):
        self._fire(self._draw_hooks, painter)

    def fire_drop(self, text):
        """拖放文本/网址：fn(text) 返回 True 表示该模组已接管（主程序不再"吃文件"）。"""
        handled = False
        for fn in list(self._drop_hooks):
            try:
                if fn(text):
                    handled = True
            except Exception as ex:
                print("[MOD] 钩子出错 %s: %s" % (fn, ex), flush=True)
        return handled


class Pet(QWidget):
    SIZE_ORDER = ["small", "medium", "large"]
    SIZES = {"small": 150, "medium": 210, "large": 285}
    MARGIN_X, MARGIN_TOP, MARGIN_BOT = 130, 150, 26

    # ---- 走路动画微调区（可自由细调）----
    # 6 帧完整步态（用户提供 left/right 各 6 张），循环约 0.54s
    WALK_SEQ = tuple(range(1, 7))
    WALK_FRAME_TIME = 0.09     # 每帧时长(秒)，6帧循环约0.54s（约11fps）
    WALK_DY = (1.5, 3.5, 0.5, -2.0, -3.0, 1.5)        # 每帧身体升降(px)
    WALK_SHADOW = (0.55, 0.58, 0.57, 0.52, 0.50, 0.55)  # 每帧影子宽度系数
    WALK_TILT = 2.2            # 行走前倾角度(度)，0 为不倾斜
    WALK_VX = 72.0             # 水平移动速度(px/秒)

    # ---- 养成微调区 ----
    AUTO_SLEEP_SEC = 180       # 多久不理她会自己睡着(秒)
    SICK_HEALTH = 40           # 健康低于此值自动生病
    TOILET_PERIOD = 240        # 大约每多少秒会想上厕所(秒)

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.topmost = True

        # ---- 素材 ----
        self.src = {
            "idle": pm_or_none("idle.png"),
            "left": pm_or_none("left.png"),
            "right": pm_or_none("right.png"),
            "back": pm_or_none("back.png"),
            "chibi": pm_or_none("chibi.png"),
            "sleep": pm_or_none("sleep.png"),
            "eat": pm_or_none("eat.png"),
            "happy": pm_or_none("happy.png"),
        }
        if self.src["idle"] is None:
            QMessageBox.critical(None, NAME, "缺少素材文件 assets/idle.png")
            raise SystemExit(1)
        for k in ("left", "right"):
            if self.src[k] is None:
                self.src[k] = self.src["idle"]
        if self.src["sleep"] is None:      # 睡觉兜底: 压暗的立绘
            dark = QPixmap(self.src["idle"])
            p = QPainter(dark)
            p.setCompositionMode(QPainter.CompositionMode_SourceAtop)
            p.fillRect(dark.rect(), QColor(25, 20, 60, 150))
            p.end()
            self.src["sleep"] = dark
        # 走路循环帧：朝右 r 帧 + 朝左 l 帧（各自 6 张，独立素材，不再镜像）
        for i in range(1, 7):
            self.src[f"wr{i}"] = pm_or_none(f"walk_r{i}.png")
            self.src[f"wl{i}"] = pm_or_none(f"walk_l{i}.png")
        self.walk_frames = all(self.src[f"wr{i}"] is not None
                               and self.src[f"wl{i}"] is not None
                               for i in range(1, 7))
        # 日常状态素材（洗澡/生病/上厕所/吃药）与三种吃相
        for k in ("bath", "sick", "toilet", "medicine",
                  "eat_dango", "eat_cookie", "eat_bento",
                  "peek_left", "peek_right", "peek_top",
                  "caps_upper", "caps_lower", "pomo_alert", "bye",
                  "skin_spring", "skin_christmas", "skin_midautumn",
                  "skin_birthday", "lick", "dj", "drag",
                  "skin_new_year", "skin_valentine", "skin_women",
                  "skin_april_fool", "skin_labor", "skin_youth",
                  "skin_children", "skin_halloween", "skin_xmas_eve",
                  "skin_lantern", "skin_qixi", "skin_chongyang", "angry"):
            self.src[k] = pm_or_none(k + ".png")
        # 24 节气皮肤（按节气名动态加载）
        for _n, _line, _emo in SOLAR_TERMS:
            self.src["skin_term_%s" % _n] = pm_or_none("skin_term_%s.png" % _n)

        # ---- 状态 ----
        self.state = "idle"        # idle/walk/drag/fall/sleep/eat/play/back
        self.facing = 1
        self.t = 0.0
        self.rot = 0.0
        self.sx = 1.0
        self.sy = 1.0
        self.dy = 0.0
        self.vy = 0.0
        self.vx = 0.0             # 扔飞的水平速度（拖拽松手时的惯性）
        self._last_drag_t = 0.0   # 拖动速度采样时间戳
        self.throw_t = 0.0        # 扔飞持续时长（用于连续旋转，避免转动跳变）
        self.bounces = 0
        self.lick_left = 0.0      # 舔屏动画剩余时间（>0 表示正在舔）
        self._night_said = ""     # 凌晨提醒已说过的日期（防止重复）
        self._daynight_check = 0.0
        self._last_beat = 0.0     # 上一帧低频能量（拍点检测）
        # 摸鱼监测 + 久坐提醒（键鼠空闲/活跃时长）
        self._idle_check = 0.0
        self._idle_said_at = 0.0
        self._active_since = None
        self._sit_said_at = 0.0
        # 羁绊/好感系统
        self.affection = 0
        self._aff_stage = 0
        # 互动彩蛋
        self._poke_times = []      # 连戳时间戳（炸毛检测）
        self.bubbles = []          # 桌面泡泡 [{x,y,r,vy,t,life}]
        # 音乐模式
        self.music_mode = False   # 音乐模式开关
        self.music_beat = 0.0     # 低频能量（节拍 0~1）
        self.music_pitch = 0.0    # 高频能量（音调 0~1）
        self.music_bands = [0.0] * 8   # 8 个频段能量（每个节奏圈独立大小）
        self.music_peak = None         # 各频段历史峰值（独立归一化）
        self.music_low_sens = 1.0      # 低音灵敏度（0.2~3.0）
        self.music_high_sens = 1.0     # 高音灵敏度（0.2~3.0）
        self.music_level = 0.0    # 总音量（0~1，静音诊断用）
        self.music_ready = False
        self.music_error = ""
        self.music_device_name = ""   # 用户选择的回环设备名（空=默认扬声器）
        self.music_device_used = ""   # 实际使用的设备名
        self._music_stop = threading.Event()
        self._music_thread = None
        self._beat_flash = 0.0    # 当前拍点闪烁强度（用于节奏灯）
        self._beat_avg = 0.0      # 低频能量滚动均值（动态拍点阈值）
        self._last_beat_t = 0.0   # 上一拍时间（最小拍间隔）
        self._music_on_t = 0.0    # 音乐模式开启时刻（静音诊断用）
        self._last_nosound_say = 0.0
        self.walk_vx = 0.0
        self.walk_target = 0.0
        self.walk_done = 0.0
        self.walk_t = 0.0          # 走路动画计时
        self.walk_frame = 1        # 当前走路帧 (1-6)
        self.state_left = 0.0
        self.squash = 0.0
        self.wiggle = 0.0
        self.zzz_timer = 0.0
        self.particles = []        # {text,x,y,vx,vy,t,life,color,size}
        self._particle_cache = {}  # 粒子 emoji 预渲染缓存 (text,size,color)->QPixmap
        # 渲染缓存：内容不变时直接贴图，避免每帧重复做文本布局
        self._sysmon_pm, self._sysmon_key = None, None
        self._bubble_pm, self._bubble_key, self._bubble_bh = None, None, 0
        self._note_pm, self._note_key = None, None      # 便签渲染缓存
        self._walk_acc = 0.0        # 走路位移累积（够阈值才移动窗口）
        # 边缘探头
        self.hover = False          # 鼠标是否悬浮在桌宠上方
        self.peek_side = 0          # 0=不探头 -1=左边缘探头 1=右边缘探头
        # 系统信息个性化
        self.sysmon_items = ["cpu", "ram", "net_in", "net_out"]
        self.sysmon_pos = "auto"    # auto/left/right/top/bottom
        # CapsLock 提示
        self.caps_last = None       # 上次的 CapsLock 状态（首次不提示）
        self.caps_upper = False
        self.caps_left = 0.0
        self.prev_state = "idle"    # 大小写提示结束后回到的状态
        # 探头露出距离（占角色宽/高的比例），上/左/右各自独立可调
        self.peek_dist = {"left": self.PEEK_EDGE, "right": self.PEEK_EDGE, "top": 1.0}
        # 我没空模式（原地自力更生，不会到处乱跑）
        self.busy_mode = False
        # 实用功能
        self.note = ""              # 桌面便签文字（空=无便签）
        # 番茄钟
        self.pomo_end = 0.0         # 结束时间戳（time.time），0=未启动
        self.pomo_total = 0.0       # 本次总时长(秒)
        self.pomo_alert_left = 0.0  # 到点提醒的剩余展示时长
        self.pomo_last_sec = -1     # 上次刷新的剩余秒数
        self.pomo_clock = None      # 长条闹钟窗口（番茄钟倒计时）
        self.pomo_notify = True     # 番茄钟结束时是否发系统通知
        self._prev_state = "idle"   # 上一帧状态（检测「活动结束回到 idle」）
        self._just_unpeeked = False # 刚从探头探回来（单击不再触发部位点击）
        # 模组(mod)支持
        self.available_mods = []    # 扫描到的模组信息
        self.enabled_mods = []      # 用户勾选启用的模组 id
        self.loaded_mods = []       # 已加载的模组模块
        self.mod_apis = []          # 每个已加载模组一个 ModAPI（各自独立目录/配置）
        self.mod_api = None         # 兼容：有模组加载时指向首个 api
        self.mod_states = {}        # 模组注册的自定义状态：name -> handler
        self._last_state = "idle"   # 用于触发状态变化钩子
        self.setAcceptDrops(True)   # 允许把文件拖给桌宠
        self.bubble = None         # {text,t,life}
        self.popup = None          # {key,t,life}
        self.hunger = 80.0
        self.mood = 80.0
        self.hyg = 85.0           # 卫生
        self.health = 95.0        # 健康
        self.toilet_need = 30.0   # 便意
        self.exp = 0
        self.level = 1
        self.size_key = "medium"
        self.opacity = 1.0
        self.pending_food = None
        self.eat_key = None       # 当前吃相素材 key
        self.show_sysmon = False  # 系统监控面板
        self.show_taskbar = False # 任务栏监控条
        self.embed_taskbar = True # 是否把监控条嵌进系统任务栏（子窗口）
        self.tbmon = None         # 任务栏监控窗口
        self.tbmon_pos = None     # 监控条自定义位置 [x, y]（拖动后记住）
        self.tbmon_locked = False # 监控条是否锁定（锁定后不可拖动）
        self.tbmon_opacity = 0.9  # 监控条不透明度
        self.tray = None          # 托盘图标（由 main 注入，便于运行时刷新）
        self.daily_skin = None    # 当日节日皮肤 key（None=默认皮肤）
        self.preview_skin = None  # 手动预览/刚导入的皮肤（优先级高于当日皮肤）
        self.festival_skins = {}  # 用户为节日导入的皮肤 {fest_key: skin_key}
        self._fest_key = None     # 已提醒过的日子 key（避免重复提醒）
        self._fest_check = 0.0    # 下次检查「今天是什么日子」的时间
        self.net_total = 0.0      # 本次开机累计流量（收+发，字节）
        self.net_recv_total = 0   # 本次开机累计接收（字节）
        self.net_sent_total = 0   # 本次开机累计发送（字节）
        self.net_nic = None       # 监控的网卡（None = 全部）
        self.sysmon = SysMon()
        self.sys_cpu = None
        self.sys_ram = (0, 0.0, 0.0)
        self.dizzy = 0.0          # 摔晕计时
        self.fall_start = 0.0     # 开始下落时的脚底高度
        self.last_interact = time.time()
        self.next_act = time.time() + random.randint(5, 10)
        self.next_toilet = time.time() + self.TOILET_PERIOD // 2
        self.pressed = False
        self.moved = False
        self.drag_offset = None
        self.drag_swing = 0.0        # 拖拽时身体惯性摆动（-1~1，头跟鼠标身体滞后）
        self._scaled_cache = None
        self._popup_cache = {}

        self.load_save()
        self.setFixedSize(self.W, self.H)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(40)      # 25fps：桌宠动画足够流畅，同时明显降低 CPU
        self.stat_timer = QTimer(self)
        self.stat_timer.timeout.connect(self.stats_step)
        self.stat_timer.start(5000)
        self.save_timer = QTimer(self)
        self.save_timer.timeout.connect(self.save)
        self.save_timer.start(30000)
        self.sys_timer = QTimer(self)
        self.sys_timer.timeout.connect(self.update_sys)
        self.sys_timer.start(1000)

        self.load_mods()          # 扫描并加载用户启用的模组
        self._ensure_taskbar()    # 上次若开着任务栏监控就恢复
        self._startup_peek()      # 上次关在屏幕边上 → 自动吸附探头

    def update_sys(self):
        """每秒采集一次系统指标（面板 / 任务栏监控按需重绘）。"""
        self.sys_cpu = self.sysmon.cpu()
        self.sys_ram = self.sysmon.ram()
        self.sysmon.net(self.net_nic)
        # 本次开机累计流量：直接取系统网卡计数器
        # （等同「控制面板 → 网络和共享中心」里的「已发送/已接收 字节」）
        self.net_sent_total, self.net_recv_total = self.sysmon.io_totals(self.net_nic)
        self.net_total = self.net_recv_total + self.net_sent_total
        if self.show_sysmon:
            self.update()
        if self.tbmon is not None:
            self._update_taskbar()

    # ---- 任务栏监控条 ----
    def _ensure_taskbar(self):
        """按 show_taskbar 创建 / 销毁任务栏监控窗口。"""
        if self.show_taskbar:
            if self.tbmon is None:
                self.tbmon = TaskbarMonitor()
                self.tbmon.pet = self
                self.tbmon.allow_embed = self.embed_taskbar
                self.tbmon.show()          # 先显示，winId 才有效
                self.tbmon._place()
            # 每次都同步设置（改存档 / 设置窗口后即时生效）
            self.tbmon.locked = self.tbmon_locked
            self.tbmon.opacity = self.tbmon_opacity
            if isinstance(self.tbmon_pos, (list, tuple)) \
                    and len(self.tbmon_pos) == 2:
                np_ = (int(self.tbmon_pos[0]), int(self.tbmon_pos[1]))
                if self.tbmon.custom_pos != np_:
                    self.tbmon.custom_pos = np_
                    self.tbmon._place()
            self._update_taskbar()
            self.tbmon.show()
        elif self.tbmon is not None:
            self.tbmon.unembed()
            self.tbmon.hide()
            self.tbmon.deleteLater()
            self.tbmon = None

    def _update_taskbar(self):
        if self.tbmon is None:
            return
        self.tbmon.ensure_parent()      # explorer 重启后重新嵌入
        mm = self.sysmon
        up = fmt_speed(mm.net_out) if mm.net_ok else "--"
        down = fmt_speed(mm.net_in) if mm.net_ok else "--"
        cpu = self.sys_cpu
        cpu_s = (f"{cpu:.0f}%" if cpu is not None else "--")
        load, used, total = self.sys_ram
        ram_s = f"{used:.1f}/{total:.0f}G"
        self.tbmon.set_data(up, down, cpu_s, ram_s, fmt_bytes(self.net_total))

    # ============ 几何 ============
    def screen_geom(self):
        # 跟随桌宠「当前所在屏幕」，多显示器下可自由拖到任意屏幕
        s = QApplication.screenAt(self.geometry().center())
        if s is None:
            s = QApplication.primaryScreen()
        return s.availableGeometry()

    def floor_y(self):
        return self.screen_geom().bottom() + 1

    def disp_h(self):
        return self.SIZES[self.size_key]

    def set_size(self, key, initial=False):
        self.size_key = key
        self._scaled_cache = None
        self._popup_cache = {}
        dh = self.disp_h()
        dw = int(self.src["idle"].width() * dh / self.src["idle"].height())
        self.W = dw + self.MARGIN_X * 2
        self.H = dh + self.MARGIN_TOP + self.MARGIN_BOT
        self.setFixedSize(self.W, self.H)
        if not initial:
            self.clamp_into_screen(keep_feet=True)
        self.update()

    def body_w(self):
        """角色本体宽度（窗口含左右透明边距）。"""
        return self.W - self.MARGIN_X * 2

    def clamp_into_screen(self, keep_feet=False):
        g = self.screen_geom()
        feet = (self.y() + self.H - self.MARGIN_BOT) if keep_feet else self.floor_y()
        feet = min(feet, self.floor_y())
        # 透明边距允许溢出屏幕，角色本体要能贴到屏幕左右边缘
        x = max(g.left() - self.MARGIN_X,
                min(self.x(), g.right() - self.MARGIN_X - self.body_w() + 1))
        self.move(x, feet - (self.H - self.MARGIN_BOT))

    def put_feet(self, feet_y=None, cx=None):
        g = self.screen_geom()
        if feet_y is None:
            feet_y = self.floor_y()
        if cx is None:
            cx = self.x() + self.W // 2
        half = self.body_w() / 2      # 以角色本体中心钳制，而不是窗口
        cx = max(g.left() + half - 1, min(cx, g.right() - half + 1))
        feet_y = min(feet_y, self.floor_y())
        self.move(round(cx - self.W // 2), feet_y - (self.H - self.MARGIN_BOT))

    def head_pos(self):
        return int(self.W / 2), int(self.H - self.MARGIN_BOT - self.disp_h() * 0.82)

    # ============ 存档 ============
    def load_save(self):
        data = {}
        if SAVE_FILE.exists():
            try:
                data = json.loads(SAVE_FILE.read_text("utf-8"))
            except Exception:
                data = {}
        self.hunger = float(data.get("hunger", 80))
        self.mood = float(data.get("mood", 80))
        self.hyg = float(data.get("hyg", 85))
        self.health = float(data.get("health", 95))
        self.toilet_need = float(data.get("toilet_need", 30))
        self.exp = int(data.get("exp", 0))
        self.level = int(data.get("level", 1))
        self.show_sysmon = bool(data.get("show_sysmon", False))
        self.show_taskbar = bool(data.get("show_taskbar", False))
        self.embed_taskbar = bool(data.get("embed_taskbar", True))
        self.tbmon_pos = data.get("tbmon_pos") or None
        self.tbmon_locked = bool(data.get("tbmon_locked", False))
        self.tbmon_opacity = float(data.get("tbmon_opacity", 0.9))
        self.pomo_notify = bool(data.get("pomo_notify", True))
        self.music_mode = bool(data.get("music_mode", False))
        self.music_device_name = str(data.get("music_device_name", ""))
        self.music_low_sens = float(data.get("music_low_sens", 1.0))
        self.music_high_sens = float(data.get("music_high_sens", 1.0))
        self.affection = int(data.get("affection", 0))
        self._aff_stage = int(data.get("aff_stage", 0))
        self.note = str(data.get("note", ""))
        global UI_FONT_FAMILY
        _uf = data.get("ui_font")
        if _uf:
            UI_FONT_FAMILY = _uf
        fs = data.get("festival_skins")
        self.festival_skins = dict(fs) if isinstance(fs, dict) else {}
        self._load_custom_skins()          # 载入用户导入的节日皮肤
        self.net_total = float(data.get("net_total", 0.0))
        self.net_nic = data.get("net_nic", None)
        # 系统信息个性化（显示项 / 位置）
        items = data.get("sysmon_items")
        if isinstance(items, list):
            self.sysmon_items = [k for k in items if k in SYSMON_ITEM_LABELS]
            if not self.sysmon_items:
                self.sysmon_items = list(SYSMON_ITEM_LABELS)
            # 老存档没有「流量」项时补上一次（带迁移标记，之后尊重用户的取消勾选）
            elif "flow" not in self.sysmon_items and not data.get("flow_migrated"):
                self.sysmon_items.append("flow")
        pos = data.get("sysmon_pos", "auto")
        self.sysmon_pos = pos if pos in SYSMON_POSITIONS else "auto"
        # 探头露出距离 / 我没空模式
        pd = data.get("peek_dist")
        if isinstance(pd, dict):
            for k in ("left", "right", "top"):
                if isinstance(pd.get(k), (int, float)):
                    self.peek_dist[k] = max(0.10, min(1.50, float(pd[k])))
        self.busy_mode = bool(data.get("busy_mode", False))
        self.enabled_mods = [x for x in data.get("enabled_mods", [])
                             if isinstance(x, str)]
        self.size_key = data.get("size", "medium")
        if self.size_key not in self.SIZES:
            self.size_key = "medium"
        self.set_size(self.size_key, initial=True)
        # 离线衰减
        hours = max(0.0, (time.time() - data.get("ts", time.time())) / 3600.0)
        self.hunger = max(0.0, self.hunger - hours * 6)
        self.mood = max(0.0, self.mood - hours * 5)
        self.hyg = max(0.0, self.hyg - hours * 4)
        self.health = max(0.0, min(100.0, self.health - hours * 2))
        self.opacity = float(data.get("opacity", 1.0))
        self.setWindowOpacity(self.opacity)
        if "x" in data and "feet" in data:
            x = int(data["x"])
            feet = int(data["feet"])
        else:
            g = self.screen_geom()
            x = g.right() - self.W - 60
            feet = self.floor_y()
        # 先把窗口放到存档坐标，screen_geom 才能识别所在屏幕（多屏恢复）
        self.move(x, feet - (self.H - self.MARGIN_BOT))
        self.put_feet(feet_y=feet, cx=x + self.W // 2)
        self.say(random.choice(LINES["greet"]), 4.0)

    def save(self):
        try:
            SAVE_FILE.write_text(json.dumps({
                "x": self.x(), "feet": self.y() + self.H - self.MARGIN_BOT,
                "size": self.size_key, "opacity": self.opacity,
                "hunger": round(self.hunger, 1), "mood": round(self.mood, 1),
                "hyg": round(self.hyg, 1), "health": round(self.health, 1),
                "toilet_need": round(self.toilet_need, 1),
                "show_sysmon": self.show_sysmon, "net_nic": self.net_nic,
                "show_taskbar": self.show_taskbar,
                "embed_taskbar": self.embed_taskbar,
                "tbmon_pos": self.tbmon_pos,
                "tbmon_locked": self.tbmon_locked,
                "tbmon_opacity": self.tbmon_opacity,
                "festival_skins": self.festival_skins,
                "ui_font": UI_FONT_FAMILY,
                "pomo_notify": self.pomo_notify,
                "music_mode": self.music_mode,
                "music_device_name": self.music_device_name,
                "music_low_sens": self.music_low_sens,
                "music_high_sens": self.music_high_sens,
                "affection": self.affection, "aff_stage": self._aff_stage,
                "note": self.note,
                "net_total": round(self.net_total, 0),
                "sysmon_items": self.sysmon_items, "sysmon_pos": self.sysmon_pos,
                "flow_migrated": True,
                "peek_dist": self.peek_dist, "busy_mode": self.busy_mode,
                "enabled_mods": self.enabled_mods,
                "exp": self.exp, "level": self.level, "ts": time.time(),
            }, ensure_ascii=False, indent=1), "utf-8")
        except Exception:
            pass

    # ============ 表现 ============
    def say(self, text, life=3.4):
        if self.busy_mode:      # 我没空模式：完全静默，一句话都不说
            return
        if self.state != "sleep":
            self.bubble = {"text": text, "t": 0.0, "life": life}

    MAX_PARTICLES = 48

    def _process_skin_image(self, path, cut_white):
        """导入皮肤：读取图片 → 可选抠白底（扫描线泛洪，不依赖 PIL）→ 统一高 560。
        返回 QImage；读取失败/异常向上抛。"""
        import numpy as np
        from collections import deque
        img = QImage(path)
        if img.isNull():
            raise ValueError("图片读取失败")
        img = img.convertToFormat(QImage.Format_RGBA8888)
        w, h = img.width(), img.height()
        bpl = img.bytesPerLine()
        arr = np.frombuffer(bytes(img.constBits()), dtype=np.uint8)
        arr = arr[:bpl * h].reshape(h, bpl)[:, :w * 4].reshape(h, w, 4).copy()
        has_alpha = int(arr[..., 3].min()) < 250
        if cut_white and not has_alpha:
            # 白底抠除：扫描线泛洪（从四角种子，只抠与边缘连通的近白区域，
            # 不会误伤角色内部的白色，如白卫衣）
            near = ((arr[..., 0] > 225) & (arr[..., 1] > 225) &
                    (arr[..., 2] > 225))
            mask = np.zeros((h, w), bool)
            dq = deque()
            for sy, sx in ((0, 0), (0, w - 1), (h - 1, 0), (h - 1, w - 1)):
                if near[sy, sx] and not mask[sy, sx]:
                    mask[sy, sx] = True
                    dq.append((sy, sx))
            while dq:
                y, x = dq.popleft()
                xa = x
                while xa > 0 and near[y, xa - 1] and not mask[y, xa - 1]:
                    xa -= 1
                    mask[y, xa] = True
                xb = x
                while xb < w - 1 and near[y, xb + 1] and not mask[y, xb + 1]:
                    xb += 1
                    mask[y, xb] = True
                for ny in (y - 1, y + 1):
                    if 0 <= ny < h:
                        row = near[ny, xa:xb + 1] & ~mask[ny, xa:xb + 1]
                        idx = np.nonzero(row)[0]
                        if idx.size:
                            mask[ny, xa + idx[0]:xa + idx[-1] + 1] = True
                            gaps = np.diff(idx)
                            starts = [idx[0]] + list(idx[1:][gaps > 1])
                            for s0 in starts:
                                dq.append((ny, xa + s0))
            # 安全校验：若误抠超过 92%（整图几乎透明）则回退不抠
            if mask.mean() < 0.92:
                arr[mask, 3] = 0
        # 裁剪到非透明内容的边界框
        ys, xs = np.nonzero(arr[..., 3])
        if ys.size:
            arr = arr[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        h2, w2 = arr.shape[:2]
        out = QImage(arr.tobytes(), w2, h2, w2 * 4, QImage.Format_RGBA8888)
        nh = 560                                   # 统一高度，保持比例
        nw = max(1, int(w2 * nh / h2))
        return out.scaled(nw, nh, Qt.IgnoreAspectRatio,
                          Qt.SmoothTransformation)

    def add_particle(self, text, x, y, color=(255, 96, 156), size=20, life=1.4,
                     vy=-46, vx=0):
        # 限制粒子总数，避免洗澡泡泡等持续生成无限累积导致 CPU 飙升卡死
        if len(self.particles) >= self.MAX_PARTICLES:
            self.particles.pop(0)
        self.particles.append({"text": text, "x": x, "y": y, "vx": vx, "vy": vy,
                               "t": 0.0, "life": life, "color": color, "size": size})

    def _emoji_pixmap(self, text, size, color):
        """粒子 emoji 预渲染成 Pixmap 并缓存：避免每帧每粒子新建 QFont，
        且 Windows 彩色 emoji 文本渲染极慢，洗澡泡泡大量生成时直接卡死。"""
        key = (text, size, color)
        pm = self._particle_cache.get(key)
        if pm is not None:
            return pm
        s = max(8, int(size * 2.2))
        pm = QPixmap(s, s)
        pm.fill(Qt.transparent)
        pp = QPainter(pm)
        f = QFont("Segoe UI Emoji" if len(text) > 1 else "Segoe UI", size)
        f.setBold(True)
        pp.setFont(f)
        pp.setPen(QColor(*color, 255))
        pp.drawText(pm.rect(), Qt.AlignCenter, text)
        pp.end()
        self._particle_cache[key] = pm
        return pm

    def show_popup(self, key, life=1.4):
        if self.src.get(key) is not None:
            self.popup = {"key": key, "t": 0.0, "life": life}

    def interact(self):
        self.last_interact = time.time()

    def _last_input_sec(self):
        """系统键鼠最后输入距现在的秒数（Windows GetLastInputInfo）。失败返回 -1。"""
        try:
            import ctypes
            class LII(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
            lii = LII()
            lii.cbSize = ctypes.sizeof(LII)
            if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
                tick = ctypes.windll.kernel32.GetTickCount()
                return max(0.0, (tick - lii.dwTime) / 1000.0)
        except Exception:
            pass
        return -1.0

    def _idle_tick(self):
        """摸鱼监测：键鼠长时间空闲→吐槽；持续活跃超 1 小时→久坐提醒。"""
        idle = self._last_input_sec()
        if idle < 0:
            return
        now = time.time()
        # 摸鱼：空闲超 20 分钟，且距上次吐槽 > 15 分钟
        if idle > 20 * 60 and not self.busy_mode \
                and now - self._idle_said_at > 15 * 60:
            self._idle_said_at = now
            self._active_since = None
            self.say("主人，都 %d 分钟没动啦，是不是在摸鱼呀？" % (idle // 60),
                     4.5)
        # 久坐：持续活跃（几乎一直有输入）超 1 小时
        if idle < 30:
            if self._active_since is None:
                self._active_since = now
            elif now - self._active_since > 60 * 60 \
                    and now - self._sit_said_at > 30 * 60 \
                    and not self.busy_mode:
                self._sit_said_at = now
                self.say("坐了一个多小时啦，起来伸个懒腰、喝口水嘛～", 4.0)
        else:
            self._active_since = None

    # 羁绊阶段：好感度解锁（0 陌生 → 100 熟悉 → 300 亲密 → 800 羁绊）
    AFF_STAGES = [(0, "陌生"), (100, "熟悉"), (300, "亲密"), (800, "羁绊")]
    AFF_LINES = {
        1: ["嘿嘿，你好像越来越喜欢摸我头了哦～", "我感觉我们更熟了一点点呢"],
        2: ["和你在一起好开心呀，主人～", "我们现在是很好的朋友了吧！"],
        3: ["最喜欢主人啦！要一直在一起哦～", "羁绊满满的！柒葱永远陪着你 ♪"],
    }

    def add_affection(self, n):
        self.affection += n
        # 判断是否跨阶段
        stage = 0
        for i, (th, _name) in enumerate(self.AFF_STAGES):
            if self.affection >= th:
                stage = i
        if stage > self._aff_stage:
            self._aff_stage = stage
            self.say(random.choice(self.AFF_LINES.get(stage, ["(´▽`ʃ♡ƪ)"])), 4.0)
            self.add_particle("💖", self.W / 2,
                              self.H - self.MARGIN_BOT - self.disp_h() * 0.5,
                              vy=-50, life=1.8, size=24)
            self.save()

    def ear_wiggle(self):
        self.wiggle = 0.6

    def blow_bubble(self):
        """吹出一个上升的泡泡（戳破有反馈）。"""
        if len(self.bubbles) < 5:
            self.bubbles.append({
                "x": self.W / 2 + random.randint(-40, 40),
                "y": self.H - self.MARGIN_BOT - self.disp_h() * 0.55,
                "r": 11 + random.randint(0, 12),
                "vy": -28 - random.randint(0, 28),
                "t": 0.0, "life": 4.5})

    def _begin_fall(self):
        self.state = "fall"
        self.vy = 0.0
        self.bounces = 0
        self.fall_start = float(self.y() + self.H - self.MARGIN_BOT)

    def hit_part(self, pos):
        """把窗口坐标映射到立绘相对位置，判定点击的身体部位。"""
        pm = self.scaled("idle")
        if pm is None:
            return None
        x0 = self.W / 2 - pm.width() / 2
        y1 = (self.H - self.MARGIN_BOT) + self.dy
        y0 = y1 - pm.height()
        rx = (pos.x() - x0) / max(1, pm.width())
        ry = (pos.y() - y0) / max(1, pm.height())
        if not (0.0 <= rx <= 1.0 and 0.0 <= ry <= 1.0):
            return None
        if ry < 0.24:
            return "ear"        # 猫耳 / 头顶
        if ry < 0.50:
            return "face"       # 脸
        if ry < 0.72:
            return "tummy"      # 身体 / 手
        if ry < 0.87:
            return "skirt"      # 裙子
        return "feet"           # 腿脚

    # ============ 交互 ============
    def enterEvent(self, e):
        self.hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.hover = False
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.pressed = True
            self.moved = False
            self.interact()
            if self.state == "peek":      # 一碰就从边缘探回来
                self.state = "idle"
                self._unpeek()
                self._just_unpeeked = True
            if self.state == "sleep":
                self.wake_up()
            # 注意：drag_offset 必须在 _unpeek() 移动窗口之后再算，否则拖动起点会偏移
            self.drag_offset = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e):
        # 精确判定鼠标是否悬在「角色本体」上（窗口含透明边距，比整窗判定更准）
        pt = e.position().toPoint()
        feet = self.H - self.MARGIN_BOT
        bw, dh = self.body_w(), self.disp_h()
        inside = (abs(pt.x() - self.W / 2) <= bw / 2 + 8
                  and feet - dh - 10 <= pt.y() <= feet + 8)
        if inside != self.hover:
            self.hover = inside
            self.update()
        if self.pressed and (e.buttons() & Qt.LeftButton):
            delta = e.globalPosition().toPoint() - self.pos() - self.drag_offset
            if not self.moved and delta.manhattanLength() > 6:
                self.moved = True
                if self.state == "bye":      # 退出动画中不可拖动
                    return
                self.state = "drag"          # 任何状态都能起拖（不再限制白名单）
                self.say(random.choice(LINES["drag"]), 2.2)
            if self.state == "drag":
                now = time.time()
                newp = e.globalPosition().toPoint() - self.drag_offset
                if self._last_drag_t:
                    dtm = max(0.008, now - self._last_drag_t)
                    ivx = (newp.x() - self.x()) / dtm
                    ivy = (newp.y() - self.y()) / dtm
                    self.vx = self.vx * 0.55 + ivx * 0.45   # EMA 平滑，甩出不抖动
                    self.vy = self.vy * 0.55 + ivy * 0.45
                self._last_drag_t = now
                self.move(newp)
                self.interact()
                # 身体惯性：随水平速度摆动（头跟鼠标，身体靠后甩出）
                target = max(-1.0, min(1.0, self.vx / 1400.0))
                self.drag_swing += (target - self.drag_swing) * 0.30

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.pressed:
            self.pressed = False
            if self.moved and self.state == "drag":
                # 松手时若贴在屏幕上边缘，直接倒挂在上边缘探头（不下落）
                if not self._try_peek_top():
                    # 扔飞：拖动末速度足够快就抛出去（重力 + 回弹）
                    if math.hypot(self.vx, self.vy) > 120:
                        self.state = "throw"
                        self.vx = max(-1800.0, min(1800.0, self.vx))
                        self.vy = max(-1400.0, min(1400.0, self.vy))
                        self.bounces = 0
                        self.rot = 0.0
                        self.throw_t = 0.0
                        self.timer.setInterval(16)   # 飞行中提高帧率，更顺滑
                    else:
                        self._begin_fall()
                    self._last_drag_t = 0.0
            elif not self.moved:
                if self._just_unpeeked:      # 刚从探头探回来：只探回来，不触发部位点击
                    self._just_unpeeked = False
                else:
                    self.on_click(e.position().toPoint())

    def dragEnterEvent(self, e):
        # 接受文件/文件夹拖入，也接受纯文本/网址拖入
        md = e.mimeData()
        if md.hasUrls() or md.hasText() or md.hasFormat("text/uri-list"):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        md = e.mimeData()
        if md.hasUrls() or md.hasText() or md.hasFormat("text/uri-list"):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def _mod_fire_drop(self, text):
        """把拖进来的文本交给模组；任一模组返回 True 表示已接管。"""
        handled = False
        for api in self.mod_apis:
            try:
                if api.fire_drop(text):
                    handled = True
            except Exception as ex:
                print("[MOD] %s.fire_drop 出错: %s" % (api.id, ex), flush=True)
        return handled

    def dropEvent(self, e):
        import os
        md = e.mimeData()
        text = (md.text() or "").strip()
        if not text:                      # 有些来源只给 text/uri-list，不带纯文本
            for u in md.urls():
                s = (u.toString() or "").strip()
                if s and not u.isLocalFile():
                    text = s
                    break
        # 先给模组机会处理（例如「网址加速」模组把网址拼前缀后打开浏览器）
        if text and self._mod_fire_drop(text):
            e.acceptProposedAction()
            return
        paths = [u.toLocalFile() for u in md.urls()]
        paths = [p for p in paths if p and os.path.exists(p)]
        if not paths:
            if text:
                self.say("唔…这串字我啃不动喵，拖个文件或网址给我吧", 2.6)
            return
        ok = sum(1 for pth in paths if self.trash_file(pth))
        if ok:
            self.state = "eat_file"
            self.state_left = 1.6
            extra = "" if len(paths) == 1 else f"（共 {ok} 个）"
            self.say(random.choice(LINES["eat_file"]) + extra, 3.0)
            self.add_particle("🍽", self.W / 2,
                              self.H - self.MARGIN_BOT - self.disp_h() * 0.5,
                              vy=-40, life=1.2, size=20)
        else:
            self.say("唔…这个吃不下，可能被占用或者没权限喵…", 2.8)
        e.acceptProposedAction()

    def trash_file(self, path):
        """把文件/文件夹丢进回收站（随时可还原）。

        返回 True 表示「已经处理掉」。
        注意：部分精简系统 / 没有回收站的卷上，SHFileOperationW 会返回非 0
        （实测返回 2 或 1223=用户取消）但其实文件已经被删掉了，
        所以判定标准是「返回 0」**或**「调用之后文件确实不在了」。
        """
        try:
            path = os.path.abspath(path)
        except Exception:
            return False
        if not os.path.exists(path):
            return False                        # 拖过来时就已经没了
        rc = -1
        for attempt in (0, 1):
            rc = self._shell_delete(path)
            if rc == 0:
                return True
            if not os.path.exists(path):        # 返回非 0 但文件确实没了 → 视为成功
                print("[EAT] SHFileOperationW rc=%s，但文件已消失，按成功处理：%s"
                      % (rc, path), flush=True)
                return True
            if attempt == 0:
                time.sleep(0.25)                # 拖动来源可能还占用着文件，稍等再试一次
        print("[EAT] 删除失败 rc=%s：%s" % (rc, path), flush=True)
        return False

    @staticmethod
    def _shell_delete(path):
        """调 Shell API 把 path 删进回收站，返回错误码（0 = 成功）。"""
        import ctypes
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND),
                        ("wFunc", wintypes.UINT),
                        ("pFrom", wintypes.LPCWSTR),
                        ("pTo", wintypes.LPCWSTR),
                        ("fFlags", ctypes.c_uint16),
                        ("fAnyOperationsAborted", wintypes.BOOL),
                        ("hNameMappings", ctypes.c_void_p),
                        ("lpszProgressTitle", wintypes.LPCWSTR)]

        op = SHFILEOPSTRUCTW()
        op.hwnd = None
        op.wFunc = 3                                   # FO_DELETE
        op.pFrom = path + "\0"                         # ctypes 会再补一个 \0 → 双 null 结尾
        op.pTo = None
        op.fFlags = 0x0040 | 0x0010 | 0x0004 | 0x0400  # 允许撤销/不弹确认/静默/不弹错误框
        return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.pet_head()

    def wheelEvent(self, e):
        idx = self.SIZE_ORDER.index(self.size_key)
        idx = max(0, min(len(self.SIZE_ORDER) - 1,
                         idx + (1 if e.angleDelta().y() < 0 else -1)))
        if self.SIZE_ORDER[idx] != self.size_key:
            self.set_size(self.SIZE_ORDER[idx])
            self.save()

    def on_click(self, pos):
        self.interact()
        self.add_affection(1)          # 每次互动都加一点好感
        if self.state == "sleep":
            self.wake_up()
            return
        if self.state in ("drag", "fall"):
            return
        # 戳泡泡：点中泡泡就啵地破掉
        for b in self.bubbles:
            if math.hypot(pos.x() - b["x"], pos.y() - b["y"]) <= b["r"] + 8:
                self.bubbles.remove(b)
                self.add_particle("🫧", b["x"], b["y"], vy=-40, life=0.7, size=20,
                                  color=(160, 210, 255))
                self.say(random.choice(["啵！", "泡泡破啦～", "接住！"]), 1.6)
                return
        # 连戳炸毛：2 秒内单击 ≥3 次（非空白区域点戳也计入）
        now = time.time()
        self._poke_times.append(now)
        self._poke_times = [t for t in self._poke_times if now - t < 2.0]
        if len(self._poke_times) >= 3 and self.state == "idle":
            self._poke_times = []
            self.state = "angry"
            self.state_left = 2.5
            self.say(random.choice(LINES["angry"]), 3.0)
            self.add_particle("💢", self.W / 2,
                              self.H - self.MARGIN_BOT - self.disp_h() * 0.7,
                              vy=-40, life=1.2, size=22, color=(255, 90, 90))
            return
        hx, hy = self.head_pos()
        part = self.hit_part(pos)
        if part:
            self._mod_fire("fire_click", part)
        if part == "ear":
            self.ear_wiggle()
            self.add_particle("♪", hx + random.randint(-20, 20), hy - 6,
                              vy=-46, life=1.2, size=18, color=(255, 150, 200))
            self.say(random.choice(LINES["ear"]), 2.8)
            self.gain(2, 1)
        elif part == "face":
            self.squash = 0.14
            self.add_particle("💕", hx + random.randint(-16, 16), hy + 6,
                              vy=-42, life=1.2, size=17)
            self.say(random.choice(LINES["face"]), 2.8)
            self.gain(2, 1)
        elif part == "tummy":
            self.wiggle = 0.9
            self.add_particle("😆", hx, hy + 26, vy=-38, life=1.1, size=19)
            self.say(random.choice(LINES["tummy"]), 2.8)
            self.gain(2, 2)
        elif part == "skirt":
            self.add_particle("💢", hx, hy + 48, vy=-40, life=1.1, size=19,
                              color=(255, 90, 90))
            self.say(random.choice(LINES["skirt"]), 2.8)
            if random.random() < 0.35 and self.src["back"] is not None:
                self.turn_back()
            self.gain(1, 0)
        elif part == "feet":
            self.squash = 0.26
            self.add_particle("💢", self.W / 2, self.H - self.MARGIN_BOT - 16,
                              vy=-36, life=1.0, size=17, color=(255, 90, 90))
            self.say(random.choice(LINES["feet"]), 2.6)
            self.gain(1, 0)
        else:
            # 点在空白/非立绘区域：默认摸头
            self.pet_head(quiet=True)

    def pet_head(self, quiet=False):
        if self.state == "sleep":
            self.wake_up()
            return
        self.interact()
        self.ear_wiggle()
        hx, hy = self.head_pos()
        for i in range(3):
            self.add_particle("💗", hx + random.randint(-30, 30), hy + random.randint(-10, 10),
                              vy=-60 - i * 12, life=1.5, size=20 + i * 2)
        self.gain(3, 0)
        self.add_affection(2)          # 摸头好感额外 +2
        if not quiet:
            self.say(random.choice(LINES["pet"]))
        if random.random() < 0.22:
            self.show_popup("happy")

    def feed(self, food):
        self.interact()
        if self.state == "sleep":
            self.wake_up()
        if self.state in ("drag", "fall"):
            return
        if self.hunger >= 96:
            self.say(random.choice(LINES["full"]))
            return
        info = FOODS.get(food) or {}
        self.pending_food = food
        self.eat_key = info.get("img", "eat") if self.src.get(info.get("img", "")) is not None else "eat"
        self.state = "eat"
        self.state_left = info.get("time", 1.9)
        self.say("啊呜——", 1.2)

    def _finish_eat(self):
        info = FOODS.get(self.pending_food) or {"stats": (30, 6, 6)}
        vh, vm, ve = info["stats"]
        self.hunger = min(100.0, self.hunger + vh)
        self.mood = min(100.0, self.mood + vm)
        self.health = min(100.0, self.health + 2)
        self.gain(ve, 0)
        hx, hy = self.head_pos()
        for i in range(2):
            self.add_particle("✨", hx + random.randint(-24, 24),
                              hy + random.randint(10, 40), vy=-50, life=1.2, size=18)
        self.say(random.choice(LINES["feed"]))
        self.eat_key = None
        self.ensure_floor()

    # ---- 日常：洗澡 / 上厕所 / 吃药 ----
    def bath_now(self):
        self.interact()
        if self.state == "sleep":
            self.wake_up()
        if self.state in ("drag", "fall"):
            return
        if self.src["bath"] is None:
            self.say("浴缸还没准备好喵…", 2.0)
            return
        self.state = "bath"
        self.state_left = 3.2
        self.say(random.choice(LINES["bath"]), 2.4)

    def _finish_bath(self):
        self.hyg = 100.0
        self.mood = min(100.0, self.mood + 10)
        self.gain(5, 0)
        self.say(random.choice(LINES["bath_done"]), 2.8)
        self.ensure_floor()

    def toilet_now(self):
        self.interact()
        if self.state == "sleep":
            self.wake_up()
        if self.state in ("drag", "fall"):
            return
        if self.src["toilet"] is None:
            self.say("厕所在装修喵…憋一会儿…", 2.0)
            return
        self.state = "toilet"
        self.state_left = 3.0
        self.say(random.choice(LINES["toilet"]), 2.4)

    def _finish_toilet(self):
        self.toilet_need = 0.0
        self.mood = min(100.0, self.mood + 4)
        self.gain(2, 0)
        self.say(random.choice(LINES["toilet_done"]), 2.6)
        self.ensure_floor()

    def medicine_now(self):
        self.interact()
        if self.state == "sleep":
            self.wake_up()
        if self.state in ("drag", "fall"):
            return
        if self.src["medicine"] is None:
            self.say("药箱里没有药了喵…", 2.0)
            return
        self.state = "medicine"
        self.state_left = 1.6
        self.say(random.choice(LINES["medicine"]), 2.0)

    def _finish_medicine(self):
        self.health = min(100.0, self.health + 60)
        self.hunger = min(100.0, self.hunger + 5)
        if self.state == "sick" and self.health >= self.SICK_HEALTH:
            self.state = "idle"
            self.say(random.choice(LINES["sick_ok"]), 3.0)
        else:
            self.say(random.choice(LINES["sick_ok"]), 2.6)
        self.ensure_floor()

    def play(self):
        self.interact()
        if self.state == "sleep":
            self.wake_up()
        if self.state in ("drag", "fall"):
            return
        if self.state == "sick":
            self.say("病恹恹的…玩不动喵…先让我休息…", 2.8)
            return
        if self.hunger < 20:
            self.say(random.choice(LINES["play_refuse"]))
            return
        self.state = "play"
        self.state_left = 2.2
        self.say(random.choice(LINES["play"]), 2.2)

    def _finish_play(self):
        self.mood = min(100.0, self.mood + 25)
        self.hunger = max(0.0, self.hunger - 8)
        self.gain(8, 0)
        self.ensure_floor()

    def sleep_now(self):
        self.interact()
        self.bubble = {"text": random.choice(LINES["sleep"]), "t": 0.0, "life": 2.5}
        self.state = "sleep"
        self.zzz_timer = 0.8

    def wake_up(self):
        self.state = "idle"
        self.last_interact = time.time()
        self.next_act = time.time() + random.randint(6, 12)
        self.say(random.choice(LINES["wake"]), 3.0)

    def turn_back(self):
        self.state = "back"
        self.state_left = 3.0
        self.bubble = {"text": random.choice(LINES["back"]), "t": 0.0, "life": 2.8}

    # ---------------- 番茄钟 ----------------
    @staticmethod
    def fmt_pomo(sec):
        """剩余时间格式：『H小时MM分SS秒』或『MM分SS秒』。"""
        sec = max(0, int(round(sec)))
        h, rem = divmod(sec, 3600)
        m, s = divmod(rem, 60)
        return f"{h}小时{m:02d}分{s:02d}秒" if h else f"{m:02d}分{s:02d}秒"

    # ---- 长条闹钟（番茄钟倒计时显示在这里）----
    def _notify(self, title, msg, msecs=6000):
        """发系统通知（走托盘图标；没有托盘就静默跳过）。"""
        if self.tray is None:
            return
        try:
            self.tray.showMessage(title, msg, QSystemTrayIcon.Information, msecs)
        except Exception as ex:
            print("[通知] 发送失败：%s" % ex, flush=True)

    def _ensure_pomo_clock(self):
        if self.pomo_clock is None:
            self.pomo_clock = PomoClock()
            self.pomo_clock.pet = self
        self.pomo_clock.set_left(self.pomo_total, self.pomo_total)
        self.pomo_clock.follow(self)
        self.pomo_clock.show()
        self.pomo_clock.raise_()

    def _hide_pomo_clock(self):
        if self.pomo_clock is not None:
            self.pomo_clock.hide()

    def _close_aux_windows(self):
        """退出前关掉辅助窗口（长条闹钟、任务栏监控条）并停音乐采集。"""
        self._music_stop.set()
        if self.pomo_clock is not None:
            self.pomo_clock.close()
            self.pomo_clock = None
        if self.tbmon is not None:
            self.tbmon.unembed()
            self.tbmon.close()
            self.tbmon = None

    def start_pomo(self, seconds):
        self.pomo_total = float(seconds)
        self.pomo_end = time.time() + seconds
        self.pomo_last_sec = -1
        self.pomo_alert_left = 0.0
        self._ensure_pomo_clock()          # 只出闹钟，不说话

    def cancel_pomo(self):
        self.pomo_end = 0.0
        self.pomo_last_sec = -1
        self.pomo_alert_left = 0.0
        self._hide_pomo_clock()
        self.say("番茄钟取消啦~", 2.2)

    def _tick_pomo(self, dt):
        if self.pomo_alert_left > 0:            # 到点提醒：闹钟闪烁展示
            self.pomo_alert_left -= dt
            if self.pomo_clock is not None:
                self.pomo_clock.set_left(self.pomo_alert_left, 8.0, alert=True)
                self.pomo_clock.follow(self)
            if self.pomo_alert_left <= 0:
                self.pomo_alert_left = 0.0
                self.state = "idle"
                self._hide_pomo_clock()
            return
        if self.pomo_end <= 0:
            return
        left = self.pomo_end - time.time()
        if left <= 0:                            # 时间到！举番茄提醒
            self.pomo_end = 0.0
            self.pomo_last_sec = -1
            self.state = "pomo_alert"
            self.pomo_alert_left = 8.0
            self._ensure_pomo_clock()
            if self.pomo_clock is not None:      # 立刻进入闪烁态
                self.pomo_clock.set_left(8.0, 8.0, alert=True)
                self.pomo_clock.follow(self)
            self.add_particle("🍅", self.W / 2,
                              self.H - self.MARGIN_BOT - self.disp_h() * 0.6,
                              vy=-46, life=1.8, size=24)
            if self.pomo_notify:                 # 系统通知（右下角弹窗 / 通知中心）
                self._notify("🍅 番茄钟时间到！",
                             "已经 %s 啦，起来活动一下喵～"
                             % self.fmt_pomo(self.pomo_total))
            return
        # 每帧刷新长条闹钟的内容与位置（跟随角色，探头时也看得见）
        if self.pomo_clock is None:
            self._ensure_pomo_clock()
        if self.pomo_clock is not None:
            self.pomo_clock.set_left(left, self.pomo_total)
            self.pomo_clock.follow(self)

    # ---- 节日皮肤 ----
    def _load_custom_skins(self):
        """把用户导入的节日皮肤（存档里记录的）加载进 src。"""
        for _key, sk in (self.festival_skins or {}).items():
            if sk and sk not in self.src:
                pm = pm_or_none(sk + ".png")
                if pm is not None and not pm.isNull():
                    self.src[sk] = pm

    def skin_for(self, key, info):
        """某个日子使用的皮肤 key：用户导入的优先于内置；不可用则 None。"""
        if not info:
            return None
        sk = (self.festival_skins or {}).get(key) or info.get("skin")
        return sk if (sk and self.src.get(sk) is not None) else None

    def _daynight_tick(self, now=None):
        """昼夜系统：夜间自动睡觉；凌晨提醒「主人快睡」。"""
        import datetime
        if now is None:
            now = datetime.datetime.now()
        h = now.hour
        if self.music_mode:          # 音乐模式不睡觉
            return
        # 夜间（22:00-6:30）无操作时自动入睡
        if (h >= 22 or h < 6) and self.state == "idle" and \
                time.time() - self.last_interact > 90:
            self.sleep_now()
            return
        # 凌晨（23:00-2:00）提醒一次，每天一句
        if h >= 23 or h < 2:
            key = now.strftime("%Y-%m-%d")
            if self._night_said != key and not self.busy_mode:
                self._night_said = key
                self.say("主人，都凌晨啦，快睡吧～", 5.0)

    def lick_screen(self):
        """舔屏幕：切到探头姿势，画半透明舌头。"""
        g = self.screen_geom()
        cx = self.x() + self.W / 2
        self.peek_side = -1 if cx < g.left() + g.width() / 2 else 1
        self.state = "lick"
        self.lick_left = 1.6
        self._apply_peek_pos()
        self.say("舔一口～", 2.4)

    def toggle_music_mode(self):
        """音乐模式：角色跟随系统播放的音乐打节拍。"""
        self.music_mode = not self.music_mode
        if self.music_mode:
            self._music_stop.clear()
            self.music_ready = False
            self.music_error = ""
            self.music_beat = self.music_pitch = self.music_level = 0.0
            self._beat_avg = 0.0
            self._music_on_t = time.time()
            self._last_nosound_say = time.time()
            self._music_thread = threading.Thread(
                target=_audio_worker, args=(self,), daemon=True)
            self._music_thread.start()
            self.say("音乐模式开启♪ 来点节奏吧！", 2.8)
        else:
            self._music_stop.set()
            self._music_thread = None
            self.music_beat = self.music_pitch = 0.0
            self.music_level = 0.0
            self._beat_flash = 0.0
            self.state = "idle"
            self.say("音乐模式关闭啦~", 2.2)
        self.save()

    def _restart_music_worker(self):
        """换音频设备后重启采集线程。"""
        if not self.music_mode:
            return
        self._music_stop.set()
        if self._music_thread is not None:
            self._music_thread.join(timeout=2)
        self._music_stop.clear()
        self.music_ready = False
        self.music_error = ""
        self.music_beat = self.music_pitch = self.music_level = 0.0
        self._beat_avg = 0.0
        self._music_on_t = time.time()
        self._last_nosound_say = time.time()
        self._music_thread = threading.Thread(
            target=_audio_worker, args=(self,), daemon=True)
        self._music_thread.start()

    def _music_tick(self, dt):
        """音乐模式：角色静止不动，只靠节奏圈可视化（不移动、不睡觉）。"""
        if not self.music_mode:
            return
        # 静音诊断：开了音乐模式但一直没声音
        if self.music_level < 0.01 and not self.music_error \
                and time.time() - self._music_on_t > 4 \
                and time.time() - self._last_nosound_say > 30:
            self._last_nosound_say = time.time()
            self.say("咦，没听到声音…试试右键「🎧 音乐设备」换一个？", 4.5)

    def _draw_music_lights(self, p, feet_y, dh):
        """音乐节奏灯：8 个频段圈，独立大小；低音灵敏度驱动低频段、高音灵敏度驱动高频段。"""
        if not self.music_mode:
            return
        cx = self.W / 2
        cy = feet_y - dh * 0.55
        bands = self.music_bands or [0.0] * 8
        n = len(bands)
        if not hasattr(self, "_band_smooth"):
            self._band_smooth = [0.0] * n
        # 前 4 个频段=低音(40-600Hz)用低音灵敏度，后 4 个=高音(600-10kHz)用高音灵敏度
        sens = [self.music_low_sens] * 4 + [self.music_high_sens] * 4
        for i in range(n):
            target = min(1.0, bands[i] * sens[i])
            self._band_smooth[i] += (target - self._band_smooth[i]) * 0.35
        for i in range(n):
            v = self._band_smooth[i]
            ang = i * (2 * math.pi / n) - math.pi / 2   # 从顶部开始
            r = dh * 0.52
            x = cx + math.cos(ang) * r
            y = cy + math.sin(ang) * r * 0.75
            rad = 6 + v * 24
            hue = (0.98 - i / (n - 1) * 0.62) % 1.0
            light = 0.55 + 0.45 * v
            col = QColor.fromHsvF(hue, 0.80, light)
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawEllipse(QPointF_c(x, y), rad, rad)

    def _check_festival(self):
        """今天是什么日子？→ 换节日皮肤（全天持有）+ 提醒一次。"""
        key, info = today_festival()
        self.daily_skin = self.skin_for(key, info)
        if key and key != self._fest_key:
            self._fest_key = key
            self.say(info["line"], 4.5)
            self.add_particle(info.get("particle", "🎉"),
                              self.W / 2,
                              self.H - self.MARGIN_BOT - self.disp_h() * 0.6,
                              vy=-46, life=1.6, size=20)
        elif not key:
            self._fest_key = None

    def _check_caps(self):
        """检测 CapsLock 是否切换，切换了就抱着字母提示主人。"""
        try:
            import ctypes
            on = bool(ctypes.windll.user32.GetKeyState(0x14) & 0x0001)
        except Exception:
            return                      # 非 Windows / 取不到就不提示
        if self.caps_last is None:      # 首次只记录状态，不打扰
            self.caps_last = on
            return
        if on == self.caps_last:
            return
        self.caps_last = on
        self.caps_upper = on
        if self.state in ("drag", "fall"):
            return
        self.prev_state = self.state if self.state != "caps" else "idle"
        self.state = "caps"
        self.caps_left = 2.2
        self._mod_fire("fire_caps", on)
        # 只用抱字母的立绘提示，不再弹气泡说话

    def _try_peek_top(self):
        """松手时若贴着屏幕上边缘，就扒在上边缘探头（倒挂往下看，不下落）。
        必须在松手瞬间判断：否则角色会因重力落到屏幕底部，再也够不到上边缘。"""
        g = self.screen_geom()
        head_y = self.y() + self.H - self.MARGIN_BOT - self.disp_h()
        if head_y > g.top() + self.disp_h() * 0.35:
            return False
        self.peek_side = 2
        self.state = "peek"
        self.bubble = None      # 探头时保持安静（连落地台词也不显示）
        self._apply_peek_pos()
        self._mod_fire("fire_peek", self.peek_side)
        return True

    PEEK_EDGE = 0.45      # 探头时身体露出屏幕的比例（其余藏在屏幕外）
    # 探头时系统信息显示在探头方向的反侧（左探头→靠右，右探头→靠左，上探头→靠下）
    PEEK_SYSMON_SIDE = {-1: "right", 1: "left", 2: "bottom"}

    def _unpeek(self):
        """从探头状态回到屏幕内：左右探头保持贴边、垂直不变；上探头移到顶部下方。"""
        g = self.screen_geom()
        if self.peek_side == 2:
            feet = g.top() + self.disp_h() + 8
            cx = self.x() + self.W / 2
            cx = max(g.left() + self.body_w() / 2,
                     min(cx, g.right() - self.body_w() / 2))
            self.move(int(cx - self.W / 2),
                      int(feet - (self.H - self.MARGIN_BOT)))
        else:
            self.clamp_into_screen(keep_feet=True)

    def _startup_peek(self):
        """启动时：若上次关闭位置贴着屏幕边缘，自动吸附成探头姿势。"""
        try:
            g = self.screen_geom()
            slack = 10
            body_l = self.x() + self.MARGIN_X
            body_r = self.x() + self.W - self.MARGIN_X
            if body_l <= g.left() + slack:
                self.peek_side = -1                      # 贴左边缘
            elif body_r >= g.right() - slack:
                self.peek_side = 1                       # 贴右边缘
            elif self.y() <= g.top() + slack:
                self.peek_side = 2                       # 贴上边缘
            else:
                return False
            self.state = "peek"
            self.bubble = None
            self.dy = 0.0
            self.rot = 0.0
            self._apply_peek_pos()
            print("[状态] 位置贴边 → 自动吸附探头 side=%d" % self.peek_side,
                  flush=True)
            return True
        except Exception as ex:
            print("[启动] 探头吸附失败：%s" % ex, flush=True)
            return False

    def _maybe_peek(self):
        """落地后判断：是否被拖到了屏幕左/右/上边缘，是就抓着边缘探头看你。
        peek_side: -1=左边缘 1=右边缘 2=上边缘（倒挂往下探）。"""
        g = self.screen_geom()
        bw = self.body_w()
        cx = self.x() + self.W / 2          # 角色中心（窗口含透明边距）
        head_y = self.y() + self.H - self.MARGIN_BOT - self.disp_h()
        if head_y <= g.top() + self.disp_h() * 0.20:
            self.peek_side = 2              # 拖到屏幕顶部 → 从上边缘探头
        elif cx <= g.left() + bw * 0.70:    # 拖到边缘附近就吸附（探头）
            self.peek_side = -1
        elif cx >= g.right() - bw * 0.70:
            self.peek_side = 1
        else:
            return False
        self.state = "peek"
        self.bubble = None      # 探头时保持安静（连落地台词也不显示）
        self._apply_peek_pos()
        self._mod_fire("fire_peek", self.peek_side)
        return True

    def _apply_peek_pos(self):
        """把角色贴到屏幕边缘：身体大部分藏在屏幕外，只露出一点探头。
        peek_side: -1=左 1=右 2=上（倒挂，立绘底部即头部，探进屏幕）。"""
        g = self.screen_geom()
        bw = self.body_w()
        if self.peek_side < 0:              # 左边缘：身体藏在屏幕外左侧
            vis = bw * self.peek_dist["left"]
            cx, feet = g.left() + vis - bw / 2, self.floor_y()
        elif self.peek_side > 1:            # 上边缘：倒挂，图顶部贴屏幕顶边
            cx = self.x() + self.W / 2
            cx = max(g.left() + bw / 2, min(cx, g.right() - bw / 2))
            feet = g.top() + self.disp_h() * self.peek_dist["top"]
        else:                                # 右边缘：镜像
            vis = bw * self.peek_dist["right"]
            cx, feet = g.right() - vis + bw / 2, self.floor_y()
        self.move(int(round(cx - self.W / 2)),
                  int(round(feet - (self.H - self.MARGIN_BOT))))

    def ensure_floor(self):
        if self.y() + self.H - self.MARGIN_BOT < self.floor_y() - 2:
            self._begin_fall()
        else:
            self.state = "idle"

    def gain(self, e, m=0):
        self.exp += e
        if m:
            self.mood = min(100.0, self.mood + m)
        need = self.exp_need()
        if self.exp >= need:
            self.exp -= need
            self.level += 1
            self.celebrate()

    def exp_need(self):
        return 50 + (self.level - 1) * 25

    def celebrate(self):
        self.show_popup("happy", life=1.8)
        cx = self.W / 2
        for i in range(9):
            self.add_particle(random.choice(["✿", "★", "✨", "💗"]),
                              cx + random.randint(-70, 70),
                              self.H - self.MARGIN_BOT - self.disp_h() + random.randint(-10, 40),
                              vy=-(40 + i * 8), vx=random.randint(-20, 20),
                              life=1.6 + i * 0.08, size=22)
        self.say(random.choice(LINES["levelup"]), 4.0)

    # ============ 行为调度 ============
    def start_walk(self):
        g = self.screen_geom()
        # 用角色本体范围计算可行走区域（透明边距可溢出屏幕）
        lo = g.left() - self.MARGIN_X + 4
        hi = g.right() - self.MARGIN_X - self.body_w() - 2
        if hi <= lo:
            return
        x = self.x()
        target = random.randint(lo, hi)
        if abs(target - x) < 60:      # 目标太近就走到另一侧去
            target = lo if x > (lo + hi) // 2 else hi
        self.walk_vx = self.WALK_VX if target > x else -self.WALK_VX
        self.walk_target = abs(target - x)
        self.walk_done = 0.0
        self.walk_t = 0.0
        self.walk_frame = 1
        self.facing = 1 if self.walk_vx > 0 else -1
        self.state = "walk"

    def behave(self):
        if time.time() < self.next_act:
            return
        self.next_act = time.time() + random.randint(9, 20)
        if self.music_mode:          # 音乐模式：静止不动，不打节拍不散步
            return
        if self.busy_mode:
            return                  # 我没空：完全静默，数值由 stats_step 自动恢复
        r = random.random()
        if r < 0.40:
            self.say(random.choice(LINES["idle"]))
        elif r < 0.72:
            self.start_walk()
        elif r < 0.84:
            self.ear_wiggle()
        elif r < 0.92 and self.mood < 40 and self.src["back"] is not None:
            self.turn_back()
        elif r < 0.98:
            self.blow_bubble()      # 偶尔吹个泡泡（点破有反馈）

    def self_care(self):
        """我没空模式：原地把自己照顾好（吃饭/洗澡/上厕所/吃药），不移动。"""
        if self.state in ("eat", "bath", "toilet", "medicine", "sick", "sleep",
                          "caps", "eat_file"):
            return
        if self.hunger < 35:
            self.feed(random.choice(list(FOODS)))
            self.say(random.choice(LINES["busy_care"]), 2.4)
        elif self.hyg < 35 and self.src.get("bath") is not None:
            self.bath_now()
        elif self.toilet_need > 75:
            self.toilet_now()
        elif self.health < self.SICK_HEALTH and self.src.get("medicine") is not None:
            self.medicine_now()
        else:
            r = random.random()
            if r < 0.45:
                self.say(random.choice(LINES["busy_care"]), 2.6)
            elif r < 0.75:
                self.ear_wiggle()

    def stats_step(self):
        if self.busy_mode:
            # 我没空：后台静默自养——数值自动回升，不生病、不抱怨、不做动作
            self.hunger = min(100.0, self.hunger + 5.0)
            self.mood = min(100.0, self.mood + 5.0)
            self.hyg = min(100.0, self.hyg + 5.0)
            self.health = min(100.0, self.health + 5.0)
            self.toilet_need = 0.0
            if self.state == "sick":
                self.state = "idle"
            return
        self.hunger = max(0.0, self.hunger - 0.10)
        self.mood = max(0.0, self.mood - 0.08)
        self.hyg = max(0.0, self.hyg - 0.07)
        self.toilet_need = min(100.0, self.toilet_need + 0.35)
        # 健康：饿肚子/脏兮兮/生病掉得快，吃饱干净时缓慢恢复
        dh = 0.02
        if self.hunger < 15:
            dh += 0.06
        if self.hyg < 15:
            dh += 0.08
        if self.state == "sick":
            dh += 0.04
        if self.hunger > 60 and self.hyg > 60 and self.state != "sick":
            dh -= 0.03
        self.health = max(0.0, min(100.0, self.health - dh))
        # 生病 / 痊愈（吃药是主要治疗手段）
        if (self.state not in ("sick", "drag", "fall", "bath", "medicine", "sleep")
                and self.health < self.SICK_HEALTH):
            self.state = "sick"
            self.say(random.choice(LINES["sick"]), 3.2)
        elif self.state == "sick" and self.health >= self.SICK_HEALTH + 15:
            self.state = "idle"
            self.say(random.choice(LINES["sick_ok"]), 3.0)
        # 便意：积累到阈值会自己跑厕所
        if self.state == "idle" and self.toilet_need > 70 and \
                time.time() >= self.next_toilet:
            self.say(random.choice(LINES["need_toilet"]), 2.2)
            self.toilet_now()
        if self.toilet_need > 70:
            self.next_toilet = time.time() + 45
        # 卫生太低会抱怨
        if self.state == "idle" and self.hyg < 25 and random.random() < 0.25:
            self.say(random.choice(LINES["dirty"]), 2.8)
        # 太久不理她（站着/走着/生气都会）就自己睡着
        if self.state in ("idle", "walk", "back") and \
                time.time() - self.last_interact > self.AUTO_SLEEP_SEC:
            self.sleep_now()
        elif self.state == "idle" and random.random() < 0.12:
            if self.hunger < 25:
                self.say(random.choice(LINES["hungry"]))
            elif self.mood < 25:
                self.say(random.choice(LINES["sad"]))
        self.setToolTip(f"{NAME} Lv.{self.level}｜饱食 {int(self.hunger)}｜心情 {int(self.mood)}"
                        f"｜卫生 {int(self.hyg)}｜健康 {int(self.health)}")

    # ============ 主循环 ============
    def tick(self):
        dt = 0.033
        self.t += dt
        if self.wiggle > 0:
            self.wiggle -= dt
        if self.dizzy > 0:
            self.dizzy -= dt
        self._check_caps()
        self._tick_pomo(dt)
        if time.time() >= self._fest_check:
            self._fest_check = time.time() + 60
            self._check_festival()
        if time.time() >= self._daynight_check:
            self._daynight_check = time.time() + 60
            self._daynight_tick()
        if time.time() >= self._idle_check:
            self._idle_check = time.time() + 30
            self._idle_tick()
        self._music_tick(dt)
        g = self.screen_geom()
        self.sx = self.sy = 1.0

        if self.state == "idle":
            self.dy = math.sin(self.t * 2.4) * 2.4
            self.rot = math.sin(self.t * 25) * 4 if self.wiggle > 0 else 0.0
            self.behave()
        elif self.state == "walk":
            # 6 帧连续步态：触地-下沉-过渡 交替，身体随步伐起伏
            self.walk_t += dt
            self.walk_frame = self.WALK_SEQ[
                int(self.walk_t / self.WALK_FRAME_TIME) % len(self.WALK_SEQ)]
            self.dy = self.WALK_DY[self.walk_frame - 1]
            self.rot = self.WALK_TILT * (1 if self.facing > 0 else -1)
            # 累积位移，够 3px 才真正移动窗口：减少窗口移动次数
            # （透明置顶窗口移动越频繁，桌面越容易残留拖影，合成开销也越大）
            self._walk_acc += self.walk_vx * dt
            if abs(self._walk_acc) >= 3:
                step = int(self._walk_acc)
                self.move(self.x() + step, self.y())
                self._walk_acc -= step
            self.walk_done += abs(self.walk_vx) * dt
            hit_wall = ((self.walk_vx < 0 and
                         self.x() <= g.left() - self.MARGIN_X + 4) or
                        (self.walk_vx > 0 and self.x() >=
                         g.right() - self.MARGIN_X - self.body_w() - 2))
            if hit_wall or self.walk_done >= self.walk_target:
                self.state = "idle"
                self.facing *= -1 if hit_wall else 1
                self.next_act = time.time() + random.randint(4, 9)
        elif self.state == "peek":
            # 探头时保持静止；顶角倒挂时轻轻晃腿
            self.dy = 0.0
            self.rot = 0.0
            if self.peek_side == 2:
                g = self.screen_geom()
                if self.x() < g.left() + 80 or self.x() + self.W > g.right() - 80:
                    self.rot = math.sin(self.t * 5) * 7   # 顶角晃腿
        elif self.state == "caps":
            # 大小写切换提示：抱着字母轻轻晃
            self.dy = math.sin(self.t * 2.6) * 2.4
            self.rot = math.sin(self.t * 3.4) * 2.0
            self.caps_left -= dt
            if self.caps_left <= 0:
                self.state = self.prev_state if self.prev_state != "caps" else "idle"
        elif self.state == "eat_file":
            # 吃掉拖进来的文件：咀嚼动画
            self.sx = 1.0 + math.sin(self.t * 16) * 0.05
            self.sy = 1.0 - math.sin(self.t * 16) * 0.06
            self.state_left -= dt
            if self.state_left <= 0:
                self.sx = self.sy = 1.0
                self.state = "idle"
        elif self.state == "drag":
            # 拖拽物理：身体因惯性滞后于头部，随速度摆动/倾斜
            self.rot = self.drag_swing * 30
            self.dy = math.sin(self.t * 3) * 2 + abs(self.drag_swing) * 8
        elif self.state == "angry":
            # 炸毛：气鼓鼓地发抖
            self.rot = math.sin(self.t * 22) * 6
            self.state_left -= dt
            if self.state_left <= 0:
                self.state = "idle"
        elif self.state == "lick":
            self.lick_left -= dt
            if self.lick_left <= 0:
                self.state = "peek"      # 舔完保持探头
        elif self.state == "throw":
            # 扔飞：重力 + 撞墙/落地回弹；子步积分让高速运动平滑、不跳帧
            g = self.screen_geom()
            # 按本帧位移自适应子步数，速度越快子步越多，避免隧穿
            max_step = max(abs(self.vx), abs(self.vy)) * dt
            steps = max(2, min(8, int(max_step // 8) + 1))
            sdt = dt / steps
            for _ in range(steps):
                self.vy += 2600 * sdt
                self.vx *= (1.0 - 0.4 * sdt)
                nx = self.x() + self.vx * sdt
                ny = self.y() + self.vy * sdt
                if nx < g.left() - self.MARGIN_X:
                    nx = g.left() - self.MARGIN_X
                    self.vx = abs(self.vx) * 0.55
                elif nx > g.right() - self.MARGIN_X - self.body_w():
                    nx = g.right() - self.MARGIN_X - self.body_w()
                    self.vx = -abs(self.vx) * 0.55
                self.move(int(nx), int(ny))
                if ny + self.H - self.MARGIN_BOT >= self.floor_y():
                    self.put_feet(self.floor_y())
                    if abs(self.vy) > 200:
                        self.vy = -self.vy * 0.42
                        self.vx *= 0.7
                        self.squash = 0.26
                        self.add_particle("💫", self.W / 2,
                                          self.H - self.MARGIN_BOT - 12,
                                          vy=-26, life=0.8, size=16)
                    else:
                        self.vx = self.vy = 0.0
                        self.squash = 0.3
                        self.rot = 0.0          # 落地旋转平滑归零，不残留角度
                        self.timer.setInterval(40)   # 落地恢复省电帧率
                        if not self._maybe_peek():
                            self.state = "idle"
                            self.say(random.choice(LINES["land"]), 2.2)
                        break
            if self.state == "throw":            # 仍在空中才继续旋转
                self.throw_t += dt
                self.rot = math.sin(self.throw_t * 16) * 20
                self.dy = -max(0.0, 8.0 - abs(self.vy) * 0.004)
        elif self.state == "fall":
            self.vy += 2400 * dt
            feet = self.y() + self.H - self.MARGIN_BOT + self.vy * dt
            if feet >= self.floor_y():
                self.put_feet(self.floor_y())
                drop = self.floor_y() - self.fall_start   # 下落距离（y 向下为正）
                if abs(self.vy) > 420 and self.bounces < 2:
                    self.bounces += 1
                    self.vy = -self.vy * 0.38
                    self.squash = 0.22
                    self.add_particle("💫", self.W / 2, self.H - self.MARGIN_BOT - 10,
                                      vy=-30, life=0.8, size=18)
                else:
                    # 落地后若贴着屏幕左右边缘，就抓着边缘探头看你
                    peeked = self._maybe_peek()
                    if not peeked:
                        self.state = "idle"
                    self.squash = 0.3
                    if drop > 300 and self.health < 100:
                        # 高处摔落：摔晕，头顶转星星
                        self.dizzy = 1.8
                        self.health = max(0.0, self.health - 3)
                        if not peeked:      # 探头时保持安静
                            self.say(random.choice(LINES["dizzy"]), 2.8)
                    elif not peeked:
                        self.say(random.choice(LINES["land"]), 2.4)
            else:
                self.move(self.x(), round(feet - (self.H - self.MARGIN_BOT)))
                self.rot = 0.0
        elif self.state == "sleep":
            self.dy = 0.0
            self.rot = 0.0
            self.sy = 1.0 + math.sin(self.t * 1.3) * 0.012
            self.zzz_timer -= dt
            if self.zzz_timer <= 0:
                self.zzz_timer = 1.5
                self.add_particle("Z", self.W / 2 + 26,
                                  self.H - self.MARGIN_BOT - self.disp_h() + 14,
                                  vy=-26, vx=10, life=2.2, size=22, color=(125, 135, 225))
        elif self.state == "eat":
            self.dy = 0.0
            self.rot = 0.0
            self.state_left -= dt
            info = FOODS.get(self.pending_food) or {}
            chew = info.get("chew", 14)
            amp = info.get("amp", 0.05)
            dur = info.get("time", 1.9)
            k = 1.0 - max(0.0, self.state_left) / dur
            if k > 0.3:      # 食物到嘴后开始按食物风格咀嚼
                self.sy = 1.0 + math.sin(self.t * chew) * amp
                if random.random() < dt * 2.2:
                    self.add_particle(info.get("fx", "✨"),
                                      self.W / 2 + random.randint(-40, 40),
                                      self.H - self.MARGIN_BOT - self.disp_h() * 0.45,
                                      vy=-40, life=1.1, size=18)
            if self.state_left <= 0:
                self._finish_eat()
        elif self.state == "bath":
            self.dy = math.sin(self.t * 3.0) * 2.0
            self.rot = math.sin(self.t * 2.0) * 2.0
            self.state_left -= dt
            if random.random() < dt * 3:
                self.add_particle("🫧", random.randint(30, self.W - 30),
                                  self.H - self.MARGIN_BOT - random.randint(10, 80),
                                  vy=-36, vx=random.randint(-14, 14), life=1.5,
                                  size=random.randint(12, 20), color=(170, 215, 255))
            if self.state_left <= 0:
                self._finish_bath()
        elif self.state == "toilet":
            self.dy = math.sin(self.t * 1.6) * 1.2
            self.rot = 0.0
            self.state_left -= dt
            if self.state_left <= 0:
                self._finish_toilet()
        elif self.state == "medicine":
            self.rot = math.sin(self.t * 9) * 6      # 摇头苦脸
            self.dy = 0.0
            self.state_left -= dt
            if self.state_left <= 0:
                self._finish_medicine()
        elif self.state == "sick":
            self.dy = math.sin(self.t * 1.1) * 1.0   # 虚弱地轻轻晃
            self.rot = 0.0
            if random.random() < dt * 0.5:
                self.say("咳咳…", 1.4)
        elif self.state == "play":
            self.rot = 0.0
            self.state_left -= dt
            self.dy = -abs(math.sin(self.t * 6.0)) * 26
            if random.random() < dt * 3:
                self.add_particle(random.choice(["♪", "♫"]),
                                  self.W / 2 + random.randint(-50, 50),
                                  self.H - self.MARGIN_BOT - self.disp_h() + random.randint(0, 60),
                                  vy=-40, life=1.2, size=18, color=(255, 130, 180))
            if self.state_left <= 0:
                self._finish_play()
        elif self.state == "back":
            self.dy = math.sin(self.t * 2.0) * 1.5
            self.rot = 0.0
            self.state_left -= dt
            if self.state_left <= 0:
                self.state = "idle"
        elif self.state in self.mod_states:
            # 模组注册的自定义状态
            st = self.mod_states[self.state]
            self.dy = 0.0
            if st["update"]:
                try:
                    st["update"](self, dt)
                except Exception as ex:
                    print("[MOD] 状态 %s.update 出错: %s" % (self.state, ex), flush=True)
            if st["duration"]:
                self.state_left -= dt
                if self.state_left <= 0:
                    self._leave_mod_state()
        elif self.state == "bye":
            # 退出动画：挥手告别 + 撒星星 + 逐渐淡出
            self.state_left -= dt
            self.rot = math.sin(self.t * 9.0) * 3.0
            self.dy = -abs(math.sin(self.t * 4.0)) * 4
            if random.random() < dt * 6:
                self.add_particle("✨",
                                  self.W / 2 + random.randint(-70, 70),
                                  self.H - self.MARGIN_BOT - self.disp_h() * 0.6,
                                  vy=-50, life=1.4, size=18,
                                  color=(255, 200, 230))
            self.setWindowOpacity(max(0.0, self.opacity * self.state_left / 1.8))
            if self.state_left <= 0:
                self.setWindowOpacity(self.opacity)
                self._close_aux_windows()
                QApplication.quit()

        if self.squash > 0:
            self.squash -= dt
        # 粒子
        alive = []
        for p in self.particles:
            p["t"] += dt
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["vy"] += 14 * dt
            if p["t"] < p["life"]:
                alive.append(p)
        self.particles = alive
        # 桌面泡泡：上升 + 轻微左右漂，超时或飘出窗口顶部消失
        for b in self.bubbles:
            b["t"] += dt
            b["y"] += b["vy"] * dt
            b["x"] += math.sin(b["t"] * 3.0) * 10
        self.bubbles = [b for b in self.bubbles
                        if b["t"] < b["life"] and b["y"] > 10]
        if self.bubble:
            self.bubble["t"] += dt
            if self.bubble["t"] > self.bubble["life"]:
                self.bubble = None
        if self.popup:
            self.popup["t"] += dt
            if self.popup["t"] > self.popup["life"]:
                self.popup = None
        # 活动结束回到 idle：若位置仍贴着屏幕边，就吸附成探头姿势
        # （拖动/落地后的位置尊重用户原样，不在这里改写，否则会「拖不出边缘」）
        if (self.state == "idle"
                and self._prev_state not in ("idle", "drag", "fall")):
            self._startup_peek()
        self._prev_state = self.state
        # 松手后身体摆动阻尼衰减（拖动时保持，非拖动时慢慢回正）
        if self.state != "drag":
            self.drag_swing *= 0.88
        # 转发给模组：每帧钩子 + 状态变化钩子
        if self.mod_apis:
            self._mod_fire("fire_tick", dt)
            old = getattr(self, "_last_mod_state", self.state)
            if self.state != old:
                self._mod_fire("fire_state_change", old, self.state)
            self._last_mod_state = self.state
        self.update()

    # ============ 缩放缓存 ============
    def scaled(self, key):
        h = self.disp_h()
        if self._scaled_cache is None or self._scaled_cache[0] != h:
            self._scaled_cache = (h, {
                k: pm.scaledToHeight(h, Qt.SmoothTransformation) if pm is not None else None
                for k, pm in self.src.items()})
        pm = self._scaled_cache[1].get(key)
        if pm is None:
            # 缓存未命中（例如运行中新增/替换的素材）→ 立即补算，避免回退默认立绘
            src_pm = self.src.get(key)
            if src_pm is not None and not src_pm.isNull():
                pm = src_pm.scaledToHeight(h, Qt.SmoothTransformation)
                self._scaled_cache[1][key] = pm
        return pm

    def popup_pm(self, key):
        pm = self.src.get(key)
        if pm is None:
            return None
        h = int(self.disp_h() * 0.85)
        cur = self._popup_cache.get(key)
        if cur is None or cur[0] != h:
            cur = (h, pm.scaledToHeight(h, Qt.SmoothTransformation))
            self._popup_cache[key] = cur
        return cur[1]

    # ============ 绘制 ============
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform |
                         QPainter.TextAntialiasing)
        # 透明无边框窗口必须每帧清屏，否则上一帧画面会叠在透明背景上形成残影
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.fillRect(self.rect(), Qt.transparent)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        feet_y = self.H - self.MARGIN_BOT
        cx = self.W // 2
        dh = self.disp_h()

        # 影子（被拖起/掉落时缩小；走路步态中身体高度不同略有变化）
        grounded = (self.state in ("idle", "walk", "sleep", "eat", "play", "back",
                                   "bath", "toilet", "sick", "medicine",
                                   "peek", "caps", "eat_file", "bye")
                    or self.state in self.mod_states)
        sw = dh * (0.55 if grounded else 0.34)
        if self.state == "walk" and self.walk_frames:
            sw = dh * self.WALK_SHADOW[self.walk_frame - 1]
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(120, 80, 110, 60 if grounded else 34))
        p.drawEllipse(QRectF(cx - sw / 2, feet_y - 7, sw, 12))

        # 精灵
        key = "idle"
        _sk = self.preview_skin or self.daily_skin   # 手动预览 > 当日节日皮肤
        if self.music_mode and self.state == "idle" and \
                self.src.get("dj") is not None:
            key = "dj"                  # 音乐模式 → 打碟 DJ 立绘
        elif self.state == "idle" and _sk and self.src.get(_sk) is not None:
            key = _sk
        elif self.state == "walk":
            if self.walk_frames:
                key = ("wr" if self.facing > 0 else "wl") + str(self.walk_frame)
            else:
                key = "right" if self.facing > 0 else "left"
        elif self.state == "drag" and self.src.get("drag") is not None:
            key = "drag"                # 被拎起来：委屈生气立绘
        elif self.state == "angry" and self.src.get("angry") is not None:
            key = "angry"               # 炸毛生气立绘
        elif self.state == "lick":
            pk = {-1: "peek_left", 1: "peek_right", 2: "peek_top"}.get(self.peek_side)
            key = "lick" if self.src.get("lick") is not None else \
                (pk if (pk and self.src.get(pk) is not None) else "idle")
        elif self.state == "peek":
            pk = {-1: "peek_left", 1: "peek_right", 2: "peek_top"}.get(self.peek_side)
            key = pk if (pk and self.src.get(pk) is not None) else \
                ("happy" if self.src.get("happy") is not None else "idle")
        elif self.state == "caps":
            ck = "caps_upper" if self.caps_upper else "caps_lower"
            key = ck if self.src.get(ck) is not None else "idle"
        elif self.state == "pomo_alert":
            key = "pomo_alert" if self.src.get("pomo_alert") is not None else \
                ("happy" if self.src.get("happy") is not None else "idle")
        elif self.state in self.mod_states:
            mk = self.mod_states[self.state]["sprite"]
            key = mk if self.src.get(mk) is not None else "idle"
        elif self.state == "eat_file":
            key = "eat" if self.src.get("eat") is not None else "idle"
        elif self.state == "bye":
            key = "bye" if self.src.get("bye") is not None else "happy"
        elif self.state == "sleep":
            key = "sleep"
        elif self.state == "back":
            key = "back"
        elif self.state in ("bath", "toilet", "sick", "medicine") and \
                self.src.get(self.state) is not None:
            key = self.state
        pm = self.scaled(key) or self.scaled("idle")
        if self.state == "eat":
            ek = self.eat_key if self.eat_key else "eat"
            if self.src.get(ek) is not None:
                pm = self.popup_pm(ek) or pm
        k = max(0.0, self.squash) / 0.3
        # 拖拽/扔飞时身体因惯性水平滞后于头部（头跟鼠标，身体甩在后面）
        lag_dx = -self.drag_swing * 28 if self.state in ("drag", "throw", "fall") else 0
        p.save()
        p.translate(cx + lag_dx, feet_y + self.dy)
        p.rotate(self.rot)
        sxv = self.sx * (1 + 0.16 * k)
        syv = self.sy * (1 - 0.18 * k)
        if self.state == "lick" and key == "lick" and self.peek_side > 0:
            p.scale(-sxv, syv)      # 右舔时水平镜像（舔屏立绘默认朝右）
        else:
            p.scale(sxv, syv)
        p.drawPixmap(int(-pm.width() / 2), -pm.height(), pm)
        p.restore()

        # 大小写提示：优先用抱字母立绘，缺少素材时才兜底画字母
        if self.state == "caps" and self.src.get(
                "caps_upper" if self.caps_upper else "caps_lower") is None:
            letter = "A" if self.caps_upper else "a"
            lf = ui_font(max(18, int(dh * 0.30)), bold=True)
            lf.setBold(True)
            p.setFont(lf)
            wob = math.sin(self.t * 5.0)
            p.save()
            p.translate(cx, feet_y - dh * 0.42 + wob * 2)
            p.rotate(wob * 4)
            p.setPen(QPen(QColor(255, 96, 156)))
            p.drawText(QRect(-40, -int(dh * 0.16), 80, int(dh * 0.32)),
                       Qt.AlignCenter, letter)
            p.restore()

        # 探头：新立绘已自带扒边双手，仅在缺少对应立绘时兜底画一只手
        if self.state == "peek" and self.src.get(
                {-1: "peek_left", 1: "peek_right", 2: "peek_top"}.get(
                    self.peek_side)) is None:
            hf = QFont("Segoe UI Emoji", max(14, int(dh * 0.16)))
            p.setFont(hf)
            g = self.screen_geom()
            vis = self.body_w() * self.PEEK_EDGE
            if self.peek_side < 0:
                hx = g.left() + vis - self.x() - 6
            else:
                hx = g.right() - vis - self.x() + 6
            p.drawText(QPointF_c(hx, feet_y - dh * 0.30), "✋")

        # 音乐节奏灯
        self._draw_music_lights(p, feet_y, dh)

        # Q版弹窗（升级/开心）
        if self.popup:
            ppm = self.popup_pm(self.popup["key"])
            if ppm is not None:
                kk = self.popup["t"] / self.popup["life"]
                p.setOpacity(max(0.0, min(1.0, (1 - kk) * 1.6)))
                p.drawPixmap(int(cx - ppm.width() / 2),
                             int(feet_y - dh - ppm.height() * 0.30 - 26 * kk), ppm)
                p.setOpacity(1.0)

        # 摔晕：头顶转圈的小星星（对准头部）
        if self.dizzy > 0:
            hx, hy = self.head_pos()
            f = QFont("Segoe UI Emoji", max(15, int(dh * 0.13)))
            p.setFont(f)
            ph = self.t * 8.0
            p.setOpacity(0.55 + 0.45 * abs(math.sin(ph)))
            p.drawText(QPointF_c(hx - 26 + 22 * math.sin(ph), hy - 4), "💫")
            p.drawText(QPointF_c(hx + 26 + 22 * math.sin(ph + math.pi), hy - 14), "💫")
            p.setOpacity(1.0)

        # 粒子（emoji 预渲染成 Pixmap 缓存后绘制，远快于每帧文本渲染）
        if self.particles:
            for pt in self.particles:
                a = max(0.0, 1.0 - pt["t"] / pt["life"])
                if a <= 0:
                    continue
                pm = self._emoji_pixmap(pt["text"], pt["size"], pt["color"])
                p.setOpacity(a)
                p.drawPixmap(QPointF_c(pt["x"] - pm.width() / 2,
                                      pt["y"] - pm.height() / 2), pm)
            p.setOpacity(1.0)

        # 桌面泡泡：半透明圆 + 高光
        if self.bubbles:
            for b in self.bubbles:
                fade = max(0.0, 1.0 - b["t"] / b["life"])
                r = b["r"]
                p.setPen(QPen(QColor(180, 220, 255, int(180 * fade))))
                p.setBrush(QColor(200, 230, 255, int(70 * fade)))
                p.drawEllipse(QPointF_c(b["x"], b["y"]), r, r)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255, 255, 255, int(200 * fade)))
                p.drawEllipse(QPointF_c(b["x"] - r * 0.32, b["y"] - r * 0.32),
                              r * 0.30, r * 0.30)

        # 桌面便签（常驻，比对话气泡更靠上）
        if self.note:
            self._draw_note(p, feet_y, dh)
        # 气泡
        if self.bubble:
            self._draw_bubble(p, feet_y, dh)

        # 系统监控面板：默认隐藏，只有鼠标悬浮在角色身上才显示（避免遮挡角色）
        if self.show_sysmon and self.hover:
            self._draw_sysmon(p, feet_y, dh, cx)

        # 模组绘制钩子（可在最后叠加自己的画面）
        if self.mod_apis:
            self._mod_fire("fire_draw", p)

    def _draw_sysmon(self, p, feet_y, dh, cx):
        m = self.sysmon
        net = fmt_speed(m.net_in) if m.net_ok else "不可用"
        net_up = fmt_speed(m.net_out) if m.net_ok else "不可用"
        cpu = self.sys_cpu
        load, used, total = self.sys_ram
        nic = self.net_nic or "全部"
        # 面板数据每秒才采集一次，缓存渲染结果，避免每帧做文本布局
        key = (self.size_key, nic, None if cpu is None else int(cpu),
               int(load), net, net_up, tuple(self.sysmon_items))
        if self._sysmon_key != key or self._sysmon_pm is None:
            self._sysmon_pm = self._render_sysmon(cpu, load, net, net_up, nic)
            self._sysmon_key = key
        pm = self._sysmon_pm
        pw, ph = pm.width(), pm.height()
        bw = self.body_w()
        pos = self.sysmon_pos
        if self.state == "peek":      # 探头时显示在探头方向的反侧
            pos = self.PEEK_SYSMON_SIDE.get(self.peek_side, pos)
        # 按位置摆放（auto 仍跟随角色）
        if pos == "left":
            px, py = 2, int(feet_y - dh * 0.72 - ph / 2)
        elif pos == "right":
            px, py = max(2, self.W - pw - 2), int(feet_y - dh * 0.72 - ph / 2)
        elif pos == "top":
            px, py = max(2, (self.W - pw) // 2), 2
        elif pos == "bottom":
            px, py = max(2, (self.W - pw) // 2), max(2, self.H - ph - 2)
        else:      # auto：优先角色右侧 → 左侧 → 都放不下就挪到角色上方
            px = int(cx + bw / 2 + 8)
            if px + pw > self.W - 2:
                px = int(cx - bw / 2 - pw - 8)
            py = int(feet_y - dh * 0.72 - ph / 2)
            if px < 2:                  # 左右都塞不下 → 显示在角色上方，别压住她
                px = int(cx - pw / 2)
                py = 4
        px = max(2, min(px, self.W - pw - 2))            # 永不越界
        py = max(2, min(py, self.H - ph - 2))
        p.drawPixmap(px, py, pm)

    def _render_sysmon(self, cpu, load, net, net_up, nic):
        """把监控面板渲染成一张 Pixmap（内容变化时才会重新调用）。"""
        vals = {"cpu": f"{cpu:.0f}%" if cpu is not None else "…",
                "ram": f"{load}%", "net_in": net, "net_out": net_up,
                # 收发流量换行显示
                "flow": "收 %s\n发 %s" % (fmt_bytes(self.net_recv_total),
                                          fmt_bytes(self.net_sent_total))}
        # 只渲染用户勾选的项目；不显示图标，也不显示网卡标题行
        lines = []
        for k in self.sysmon_items:
            if k not in SYSMON_ITEM_LABELS:
                continue
            label = SYSMON_ITEM_LABELS[k][1]
            parts = str(vals[k]).split("\n")
            for i, part in enumerate(parts):
                lines.append(((label + " ") if i == 0 else "") + part)
        fsz = 8 if self.size_key == "small" else 9
        f = ui_font(fsz)
        fm = QFontMetrics(f)
        pad = 7
        lh = fm.height() + 3
        if lines:
            lw = max(fm.horizontalAdvance(t.strip()) for t in lines)
        else:
            lw = fm.horizontalAdvance("(无项目)")
        pw = lw + pad * 2 + 6
        ph = lh * max(1, len(lines)) + pad * 2 + 2
        pw = min(pw, self.W - 4)                  # 窗口放不下就贴边
        pm = QPixmap(max(1, pw), max(1, ph))
        pm.fill(Qt.transparent)
        pp = QPainter(pm)
        pp.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        pp.setFont(f)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, pw, ph), 8, 8)
        pp.setPen(Qt.NoPen)
        pp.setBrush(QColor(255, 255, 255, 232))
        pp.drawPath(path)
        pp.setBrush(Qt.NoBrush)
        pp.setPen(QPen(QColor(255, 150, 190), 2))
        pp.drawPath(path)
        pp.setPen(QColor(120, 90, 110))
        y = pad
        for t in lines:
            pp.drawText(QRect(pad, y, pw - pad * 2, lh),
                        Qt.AlignVCenter | Qt.TextSingleLine, t.strip())
            y += lh
        pp.end()
        return pm

    def _draw_note(self, p, feet_y, dh):
        """桌面便签：黄色便签卡片，常驻显示在角色上方。"""
        key = ("note", self.note, self.size_key)
        if self._note_key != key or self._note_pm is None:
            self._note_pm = self._render_note(self.note)
            self._note_key = key
        pm = self._note_pm
        bw, bh = pm.width(), pm.height()
        bx = max(6, min(self.W // 2 - bw // 2, self.W - bw - 6))
        by = max(4, feet_y - dh - 10 - bh - 26)
        p.drawPixmap(bx, by, pm)

    def _render_note(self, text):
        """把便签文字渲染成黄色便签卡片（含胶条）。"""
        f = ui_font(11)
        fm = QFontMetrics(f)
        max_w = 190
        lines = []
        for raw in text.split("\n"):
            cur = ""
            for ch in raw:
                if fm.horizontalAdvance(cur + ch) > max_w and cur:
                    lines.append(cur)
                    cur = ch
                else:
                    cur += ch
            lines.append(cur)
        lines = lines[:12] or [""]
        line_h = fm.height() + 3
        pad = 10
        bw = min(240, max(90, max(fm.horizontalAdvance(l) for l in lines)) + pad * 2)
        bh = line_h * len(lines) + pad * 2 + 12
        pm = QPixmap(bw, bh)
        pm.fill(Qt.transparent)
        q = QPainter(pm)
        q.setRenderHint(QPainter.Antialiasing)
        # 便签主体（淡黄，稍旋转感通过顶部胶条表现）
        q.setPen(Qt.NoPen)
        q.setBrush(QColor(255, 244, 170))
        q.drawRoundedRect(0, 8, bw, bh - 8, 8, 8)
        # 顶部胶条
        q.setBrush(QColor(255, 180, 90, 200))
        q.drawRoundedRect(bw // 2 - 26, 0, 52, 14, 4, 4)
        # 文字
        q.setPen(QColor(90, 70, 30))
        q.setFont(f)
        ty = 8 + pad + fm.ascent()
        for l in lines:
            q.drawText(pad, ty, l)
            ty += line_h
        q.end()
        return pm

    def _draw_bubble(self, p, feet_y, dh):
        text = self.bubble["text"]
        # 探头时气泡必须留在屏幕可见的一侧，否则会被推出屏幕、看不到计时
        peek = self.state == "peek"
        max_w = 210
        if peek and self.peek_side in (-1, 1):
            dkey = "left" if self.peek_side == -1 else "right"
            avail = int(self.MARGIN_X + self.body_w() * self.peek_dist[dkey]) - 14
            max_w = max(110, min(210, avail - 26))     # 可见区窄就自动收窄气泡
        # 气泡文本只在 say() 时变化，缓存渲染结果避免每帧做文本换行布局
        key = (text, self.size_key, max_w)
        if self._bubble_key != key or self._bubble_pm is None:
            self._bubble_pm = self._render_bubble(text, max_w)
            self._bubble_key = key
        pm = self._bubble_pm
        bw, bh = pm.width(), self._bubble_bh
        bx, by = self._bubble_pos(bw, bh, feet_y, dh)
        p.drawPixmap(bx, by, pm)

    def _bubble_pos(self, bw, bh, feet_y, dh):
        """气泡在窗口内的位置。探头时贴到屏幕可见的一侧，保证计时看得到。"""
        peek = self.state == "peek"
        if peek and self.peek_side == -1:          # 左探头 → 贴窗口右侧（屏幕内）
            bx = max(4, self.W - bw - 6)
        elif peek and self.peek_side == 1:         # 右探头 → 贴窗口左侧（屏幕内）
            bx = 6
        else:
            bx = max(6, min(self.W // 2 - bw // 2 + 34, self.W - bw - 6))
        if peek and self.peek_side == 2:           # 上探头 → 挪到角色下方
            by = min(max(4, self.H - bh - 6), int(feet_y + 10))
        else:
            by = max(4, feet_y - dh - 10 - bh - 14)
        # 兜底：把气泡整体限制在屏幕内（探头时窗口大半在屏幕外，容易被裁掉）
        try:
            g = self.screen_geom()
            sx = max(g.left() + 4, min(self.x() + bx, g.right() - bw - 4))
            sy = max(g.top() + 4, min(self.y() + by, g.bottom() - bh - 4))
            bx, by = int(sx - self.x()), int(sy - self.y())
        except Exception:
            pass
        return bx, by

    def _render_bubble(self, text, max_w=210):
        """把对话气泡（含尾巴）渲染成一张 Pixmap（换文案时才会重新调用）。"""
        f = ui_font(11)
        fm = QFontMetrics(f)
        pad = 12
        br = fm.boundingRect(QRect(0, 0, max_w, 200), Qt.TextWordWrap, text)
        bw = br.width() + pad * 2
        bh = br.height() + pad + 6
        bx = max(6, min(self.W // 2 - bw // 2 + 34, self.W - bw - 6))
        pm = QPixmap(bw, bh + 14)          # 下方留出尾巴空间
        pm.fill(Qt.transparent)
        pp = QPainter(pm)
        pp.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        pp.setFont(f)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, bw, bh), 10, 10)
        tail = QPainterPath()
        tx = min(max(self.W // 2 - 8 - bx, 16), bw - 30)   # 窗口坐标换算成气泡内坐标
        tail.moveTo(tx, bh - 2)
        tail.lineTo(tx + 16, bh - 2)
        tail.lineTo(tx + 5, bh + 12)
        tail.closeSubpath()
        pp.setPen(Qt.NoPen)
        pp.setBrush(QColor(255, 255, 255, 243))
        pp.drawPath(path)
        pp.drawPath(tail)
        pp.setBrush(Qt.NoBrush)
        pp.setPen(QPen(QColor(255, 150, 190), 2))
        pp.drawPath(path)
        pp.setPen(QColor(92, 70, 88))
        pp.drawText(QRect(pad, pad // 2, bw - pad * 2, bh - pad + 2),
                    Qt.AlignVCenter | Qt.TextWordWrap, text)
        pp.end()
        self._bubble_bh = bh
        return pm

    # ============ 菜单 ============
    def contextMenuEvent(self, e):
        m = QMenu(self)
        if self.state == "sleep":
            m.addAction("☀ 叫醒")
        else:
            sub = m.addMenu("🍡 喂食")
            for food in FOODS:
                sub.addAction(food)
            m.addAction("🎾 玩耍")
            m.addAction("✋ 摸摸头")
            m.addAction("🛁 洗澡")
            m.addAction("🚽 上厕所")
            if self.state == "sick" or self.health < self.SICK_HEALTH + 10:
                m.addAction("💊 吃药")
            m.addAction("😴 睡觉")
            m.addSeparator()
        a_sys = m.addAction("📊 系统监控")
        a_sys.setCheckable(True)
        a_sys.setChecked(self.show_sysmon)
        a_tb = m.addAction("📈 任务栏监控")
        a_tb.setCheckable(True)
        a_tb.setChecked(self.show_taskbar)
        if self.show_sysmon:
            mset = m.addMenu("⚙ 监控设置")
            mitem = mset.addMenu("显示项目")
            for k, (ico, label) in SYSMON_ITEM_LABELS.items():
                a = mitem.addAction(f"{ico} {label}")
                a.setCheckable(True)
                a.setChecked(k in self.sysmon_items)
                a.setData("item:" + k)
            mpos = mset.addMenu("显示位置")
            for k, label in SYSMON_POSITIONS.items():
                a = mpos.addAction(label)
                a.setCheckable(True)
                a.setChecked(self.sysmon_pos == k)
                a.setData("pos:" + k)
            nics = self.sysmon.nics()
            if nics:
                mnic = m.addMenu("🌐 监控网卡")
                a_all = mnic.addAction("全部网卡（默认）")
                a_all.setCheckable(True)
                a_all.setChecked(self.net_nic is None)
                a_all.setData("nic:")
                for nic in nics:
                    a = mnic.addAction(nic)
                    a.setCheckable(True)
                    a.setChecked(self.net_nic == nic)
                    a.setData("nic:" + nic)
            elif self.sysmon.psutil is None:
                m.addAction("🌐 网速需安装 psutil")
        mpomo = m.addMenu("🍅 番茄钟")
        for label, secs in (("▶ 5 分钟", 300), ("▶ 15 分钟", 900),
                            ("▶ 25 分钟", 1500), ("▶ 45 分钟", 2700)):
            a = mpomo.addAction(label)
            a.setData("pomo:%d" % secs)
        a_custom = mpomo.addAction("⏱ 自定义时长…")
        a_custom.setData("pomo:custom")
        if self.pomo_end > 0:
            a_cancel = mpomo.addAction("⏹ 取消番茄钟")
            a_cancel.setData("pomo:cancel")
        a_busy = m.addAction("🙈 我没空模式")
        a_busy.setCheckable(True)
        a_busy.setChecked(self.busy_mode)
        m.addAction("👅 舔屏幕")
        a_music = m.addAction("🎵 音乐模式")
        a_music.setCheckable(True)
        a_music.setChecked(self.music_mode)
        mdev = m.addMenu("🎧 音乐设备")
        try:
            import soundcard as sc
            _devs = [mm.name for mm in sc.all_microphones(include_loopback=True)]
        except Exception:
            _devs = []
        a_auto = mdev.addAction("默认扬声器")
        a_auto.setCheckable(True)
        a_auto.setChecked(not self.music_device_name)
        for _dn in _devs:
            _da = mdev.addAction("🎧 " + _dn)
            _da.setCheckable(True)
            _da.setChecked(_dn == self.music_device_name)
        m.addAction("🎛 设置…")
        m.addAction("🖼 刷新托盘图标")
        m.addAction("🧩 模组管理器")
        if self.show_taskbar:
            a_lock = m.addAction("🔓 解锁监控条" if self.tbmon_locked
                                 else "📌 锁定监控条（不可拖动）")
            a_lock.setCheckable(True)
            a_lock.setChecked(self.tbmon_locked)
            m.addAction("↩ 监控条回到自动位置")
        mod_acts = []
        for ai, _api in enumerate(self.mod_apis):
            for mi, (label, _cb) in enumerate(_api._menu_actions):
                mod_acts.append((label, ai, mi))
        if mod_acts:
            mmod = m.addMenu("🧩 模组")
            for label, ai, mi in mod_acts:
                a = mmod.addAction(label)
                a.setData("modact:%d:%d" % (ai, mi))
        # 模组注册的顶层菜单项（直接铺在右键菜单上，不在子菜单里）
        for ai, _api in enumerate(self.mod_apis):
            for ti, (label, _cb) in enumerate(_api._top_menu_actions):
                a = m.addAction(label)
                a.setData("modtop:%d:%d" % (ai, ti))
        msize = m.addMenu("📏 大小")
        for k, label in (("small", "小"), ("medium", "中"), ("large", "大")):
            a = msize.addAction(label)
            a.setCheckable(True)
            a.setChecked(self.size_key == k)
            a.setData("size:" + k)
        mop = m.addMenu("👻 透明度")
        for v in (1.0, 0.8, 0.6):
            a = mop.addAction(f"{int(v * 100)}%")
            a.setCheckable(True)
            a.setChecked(abs(self.opacity - v) < 0.01)
            a.setData("op:" + str(v))
        a_top = m.addAction("📌 窗口置顶")
        a_top.setCheckable(True)
        a_top.setChecked(self.topmost)
        m.addAction("🗒 便签")
        m.addAction("🙈 隐藏桌宠")
        a_auto = m.addAction("🚀 开机自启")
        a_auto.setCheckable(True)
        a_auto.setChecked(autostart_exists())
        m.addSeparator()
        m.addAction("📋 柒葱的状态")
        m.addAction("🚪 退出")
        chosen = m.exec(e.globalPos())
        if chosen is None:
            return
        txt = chosen.text()
        data = chosen.data()
        if isinstance(data, str) and data.startswith("size:"):
            self.set_size(data.split(":")[1])
            self.save()
        elif isinstance(data, str) and data.startswith("op:"):
            self.opacity = float(data.split(":")[1])
            self.setWindowOpacity(self.opacity)
            self.save()
        elif txt == "☀ 叫醒":
            self.wake_up()
        elif txt in FOODS:
            self.feed(txt)
        elif txt == "🎾 玩耍":
            self.play()
        elif txt == "✋ 摸摸头":
            self.pet_head()
        elif txt == "🛁 洗澡":
            self.bath_now()
        elif txt == "🚽 上厕所":
            self.toilet_now()
        elif txt == "💊 吃药":
            self.medicine_now()
        elif txt == "😴 睡觉":
            self.sleep_now()
        elif isinstance(data, str) and data.startswith("nic:"):
            self.net_nic = data.split(":", 1)[1] or None
            self.sysmon._net_last = None      # 换网卡后重新取基准
            self.net_in = self.net_out = 0.0
            self.save()
            self.update()
        elif isinstance(data, str) and data.startswith("item:"):
            k = data.split(":", 1)[1]
            if k in self.sysmon_items:
                if len(self.sysmon_items) > 1:      # 至少保留一项
                    self.sysmon_items.remove(k)
            else:
                self.sysmon_items.append(k)
            # 保持固定显示顺序
            self.sysmon_items = [x for x in SYSMON_ITEM_LABELS
                                 if x in self.sysmon_items]
            self.save()
            self.update()
        elif isinstance(data, str) and data.startswith("pos:"):
            self.sysmon_pos = data.split(":", 1)[1]
            self.save()
            self.update()
        elif txt == "📈 任务栏监控":
            self.show_taskbar = not self.show_taskbar
            self.interact()
            if self.show_taskbar:
                self.say("任务栏监控打开啦～", 2.4)
                self.update_sys()           # 立刻填一次数据
            self._ensure_taskbar()
            self.save()
        elif txt == "📊 系统监控":
            self.show_sysmon = not self.show_sysmon
            self.interact()
            if self.show_sysmon:
                self.say("柒葱帮你盯着电脑状态喵！", 2.6)
            self.update()
            self.save()
        elif isinstance(data, str) and data.startswith("pomo:"):
            v = data.split(":", 1)[1]
            if v == "cancel":
                self.cancel_pomo()
            elif v == "custom":
                mins, ok = QInputDialog.getDouble(
                    self, "番茄钟", "请输入时长（分钟）：", 25.0, 0.1, 600.0, 1)
                if ok:
                    self.start_pomo(mins * 60.0)
            else:
                try:
                    self.start_pomo(float(v))
                except ValueError:
                    pass
        elif txt == "🙈 我没空模式":
            self.busy_mode = not self.busy_mode
            self.say(random.choice(
                LINES["busy_on" if self.busy_mode else "busy_off"]), 2.8)
            self.save()
        elif isinstance(data, str) and data.startswith("modact:"):
            _, ai, mi = data.split(":")
            try:
                api = self.mod_apis[int(ai)]
                api._menu_actions[int(mi)][1]()
            except Exception as ex:
                print("[MOD] 菜单动作出错: %s" % ex, flush=True)
        elif isinstance(data, str) and data.startswith("modtop:"):
            _, ai, ti = data.split(":")
            try:
                api = self.mod_apis[int(ai)]
                api._top_menu_actions[int(ti)][1]()
            except Exception as ex:
                print("[MOD] 顶层菜单动作出错: %s" % ex, flush=True)
        elif txt == "🧩 模组管理器":
            self.open_mod_manager()
        elif txt in ("📌 锁定监控条（不可拖动）", "🔓 解锁监控条"):
            self.tbmon_locked = not self.tbmon_locked
            if self.tbmon is not None:
                self.tbmon.locked = self.tbmon_locked
            self.save()
        elif txt == "↩ 监控条回到自动位置":
            self.tbmon_pos = None
            if self.tbmon is not None:
                self.tbmon.custom_pos = None
                self.tbmon._place()
            self.save()
        elif txt == "🖼 刷新托盘图标":
            pm = pm_or_none("tray.png")
            if pm is not None and self.tray is not None:
                self.tray.setIcon(QIcon(pm))
                self.say("托盘图标刷新啦～", 2.2)
            else:
                self.say("找不到 assets/tray.png 喵…", 2.6)
        elif txt == "👅 舔屏幕":
            self.lick_screen()
        elif txt == "🎵 音乐模式":
            self.toggle_music_mode()
        elif txt == "默认扬声器":
            self.music_device_name = ""
            self._restart_music_worker()
            self.say("音乐设备：默认扬声器", 2.6)
        elif txt.startswith("🎧 "):
            self.music_device_name = txt[2:]
            self._restart_music_worker()
            self.say("音乐设备换成：\n%s" % self.music_device_name, 3.0)
        elif txt == "🎛 设置…":
            self.open_settings()
        elif txt == "🛠 开发者模式":
            self.open_dev_dialog()
        elif txt == "📌 窗口置顶":
            self.topmost = not self.topmost
            self.setWindowFlag(Qt.WindowStaysOnTopHint, self.topmost)
            self.show()
        elif txt == "🗒 便签":
            self.edit_note()
        elif txt == "🙈 隐藏桌宠":
            self.hide()
            if self.tray is not None:
                self.tray.showMessage(NAME, "柒葱藏到托盘啦，双击托盘图标叫回来～",
                                      QSystemTrayIcon.Information, 3000)
        elif txt == "🚀 开机自启":
            self.toggle_autostart(not autostart_exists())
        elif txt == "📋 柒葱的状态":
            self.show_status()
        elif txt == "🚪 退出":
            self.quit_app()

    def edit_note(self):
        """桌面便签：记一句话，她举着常驻显示。"""
        text, ok = QInputDialog.getMultiLineText(
            self, "桌面便签", "记点什么？柒葱帮你举着：", self.note)
        if not ok:
            return
        self.note = text.strip()
        if self.note:
            self.say("便签记好啦～", 2.0)
        self.save()
        self.update()

    def toggle_autostart(self, enable: bool):
        pth = autostart_path()
        try:
            if enable:
                pth.parent.mkdir(parents=True, exist_ok=True)
                content = '@echo off\r\nstart "" "%s" "%s"\r\n' % (
                    sys.executable, str(BASE_DIR / "pet.py"))
                pth.write_bytes(content.encode("ascii"))
            elif pth.exists():
                pth.unlink()
        except Exception as ex:
            QMessageBox.warning(self, NAME, f"设置开机自启失败：{ex}")

    # ---------------- 模组(mod) ----------------
    def scan_mods(self):
        """扫描 mods 目录：每个子文件夹 = 一个模组，需含 mod.json。"""
        found = []
        if not MODS_DIR.exists():
            try:
                MODS_DIR.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            return found
        for d in sorted(MODS_DIR.iterdir()):
            if not d.is_dir() or d.name.startswith(("_", ".")):
                continue
            meta_f = d / "mod.json"
            if not meta_f.exists():
                continue
            try:
                meta = json.loads(meta_f.read_text("utf-8"))
            except Exception as ex:
                print("[MOD] %s 的 mod.json 解析失败: %s" % (d.name, ex), flush=True)
                continue
            found.append({
                "id": meta.get("id") or d.name,
                "name": meta.get("name", d.name),
                "version": meta.get("version", "1.0"),
                "author": meta.get("author", ""),
                "description": meta.get("description", ""),
                "entry": meta.get("entry", "main.py"),
                "dir": d,
            })
        return found

    def load_mods(self):
        """按启用列表加载模组。单个模组出错不影响其它模组和主程序。"""
        self.unload_mods()
        self.available_mods = self.scan_mods()
        for info in self.available_mods:
            if info["id"] not in self.enabled_mods:
                continue
            entry = info["dir"] / info["entry"]
            if not entry.exists():
                alt = info["dir"] / "mod.py"        # 兼容 mod.py 命名
                if alt.exists():
                    entry = alt
                else:
                    print("[MOD] %s 缺少入口文件 %s" % (info["id"], info["entry"]),
                          flush=True)
                    continue
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location(
                    "mod_" + info["id"], str(entry))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                api = ModAPI(self, info["dir"], info["id"])
                if hasattr(mod, "setup"):
                    mod.setup(api)
                elif hasattr(mod, "on_load"):
                    mod.on_load(api)
                self.loaded_mods.append({"id": info["id"], "mod": mod, "api": api})
                self.mod_apis.append(api)
                print("[MOD] 已加载：%s (%s)" % (info["name"], info["id"]), flush=True)
            except Exception as ex:
                print("[MOD] 加载失败 %s: %s" % (info["id"], ex), flush=True)
        self.mod_api = self.mod_apis[0] if self.mod_apis else None

    def unload_mods(self):
        """卸载所有模组（会调用其 teardown(api)，若有）。"""
        for item in self.loaded_mods:
            try:
                if hasattr(item["mod"], "teardown"):
                    item["mod"].teardown(item["api"])
                elif hasattr(item["mod"], "on_unload"):
                    item["mod"].on_unload(item["api"])
            except Exception as ex:
                print("[MOD] 卸载出错 %s: %s" % (item["id"], ex), flush=True)
        self.loaded_mods = []
        self.mod_apis = []
        self.mod_api = None
        self.mod_states = {}

    def _mod_fire(self, hook, *args):
        """把事件转发给所有模组（各模组异常隔离）。"""
        for api in self.mod_apis:
            try:
                getattr(api, hook)(*args)
            except Exception as ex:
                print("[MOD] %s.%s 出错: %s" % (api.id, hook, ex), flush=True)

    # ---------- 模组自定义状态机 ----------
    def enter_state(self, name):
        """进入（可能是模组注册的）状态；自定义状态会调用其 enter 钩子。"""
        st = self.mod_states.get(name)
        if st is None:
            self.state = name
            return
        self.state = name
        if st["duration"]:
            self.state_left = st["duration"]
        if st["enter"]:
            try:
                st["enter"](self)
            except Exception as ex:
                print("[MOD] 状态 %s.enter 出错: %s" % (name, ex), flush=True)

    def _leave_mod_state(self):
        """离开当前自定义状态：调用 exit 钩子并回到 idle。"""
        st = self.mod_states.get(self.state)
        if st and st["exit"]:
            try:
                st["exit"](self)
            except Exception as ex:
                print("[MOD] 状态 %s.exit 出错: %s" % (self.state, ex), flush=True)
        self.state = "idle"

    def reload_mods(self):
        self.load_mods()
        self.update()

    def open_mod_manager(self):
        """模组管理器：勾选启用/禁用，确定后保存并热重载。"""
        dlg = QDialog(self)
        dlg.setWindowTitle("🧩 模组管理器")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("勾选要启用的模组（确定后立即生效）："))
        self.available_mods = self.scan_mods()
        boxes = {}
        if not self.available_mods:
            lay.addWidget(QLabel(
                "（mods 文件夹下还没有模组）\n"
                "放法：mods/我的模组/mod.json + 我的模组/main.py"))
        for info in self.available_mods:
            txt = "%s  [%s]  v%s" % (info["name"], info["id"], info["version"])
            if info["author"]:
                txt += "  by " + info["author"]
            cb = QCheckBox(txt)
            cb.setChecked(info["id"] in self.enabled_mods)
            if info["description"]:
                cb.setToolTip(info["description"])
            lay.addWidget(cb)
            boxes[info["id"]] = cb
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)
        if dlg.exec():
            self.enabled_mods = [mid for mid, cb in boxes.items() if cb.isChecked()]
            self.save()
            self.reload_mods()

    def open_settings(self):
        """统一设置窗口：外观 / 探头 / 行为 / 监控 / 模组。改动实时预览，
        「应用」保存、「确定」保存并关闭、「取消」还原到打开时的状态。"""
        snap = dict(
            font=UI_FONT_FAMILY,
            size=self.size_key, opacity=self.opacity, topmost=self.topmost,
            peek=dict(self.peek_dist), vx=self.WALK_VX, sleep=self.AUTO_SLEEP_SEC,
            busy=self.busy_mode, pomo_notify=self.pomo_notify,
            sysmon=self.show_sysmon,
            items=list(self.sysmon_items), pos=self.sysmon_pos,
            tb=self.show_taskbar, tb_lock=self.tbmon_locked,
            tb_op=self.tbmon_opacity, tb_pos=self.tbmon_pos,
            m_low=self.music_low_sens, m_high=self.music_high_sens)
        dlg = QDialog(self)
        dlg.setWindowTitle("🎛 柒葱设置  Ver " + VERSION)
        dlg.setMinimumWidth(440)
        root = QVBoxLayout(dlg)
        tabs = QTabWidget(dlg)
        root.addWidget(tabs)

        # ---- 外观 ----
        t1 = QWidget(); f1 = QFormLayout(t1)
        sz_cb = QComboBox()
        for k, lab in (("small", "小"), ("medium", "中"), ("large", "大")):
            sz_cb.addItem(lab, k)
        sz_cb.setCurrentIndex(self.SIZE_ORDER.index(self.size_key))
        f1.addRow("角色大小", sz_cb)
        op_v = QSlider(Qt.Horizontal); op_v.setRange(40, 100)
        op_v.setValue(int(self.opacity * 100))
        f1.addRow("窗口不透明度", op_v)
        top_cb = QCheckBox("窗口始终置顶"); top_cb.setChecked(self.topmost)
        f1.addRow("", top_cb)
        font_cb = QComboBox()
        fams = QFontDatabase.families()
        prefer = ["Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "SimSun",
                  "Noto Sans SC", "Source Han Sans SC", "Segoe UI", "Arial"]
        ordered = [f for f in prefer if f in fams] + \
                  [f for f in fams if f not in prefer]
        font_cb.addItems(ordered)
        if UI_FONT_FAMILY in ordered:
            font_cb.setCurrentText(UI_FONT_FAMILY)
        f1.addRow("全局字体（规避版权）", font_cb)
        tabs.addTab(t1, "外观")

        # ---- 探头 ----
        t2 = QWidget(); f2 = QFormLayout(t2)
        peek_sp = {}
        for key, lab in (("left", "左边缘露出比例"), ("right", "右边缘露出比例"),
                         ("top", "上边缘露出比例")):
            sp = QDoubleSpinBox(); sp.setRange(0.10, 1.50)
            sp.setSingleStep(0.05); sp.setDecimals(2)
            sp.setValue(self.peek_dist[key])
            f2.addRow(lab, sp); peek_sp[key] = sp
        tabs.addTab(t2, "探头")

        # ---- 行为 ----
        t3 = QWidget(); f3 = QFormLayout(t3)
        vx_v = QSpinBox(); vx_v.setRange(10, 300); vx_v.setSingleStep(5)
        vx_v.setValue(int(self.WALK_VX)); f3.addRow("走路速度 (px/秒)", vx_v)
        sl_v = QSpinBox(); sl_v.setRange(30, 3600); sl_v.setSingleStep(30)
        sl_v.setValue(int(self.AUTO_SLEEP_SEC))
        f3.addRow("多久不理就入睡 (秒)", sl_v)
        busy_cb = QCheckBox("我没空模式（不乱跑，自己照顾自己）")
        busy_cb.setChecked(self.busy_mode); f3.addRow("", busy_cb)
        notify_cb = QCheckBox("番茄钟结束时发送系统通知")
        notify_cb.setChecked(self.pomo_notify); f3.addRow("", notify_cb)
        tabs.addTab(t3, "行为")

        # ---- 监控 ----
        t4 = QWidget(); f4 = QFormLayout(t4)
        sys_cb = QCheckBox("系统信息面板（鼠标悬浮角色才显示）")
        sys_cb.setChecked(self.show_sysmon); f4.addRow("", sys_cb)
        item_cbs = {}
        for k, (ico, lab) in SYSMON_ITEM_LABELS.items():
            cb = QCheckBox(lab); cb.setChecked(k in self.sysmon_items)
            f4.addRow("　显示项", cb); item_cbs[k] = cb
        pos_cb = QComboBox()
        pos_keys = list(SYSMON_POSITIONS)
        for k in pos_keys:
            pos_cb.addItem(SYSMON_POSITIONS[k], k)
        pos_cb.setCurrentIndex(pos_keys.index(self.sysmon_pos))
        f4.addRow("面板位置", pos_cb)
        tb_cb = QCheckBox("显示任务栏监控条"); tb_cb.setChecked(self.show_taskbar)
        f4.addRow("", tb_cb)
        tb_lock_cb = QCheckBox("锁定监控条位置（不可拖动）")
        tb_lock_cb.setChecked(self.tbmon_locked); f4.addRow("", tb_lock_cb)
        tb_op_v = QSlider(Qt.Horizontal); tb_op_v.setRange(15, 100)
        tb_op_v.setValue(int(self.tbmon_opacity * 100))
        f4.addRow("监控条不透明度", tb_op_v)
        tabs.addTab(t4, "监控")

        # ---- 音乐（节奏灯）----
        t7 = QWidget(); f7 = QFormLayout(t7)
        f7.addRow(QLabel("音乐模式的节奏灯灵敏度（进入音乐模式生效）"))
        low_v = QSlider(Qt.Horizontal); low_v.setRange(20, 300)
        low_v.setValue(int(self.music_low_sens * 100))
        f7.addRow("低音灵敏度", low_v)
        high_v = QSlider(Qt.Horizontal); high_v.setRange(20, 300)
        high_v.setValue(int(self.music_high_sens * 100))
        f7.addRow("高音灵敏度", high_v)
        tabs.addTab(t7, "音乐")

        # ---- 皮肤 / 节日（调试）----
        t6 = QWidget(); f6 = QFormLayout(t6)
        _k0, info0 = today_festival()
        f6.addRow(QLabel("今天：%s" % (info0["name"] if info0 else "普通的一天")))
        entries = all_festival_entries()

        # 按日期从小到大排序（农历节日取下一个未来日期的月-日）
        import datetime as _dt
        _today = _dt.date.today()

        def _dkey(e):
            _k, _n, _ds, _i = e
            if "date" in _i:
                return _i["date"]
            if _i.get("term") and _ds:
                try:
                    _p = [int(x) for x in _ds.split("-")]
                    return (_p[1], _p[2])
                except Exception:
                    return (12, 31)
            fut = sorted(d for d in _i.get("lunar", [])
                         if _dt.date(*d) >= _today)
            if fut:
                return (fut[0][1], fut[0][2])
            old = min(_i.get("lunar", [(9999, 12, 31)]))
            return (old[1], old[2])

        entries = sorted(entries, key=_dkey)
        fest_map = {k: info for k, _, _, info in entries}

        # 节日皮肤一览表：直观看到哪个节日缺皮肤
        tw = QTableWidget(len(entries), 4)
        tw.setHorizontalHeaderLabels(["日期", "节日", "皮肤", "状态"])
        tw.verticalHeader().setVisible(False)
        tw.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tw.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        tw.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        for r, (k, name, dstr, info) in enumerate(entries):
            sk = self.skin_for(k, info)
            has_sk = bool(sk)
            tw.setItem(r, 0, QTableWidgetItem(dstr))
            tw.setItem(r, 1, QTableWidgetItem(name))
            tw.setItem(r, 2, QTableWidgetItem(sk if sk else "—"))
            it = QTableWidgetItem("✓ 已有" if has_sk else "✗ 缺皮肤")
            it.setForeground(QColor(30, 160, 60) if has_sk
                             else QColor(220, 60, 60))
            tw.setItem(r, 3, it)
        tw.setFixedHeight(min(300, 30 * len(entries) + 34))
        f6.addRow(tw)

        skin_cb = QComboBox()
        for k, name, dstr, info in entries:
            skin_cb.addItem("%s（%s）" % (name, dstr), k)
        if _k0:      # 默认选中今天的节日
            _i0 = next((i for i, (k, *_r) in enumerate(entries) if k == _k0), -1)
            if _i0 >= 0:
                skin_cb.setCurrentIndex(_i0)
        f6.addRow("日子", skin_cb)
        tw.clicked.connect(
            lambda idx: skin_cb.setCurrentIndex(idx.row())
            if 0 <= idx.row() < skin_cb.count() else None)
        btn_prev = QPushButton("👁 预览该皮肤")
        btn_test = QPushButton("🔔 测试提醒")
        btn_restore = QPushButton("↩ 恢复默认皮肤")
        cb_cut = QCheckBox("导入时自动去除白底（已带透明的图不受影响）")
        cb_cut.setChecked(True)
        btn_imp = QPushButton("📁 导入皮肤图片…")
        btn_clr = QPushButton("🗑 清除该日子的皮肤")
        f6.addRow(btn_prev); f6.addRow(btn_test); f6.addRow(btn_restore)
        f6.addRow(cb_cut); f6.addRow(btn_imp); f6.addRow(btn_clr)

        def do_preview():
            k = skin_cb.currentData()
            info = fest_map.get(k, {})
            sk = self.skin_for(k, info)      # 含用户导入的皮肤
            if sk:
                self.preview_skin = sk
                self.say("预览皮肤：%s" % info.get("name", ""), 2.8)
            else:
                self.say("这个日子还没有专属皮肤喵…", 2.8)
            self.update()

        def do_test():
            info = fest_map.get(skin_cb.currentData(), {})
            self.say(info.get("line", "今天是个好日子～"), 4.0)
            self.add_particle(info.get("particle", "🎉"),
                              self.W / 2,
                              self.H - self.MARGIN_BOT - self.disp_h() * 0.6,
                              vy=-46, life=1.6, size=20)

        def do_restore():
            self.preview_skin = None         # 只清预览，保留当日节日皮肤
            self.update()

        def do_import():
            k = skin_cb.currentData()
            info = fest_map.get(k, {})
            path, _f = QFileDialog.getOpenFileName(
                dlg, "选择皮肤图片", "",
                "图片 (*.png *.jpg *.jpeg *.webp *.bmp)")
            if not path:
                return
            try:
                img = self._process_skin_image(path, cb_cut.isChecked())
                sk = "skin_custom_%s" % k
                out = ASSET_DIR / (sk + ".png")
                img.save(str(out))
                pm = QPixmap(str(out))
                if pm.isNull():
                    self.say("图片读取失败喵…", 2.8)
                    return
                self.src[sk] = pm
                self._scaled_cache = None        # 新素材要重建缩放缓存才能显示
                self._popup_cache = {}
                self.festival_skins[k] = sk
                self.preview_skin = sk           # 导入后立刻换上看效果
                self.save()
                self.update()
                self.say("皮肤导入成功！已为 %s 换上～（↩ 可还原）"
                         % info.get("name", ""), 3.6)
            except Exception as ex:
                self.say("导入失败：%s" % ex, 3.2)

        def do_clear():
            k = skin_cb.currentData()
            sk = self.festival_skins.pop(k, None)
            if not sk:
                self.say("这个日子还没有导入过皮肤哦", 2.6)
                return
            self.src.pop(sk, None)
            self._scaled_cache = None
            self._popup_cache = {}
            try:
                (ASSET_DIR / (sk + ".png")).unlink(missing_ok=True)
            except Exception:
                pass
            if self.daily_skin == sk:
                self.daily_skin = None
            if self.preview_skin == sk:
                self.preview_skin = None
            self.save()
            self.update()
            self.say("已清除该日子的皮肤", 2.4)

        btn_prev.clicked.connect(do_preview)
        btn_test.clicked.connect(do_test)
        btn_restore.clicked.connect(do_restore)
        btn_imp.clicked.connect(do_import)
        btn_clr.clicked.connect(do_clear)
        tabs.addTab(t6, "皮肤/节日")

        # ---- 模组 ----
        t5 = QWidget(); f5 = QFormLayout(t5)
        f5.addRow(QLabel("模组放在 mods/ 下，每个子文件夹一个模组。"))
        btn_mod = QPushButton("🧩 打开模组管理器")
        btn_mod.clicked.connect(self.open_mod_manager)
        f5.addRow(btn_mod)
        tabs.addTab(t5, "模组")

        # ---- 实时应用（预览）----
        def apply_live(*_a):
            global UI_FONT_FAMILY
            fam = font_cb.currentText()
            if fam and fam != UI_FONT_FAMILY:
                UI_FONT_FAMILY = fam
                self._bubble_key = None      # 字体变了 → 缓存重渲染
                self._sysmon_key = None
            self.opacity = op_v.value() / 100.0
            self.setWindowOpacity(self.opacity)
            self.topmost = top_cb.isChecked()
            self.setWindowFlag(Qt.WindowStaysOnTopHint, self.topmost)
            self.show()
            if sz_cb.currentData() and sz_cb.currentData() != self.size_key:
                self.set_size(sz_cb.currentData())
            for k in peek_sp:
                self.peek_dist[k] = float(peek_sp[k].value())
            if self.state == "peek":
                self._apply_peek_pos()
            self.WALK_VX = float(vx_v.value())
            self.AUTO_SLEEP_SEC = int(sl_v.value())
            self.busy_mode = busy_cb.isChecked()
            self.pomo_notify = notify_cb.isChecked()
            self.show_sysmon = sys_cb.isChecked()
            picked = [k for k, cb in item_cbs.items() if cb.isChecked()]
            self.sysmon_items = picked or ["cpu"]
            self.sysmon_pos = pos_cb.currentData()
            self.show_taskbar = tb_cb.isChecked()
            self.tbmon_locked = tb_lock_cb.isChecked()
            self.tbmon_opacity = tb_op_v.value() / 100.0
            self.music_low_sens = low_v.value() / 100.0
            self.music_high_sens = high_v.value() / 100.0
            if self.tbmon is not None:
                self.tbmon.locked = self.tbmon_locked
                self.tbmon.opacity = self.tbmon_opacity
                self.tbmon.update()
            self._ensure_taskbar()
            self.update()

        for w in (op_v, vx_v, sl_v, tb_op_v, low_v, high_v):
            w.valueChanged.connect(apply_live)
        for w in (top_cb, busy_cb, sys_cb, tb_cb, tb_lock_cb, notify_cb):
            w.stateChanged.connect(apply_live)
        for w in item_cbs.values():
            w.stateChanged.connect(apply_live)
        for w in peek_sp.values():
            w.valueChanged.connect(apply_live)
        sz_cb.currentIndexChanged.connect(apply_live)
        pos_cb.currentIndexChanged.connect(apply_live)
        font_cb.currentIndexChanged.connect(apply_live)

        # ---- 底部：应用 / 确定 / 取消 ----
        bar = QHBoxLayout()
        ver_lab = QLabel('<a href="#ver" style="color:#999;">Ver %s</a>' % VERSION)
        ver_lab.setStyleSheet("color:#999;")
        ver_lab.setToolTip("点击查看版本迭代记录")
        ver_lab.setOpenExternalLinks(False)
        ver_lab.setTextInteractionFlags(Qt.TextBrowserInteraction)
        bar.addWidget(ver_lab)

        def show_version_log(_url=""):
            lines = []
            for v, desc in VERSION_LOG:
                mark = "●" if v == VERSION else "○"
                lines.append("%s <b>Ver %s</b><br>&nbsp;&nbsp;%s" % (mark, v, desc))
            box = QMessageBox(dlg)
            box.setWindowTitle("版本迭代")
            box.setTextFormat(Qt.RichText)
            box.setText("<br><br>".join(lines))
            box.setStandardButtons(QMessageBox.Ok)
            box.exec()

        ver_lab.linkActivated.connect(show_version_log)
        b_apply = QPushButton("应用")
        b_ok = QPushButton("确定")
        b_cancel = QPushButton("取消")
        bar.addStretch(1)
        for b in (b_apply, b_ok, b_cancel):
            bar.addWidget(b)
        root.addLayout(bar)

        def do_apply():
            apply_live()
            self.save()

        def do_ok():
            do_apply()
            dlg.accept()

        def do_cancel():
            global UI_FONT_FAMILY
            UI_FONT_FAMILY = snap["font"]
            self._bubble_key = None
            self.size_key = snap["size"]
            self.set_size(self.size_key)
            self.opacity = snap["opacity"]
            self.setWindowOpacity(self.opacity)
            self.topmost = snap["topmost"]
            self.setWindowFlag(Qt.WindowStaysOnTopHint, self.topmost)
            self.show()
            self.peek_dist = dict(snap["peek"])
            self.WALK_VX = snap["vx"]
            self.AUTO_SLEEP_SEC = snap["sleep"]
            self.busy_mode = snap["busy"]
            self.pomo_notify = snap["pomo_notify"]
            self.show_sysmon = snap["sysmon"]
            self.sysmon_items = list(snap["items"])
            self.sysmon_pos = snap["pos"]
            self.show_taskbar = snap["tb"]
            self.tbmon_locked = snap["tb_lock"]
            self.tbmon_opacity = snap["tb_op"]
            self.tbmon_pos = snap["tb_pos"]
            self.music_low_sens = snap["m_low"]
            self.music_high_sens = snap["m_high"]
            if self.tbmon is not None:
                self.tbmon.locked = self.tbmon_locked
                self.tbmon.opacity = self.tbmon_opacity
                self.tbmon.custom_pos = (tuple(self.tbmon_pos)
                                         if self.tbmon_pos else None)
                self.tbmon._place()
                self.tbmon.update()
            self._ensure_taskbar()
            if self.state == "peek":
                self._apply_peek_pos()
            self.update()
            dlg.reject()

        b_apply.clicked.connect(do_apply)
        b_ok.clicked.connect(do_ok)
        b_cancel.clicked.connect(do_cancel)
        dlg.exec()

    def open_dev_dialog(self):
        """兼容旧调用：开发者模式 = 统一设置窗口。"""
        self.open_settings()

    def show_status(self):
        def bar(v, n=10):
            f = int(round(v / 100 * n))
            return "█" * f + "░" * (n - f)

        QMessageBox.information(
            self, f"{NAME}的状态",
            f"等级 Lv.{self.level}    经验 {self.exp}/{self.exp_need()}\n\n"
            f"饱食度  {bar(self.hunger)}  {int(self.hunger)}\n"
            f"心  情  {bar(self.mood)}  {int(self.mood)}\n"
            f"卫  生  {bar(self.hyg)}  {int(self.hyg)}\n"
            f"健  康  {bar(self.health)}  {int(self.health)}\n\n"
            f"小提示：摸摸头、喂食、玩耍都能涨经验哦~\n"
            f"太脏会生病，生病要吃药；{self.AUTO_SLEEP_SEC // 60}分钟"
            f"不理她就会自己睡着~")

    def quit_app(self):
        """退出：先播告别动画，播完才真正退出。"""
        if self.state == "bye":
            return
        self.save()
        self._hide_pomo_clock()
        if self.src.get("bye") is None:          # 没素材就直接退
            self._close_aux_windows()
            QApplication.quit()
            return
        self.state = "bye"
        self.state_left = 1.8
        self.dy = 0.0
        self.rot = 0.0
        self.popup = None
        self.say("那…我先走啦，下次见喵！", 1.8)

    def toggle_visible(self):
        if self.isVisible():
            self.hide()
            if self.tbmon is not None:
                self.tbmon.hide()
        else:
            self.show()
            if self.show_taskbar and self.tbmon is not None:
                self.tbmon.show()


from PySide6.QtCore import QPointF as QPointF_c  # noqa: E402  (绘制粒子用)


def main():
    _materialize_resources()
    app = QApplication(sys.argv)
    app.setApplicationName("QiCongPet")
    app.setQuitOnLastWindowClosed(False)
    lock = QLockFile(os.path.join(
        QStandardPaths.writableLocation(QStandardPaths.TempLocation), "qicong_pet.lock"))
    if not lock.tryLock(200):
        QMessageBox.information(None, NAME, NAME + "已经在桌面上啦~")
        return 0
    pet = Pet()
    pet.show()
    try:
        if QSystemTrayIcon.isSystemTrayAvailable():
            tray = QSystemTrayIcon()
            tray_pm = pm_or_none("tray.png")
            if tray_pm is not None:                 # 用自定义托盘图标
                tray.setIcon(QIcon(tray_pm))
            elif pet.src["chibi"] is not None:
                tray.setIcon(QIcon(pet.src["chibi"].scaledToHeight(
                    64, Qt.SmoothTransformation)))
            tmenu = QMenu()
            tmenu.addAction("显示 / 隐藏", pet.toggle_visible)
            tmenu.addAction("喂点团子 🍡", lambda: pet.feed("团子 🍡"))
            tmenu.addAction("玩耍 🎾", pet.play)
            tmenu.addSeparator()
            tmenu.addAction("退出", pet.quit_app)
            tray.setContextMenu(tmenu)
            tray.setToolTip(NAME + " — 桌面宠物")
            tray.activated.connect(
                lambda r: pet.toggle_visible()
                if r == QSystemTrayIcon.DoubleClick else None)
            tray.show()
            pet.tray = tray          # 注入，便于菜单里刷新图标
    except Exception:
        pass

    if "--smoke" in sys.argv:
        # 确定性冒烟测试：动作后手动驱动 tick，不依赖定时器节奏
        def pump(n):
            for _ in range(n):
                pet.tick()

        def s1():
            pet.feed("团子 🍡")
            pump(100)
            print("[SMOKE] feed -> state=%s exp=%s hunger=%.0f" %
                  (pet.state, pet.exp, pet.hunger), flush=True)

        def s2():
            pet.play()
            pump(100)
            print("[SMOKE] play -> state=%s exp=%s mood=%.0f" %
                  (pet.state, pet.exp, pet.mood), flush=True)

        def s3():
            x0 = pet.x()
            pet.start_walk()
            pump(60)
            print("[SMOKE] walk -> state=%s moved=%s" %
                  (pet.state, pet.x() != x0), flush=True)

        def s4():
            pet.sleep_now()
            pump(40)
            print("[SMOKE] sleep -> state=%s particles=%d" %
                  (pet.state, len(pet.particles) > 0), flush=True)

        def fin():
            pet.save()
            print("[SMOKE] stats hunger=%s mood=%s exp=%s level=%s" %
                  (pet.hunger, pet.mood, pet.exp, pet.level), flush=True)
            print("SMOKE OK", flush=True)
            app.quit()

        QTimer.singleShot(200, s1)
        QTimer.singleShot(600, s2)
        QTimer.singleShot(1000, s3)
        QTimer.singleShot(1400, s4)
        QTimer.singleShot(1800, fin)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
