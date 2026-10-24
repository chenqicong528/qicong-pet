# -*- coding: utf-8 -*-
"""绕过被 403 的 pip 在线通道，用 urllib 直接从镜像下载 wheel 再离线安装。"""
import re
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

OUT = Path(__file__).resolve().parent / "wheels"
OUT.mkdir(exist_ok=True)
INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple/{pkg}/"

PKGS = ["shiboken6", "PySide6-Essentials", "numpy", "pillow"]


def list_wheels(pkg):
    req = urllib.request.Request(INDEX.format(pkg=pkg), headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    out = []
    for m in re.finditer(r'<a href="([^"]+)"[^>]*>([^<]+)</a>', html):
        url, name = urljoin(INDEX.format(pkg=pkg), m.group(1)), m.group(2).strip()
        if name.endswith(".whl") and "win_amd64" in name:
            out.append((name, url))
    return out


def ver_tuple(name):
    m = re.search(r"-([0-9]+(?:\.[0-9]+)*)-", name)
    return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)


def pick(pkg):
    wheels = list_wheels(pkg)
    if not wheels:
        raise RuntimeError(f"{pkg}: 没有找到 win_amd64 wheel")
    name, url = max(wheels, key=lambda x: ver_tuple(x[0]))
    return name, url


def download(name, url):
    dest = OUT / name
    if dest.exists() and dest.stat().st_size > 0:
        print("已存在:", name)
        return dest
    t0 = time.time()
    with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length", 0))
        got = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if total:
                pct = got * 100 // total
                if pct % 10 == 0:
                    print(f"  {name}: {pct}%", flush=True)
    print(f"  完成 {name} {got/1e6:.1f}MB 用时 {time.time()-t0:.0f}s", flush=True)
    return dest


def main():
    files = []
    for pkg in PKGS:
        name, url = pick(pkg)
        print("选择:", name)
        files.append(download(name, url))
    print("\n全部下载完成:")
    for f in files:
        print(" ", f)


if __name__ == "__main__":
    sys.exit(main())
