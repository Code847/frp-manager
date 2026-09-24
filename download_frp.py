#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""frp 二进制下载脚本

仓库为保持轻量不收录 bin/ 下的可执行文件（约 143MB），
克隆后运行本脚本即可自动下载当前平台对应的 frpc / frps。

用法:
    python download_frp.py                 # 下载最新稳定版
    python download_frp.py 0.67.0          # 下载指定版本
    python download_frp.py --mirror ghfast # 指定镜像（国内网络优选）
    python download_frp.py --list          # 只列出可用版本，不下载

说明: 面板启动后也可在「系统设置 → FRP 版本控制」中图形化下载与切换版本。
"""

import os
import sys
import stat
import json
import tarfile
import zipfile
import platform
import argparse
import urllib.request

GITHUB_API = 'https://api.github.com/repos/fatedier/frp/releases/latest'
GITHUB_URL = 'https://github.com/fatedier/frp/releases/download/v{ver}/{name}'
MIRRORS = {
    'official': GITHUB_URL,
    'ghfast': 'https://ghfast.top/' + GITHUB_URL,
    'ghproxy_com': 'https://gh-proxy.com/' + GITHUB_URL,
    'ghproxy_net': 'https://ghproxy.net/' + GITHUB_URL,
    'mirror_ghproxy': 'https://mirror.ghproxy.com/' + GITHUB_URL,
}

ARCH_ALIASES = {
    'x86_64': 'amd64', 'amd64': 'amd64', 'x64': 'amd64', 'em64t': 'amd64',
    'aarch64': 'arm64', 'arm64': 'arm64', 'armv8l': 'arm64', 'armv8': 'arm64',
    'armv7l': 'arm', 'armv7': 'arm', 'armv6l': 'arm', 'armv6': 'arm', 'arm': 'arm',
    'i386': '386', 'i686': '386', 'x86': '386',
}

DEFAULT_VERSION = '0.67.0'


def detect_platform():
    """返回 (system, arch)，与 frp 官方发布包命名一致。"""
    sysname = platform.system().lower()
    system = {'windows': 'windows', 'linux': 'linux', 'darwin': 'darwin'}.get(
        sysname, sysname)
    arch = ARCH_ALIASES.get((platform.machine() or '').lower(),
                            (platform.machine() or 'amd64').lower())
    return system, arch


def http_json(url, timeout=15):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'frp-manager-downloader',
        'Accept': 'application/vnd.github+json',
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def latest_version():
    try:
        data = http_json(GITHUB_API)
        return str(data.get('tag_name', '')).lstrip('v') or DEFAULT_VERSION
    except Exception as exc:
        print(f"[WARN] 获取最新版本失败({exc})，回退到 {DEFAULT_VERSION}")
        return DEFAULT_VERSION


def download(url, path, reporthook):
    tmp = path + '.part'
    urllib.request.urlretrieve(url, tmp, reporthook=reporthook)
    os.replace(tmp, path)


def do_download(version, mirror_key, bin_dir):
    system, arch = detect_platform()
    platform_tag = f"{system}_{arch}"
    ext = 'zip' if system == 'windows' else 'tar.gz'
    archive_name = f"frp_{version}_{platform_tag}.{ext}"

    tpl = MIRRORS.get(mirror_key) or MIRRORS['official']
    order = [tpl] + [v for k, v in MIRRORS.items() if k != mirror_key] \
        if mirror_key != 'official' else list(MIRRORS.values())

    os.makedirs(bin_dir, exist_ok=True)
    temp_dir = os.path.join(bin_dir, '..', 'temp')
    os.makedirs(temp_dir, exist_ok=True)
    archive_path = os.path.join(temp_dir, archive_name)

    print(f"[INFO] 目标平台: {platform_tag}    版本: v{version}")
    ok = False
    for t in order:
        url = t.format(ver=version, name=archive_name) if '{' in t \
            else f"{t.rstrip('/')}/{archive_name}"
        print(f"[INFO] 尝试下载: {url}")

        def hook(count, size, total):
            if total > 0 and count % 20 == 0:
                pct = min(100, int(count * size * 100 / total))
                print(f"\r[INFO] 进度 {pct}%", end='', flush=True)

        try:
            download(url, archive_path, hook)
            print("\r[INFO] 下载完成            ")
            ok = True
            break
        except Exception as exc:
            print(f"\n[WARN] 该源失败: {exc}")
    if not ok:
        print("[ERROR] 所有下载源均失败。可手动下载后放入 bin/ 目录：")
        print(f"        {MIRRORS['official'].format(ver=version, name=archive_name)}")
        return 1

    print("[INFO] 解压中...")
    if ext == 'zip':
        with zipfile.ZipFile(archive_path, 'r') as z:
            z.extractall(temp_dir)
    else:
        with tarfile.open(archive_path, 'r:gz') as t:
            try:
                t.extractall(temp_dir, filter='data')
            except TypeError:
                t.extractall(temp_dir)

    extract_dir = os.path.join(temp_dir, f"frp_{version}_{platform_tag}")
    if not os.path.isdir(extract_dir):
        print(f"[ERROR] 解压目录异常: {extract_dir}")
        return 1

    bin_ext = '.exe' if system == 'windows' else ''
    copied = []
    for src_name, dst in (('frpc', f'frpc_{platform_tag}{bin_ext}'),
                          ('frps', f'frps_{platform_tag}{bin_ext}')):
        src = os.path.join(extract_dir, src_name + bin_ext)
        if not os.path.exists(src):
            print(f"[WARN] 包内缺少 {src_name}{bin_ext}，跳过")
            continue
        target = os.path.join(bin_dir, dst)
        with open(src, 'rb') as f1, open(target, 'wb') as f2:
            f2.write(f1.read())
        if system != 'windows':
            os.chmod(target, os.stat(target).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        copied.append(dst)
        print(f"[OK] {dst}  ({os.path.getsize(target) / 1024 / 1024:.1f} MB)")

    try:
        os.remove(archive_path)
    except OSError:
        pass

    if copied:
        print(f"\n[DONE] 已就绪：{', '.join(copied)}  →  {bin_dir}")
        print("       现在可以运行 start.bat / python main.py 启动面板")
        return 0
    print("[ERROR] 未提取到任何可执行文件")
    return 1


def main():
    ap = argparse.ArgumentParser(description='下载 frp 二进制到 bin/ 目录')
    ap.add_argument('version', nargs='?', default=None, help='版本号，如 0.67.0')
    ap.add_argument('--mirror', default='official', choices=list(MIRRORS.keys()),
                    help='下载源，国内网络建议 ghfast / ghproxy_net')
    ap.add_argument('--bin-dir', default=None, help='输出目录，默认脚本同级 bin/')
    ap.add_argument('--list', action='store_true', help='只列出版本不下载')
    args = ap.parse_args()

    version = args.version
    if not version:
        version = latest_version()
    if args.list:
        print(f"最新版本: v{version}")
        print(f"下载地址: {MIRRORS[args.mirror].format(ver=version, name='')}")
        return 0

    bin_dir = args.bin_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bin')
    return do_download(version, args.mirror, bin_dir)


if __name__ == '__main__':
    sys.exit(main())
