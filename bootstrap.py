# -*- coding: utf-8 -*-
"""
柒葱桌宠 · 一键启动引导器
========================
作用：把整个 qicong-pet 文件夹复制到任何一台 Windows 电脑后，
      双击「一键启动.bat」→ 本脚本自动检查依赖、缺失就自动装，然后唤出桌宠。

依赖策略：
  - 必需：PySide6（没有它桌宠起不来）
  - 可选：numpy / soundcard（音乐模式用；装不上也不影响桌宠正常跑）
安装方式：优先用项目自带的离线 wheel（tools/wheels），装不上再联网 pip（清华镜像）。
"""
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WHEELS = ROOT / "tools" / "wheels"
MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"


def has(mod):
    """模块是否已安装（只探测不导入，快）。"""
    import importlib.util
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def pip_install(pkgs, offline=False):
    """调 pip 装包；offline=True 时用项目自带 wheels。"""
    cmd = [sys.executable, "-m", "pip", "install"]
    if offline:
        cmd += ["--no-index", "--find-links", str(WHEELS)]
    else:
        cmd += ["-i", MIRROR, "--trusted-host", "pypi.tuna.tsinghua.edu.cn"]
    cmd += list(pkgs)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        return r.returncode == 0
    except Exception:
        return False


def ensure(pkg, mod, required=False, note=""):
    """确保某个包可用；返回 True/False。"""
    if has(mod):
        print("  [OK]  %s 已就绪" % pkg)
        return True
    print("  [..]  正在安装 %s ...（首次约需 1-3 分钟）" % pkg)
    # 先试离线 wheel（没网也能装），再试联网
    if WHEELS.is_dir() and pip_install([pkg], offline=True):
        print("  [OK]  %s（离线安装成功）" % pkg)
        return True
    if pip_install([pkg]):
        print("  [OK]  %s（联网安装成功）" % pkg)
        return True
    if required:
        print("  [!!]  %s 安装失败（必需）" % pkg)
    else:
        tip = "（%s）" % note if note else "（不影响桌宠启动）"
        print("  [--]  %s 装不上，跳过 %s" % (pkg, tip))
    return False


def launch():
    """用无控制台的 pythonw 启动桌宠（桌面不弹黑窗）。"""
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    launcher = str(pyw) if pyw.exists() else str(exe)
    subprocess.Popen([launcher, str(ROOT / "pet.py")], cwd=str(ROOT))
    return launcher


def main():
    print("=" * 50)
    print("   柒葱桌宠 · 一键启动")
    print("=" * 50)
    print("Python: %s\n" % sys.executable)
    print("检查依赖：")

    if not ensure("PySide6", "PySide6", required=True):
        print("\n[失败] PySide6 装不上，桌宠无法启动。")
        print("       请检查网络，或手动执行：")
        print("       %s -m pip install PySide6" % sys.executable)
        if not hasattr(sys, "frozen"):
            input("\n按回车退出...")
        return 1

    print("\n可选组件（音乐模式）：")
    ensure("numpy", "numpy")
    ensure("soundcard", "soundcard")

    print("\n推荐组件（系统监控网速）：")
    ensure("psutil", "psutil", note="装不上时桌宠正常跑，仅网速显示「不可用」")

    if "--check" in sys.argv:        # 只检查不启动（调试用）
        print("\n[检查完成] 依赖齐全，未启动桌宠（--check 模式）。")
        return 0

    print("\n[启动] 正在唤出桌宠 ...")
    launch()
    print("[完成] 桌宠已启动！它会出现在屏幕底部（任务栏上方）。")
    print("       右键它可打开菜单（喂食/音乐模式/设置/退出）。")
    # 成功启动 → 短暂停留展示结果后自动关闭，不等按键
    print("\n（本窗口 2 秒后自动关闭）")
    time.sleep(2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
