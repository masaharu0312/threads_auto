"""画像を作って GitHub に置き、Threads から読める公開URLにする。"""
from __future__ import annotations

import hashlib
import os
import subprocess
import time
from pathlib import Path

import requests

from common import ROOT
from render import render

IMAGES_DIR = ROOT / "images"
PHOTOS_DIR = ROOT / "assets" / "photos"


def ensure_image(slot: str, kind: str, headline: str, body: str, note: str,
                 photo_name: str, display_name: str) -> Path:
    """内容のハッシュをファイル名にして、まだ無ければ画像を作る。"""
    key = "|".join([slot, kind, headline, body, note, photo_name, display_name])
    name = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16] + ".png"
    path = IMAGES_DIR / name
    if not path.exists():
        IMAGES_DIR.mkdir(exist_ok=True)
        photo = PHOTOS_DIR / photo_name if photo_name else None
        render(kind, slot, headline, body, note, display_name, photo).save(path, optimize=True)
    return path


def image_url(path: Path) -> str:
    repo = os.environ["GITHUB_REPOSITORY"]  # 例: yourname/threads_auto
    branch = os.environ.get("IMAGE_BRANCH", "main")
    return f"https://raw.githubusercontent.com/{repo}/{branch}/images/{path.name}"


def push_images(paths: list[Path], message: str) -> None:
    """新しい画像をコミットして push する（GitHub Actions 上で実行する想定）。"""
    rel = [str(p.relative_to(ROOT)) for p in paths]
    subprocess.run(["git", "add", *rel], cwd=ROOT, check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0:
        return
    subprocess.run(["git", "commit", "-m", message], cwd=ROOT, check=True)
    for _ in range(3):
        subprocess.run(["git", "pull", "--rebase"], cwd=ROOT, check=True)
        if subprocess.run(["git", "push"], cwd=ROOT).returncode == 0:
            return
        time.sleep(5)
    raise RuntimeError("画像の push に失敗しました")


def wait_until_public(url: str, timeout: int = 180) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if requests.head(url, timeout=20).status_code == 200:
            return
        time.sleep(10)
    raise RuntimeError(f"画像URLが公開されません: {url}")
