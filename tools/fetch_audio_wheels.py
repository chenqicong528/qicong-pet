# -*- coding: utf-8 -*-
"""下载 soundcard（系统音频回环采集，纯 Python + CFFI）及其依赖 cffi/pycparser 的离线 wheel。"""
import re
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

OUT = Path(__file__).resolve().parent / "wheels"
OUT.mkdir(exist_ok=True)
INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple/{pkg}/"

# soundcard 依赖链：soundcard -> cffi -> pycparser（都是纯 Python/abi3 wheel）
PKGS = ["soundcard", "cffi", "pycparser"]


def list_wheels(pkg):
    req = urllib.request.Request(INDEX.format(pkg=pkg), headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    out = []
    for m in re.finditer(r'<a href="([^"]+)"[^>]*>([^<]+)</a>', html):
        url, name = urljoin(INDEX.format(pkg=pkg), m.group(1)), m.group(2).strip()
        if not name.endswith(".whl"):
            continue
        # win_amd64 或通用（py3-none-any）
        if "win_amd64" in name or "py3-none-any" in name or "py2.py3-none-any" in name:
            out.append((name, url))
    return out


def ver_tuple(name):
    m = re.search(r"-([0-9]+(?:\.[0-9]+)*)-", name)
    return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)


def pick(pkg):
    wheels = list_wheels(pkg)
    if not wheels:
        raise RuntimeError(f"{pkg}: 没有找到可用 wheel")
    import sys
    tag = "cp%d%d" % (sys.version_info.major, sys.version_info.minor)
    # 匹配当前解释器版本（cp313 等）
    exact = [w for w in wheels if tag in w[0]]
    # 其次 abi3（向后兼容）
    abi3 = [w for w in wheels if "abi3" in w[0]]
    # 最后纯 py（any）
    anyw = [w for w in wheels if "none-any" in w[0]]
    pool = exact or abi3 or anyw or wheels
    name, url = max(pool, key=lambda x: ver_tuple(x[0]))
    return name, url


def download(name, url):
    dest = OUT / name
    if dest.exists() and dest.stat().st_size > 0:
        print("已存在:", name)
        return dest
    with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as f:
        got = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
    print("  完成 %s %.2fMB" % (name, got / 1e6), flush=True)
    return dest


def main():
    for pkg in PKGS:
        name, url = pick(pkg)
        print("选择:", name)
        download(name, url)
    print("DONE")


if __name__ == "__main__":
    sys.exit(main())
