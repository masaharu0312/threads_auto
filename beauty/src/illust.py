"""まだ出していない投稿に、本文（つかみ）に合うイラストを OpenAI の画像生成で作って付ける。

画像は beauty/images/ に置いて push し、Threads から読める公開URLを「画像URL」列に書く。
OPENAI_API_KEY が無いときは何もしない（投稿は文章だけで出る）。

    python beauty/src/illust.py               # 今日以降の、画像がまだ無い投稿すべて
    python beauty/src/illust.py --limit 1     # 1枚だけ（お試し）
    python beauty/src/illust.py --redo 2026-11-03-朝   # この投稿の画像を作り直す
"""
from __future__ import annotations

import argparse
import base64
import os
import re
import subprocess
import sys
import time

import requests

from common import POSTS_SHEET, ROOT, col, col_letter, now_jst, open_sheet

IMAGES_DIR = ROOT / "images"
MODEL = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1")

STYLE = """\
Soft, warm flat illustration for a Japanese Threads account that helps people working in the beauty industry
(hair salon, esthetic salon, nail salon, eyelash salon) find workplaces that are not exploitative.
Draw one simple scene that visually expresses the mood of the post hook below, so that people stop scrolling.
- Palette: warm beige, off-white, dusty pink, soft mint accents. Gentle, calm, trustworthy. Not dark, not dramatic.
- People: Japanese women in their 20s-30s working in a beauty salon, drawn simply. Friendly, not sexualized.
- Absolutely no text, letters, numbers, logos or signs anywhere in the image.
- Square composition with the main subject in the center and some empty space around it.

Post hook (Japanese):
"""


def generate_png(prompt: str) -> bytes:
    r = requests.post(
        "https://api.openai.com/v1/images/generations",
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        json={"model": MODEL, "prompt": prompt, "size": "1024x1024", "quality": "medium", "n": 1},
        timeout=300,
    )
    if r.status_code != 200:
        try:
            err = r.json().get("error", {})
            detail = f"{err.get('type')} / {err.get('code')} / {err.get('param')}: {err.get('message', '')}"
        except ValueError:
            detail = r.text
        # キーの一部がメッセージに入ることがあるので伏せる
        detail = re.sub(r"sk-[A-Za-z0-9_\-*]+", "sk-…", detail)[:300]
        raise RuntimeError(f"画像生成に失敗 {r.status_code}: {detail}")
    return base64.b64decode(r.json()["data"][0]["b64_json"])


def public_url(name: str) -> str:
    repo = os.environ["GITHUB_REPOSITORY"]
    return f"https://raw.githubusercontent.com/{repo}/main/beauty/images/{name}"


def git(*args: str, check: bool = True) -> int:
    return subprocess.run(["git", *args], cwd=ROOT.parent, check=check).returncode


def push(names: list[str]) -> None:
    git("add", *[str(IMAGES_DIR / n) for n in names])
    if git("diff", "--cached", "--quiet", check=False) == 0:
        return
    git("commit", "-m", f"美容：イラストを追加（{len(names)}枚）")
    for _ in range(3):
        git("pull", "--rebase")
        if git("push", check=False) == 0:
            return
        time.sleep(5)
    raise RuntimeError("画像の push に失敗しました")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="作る枚数の上限（0なら全部）")
    parser.add_argument("--redo", nargs="*", default=[], help="画像を作り直す投稿のID")
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY が未登録のため、画像は作りません")
        return 0

    sh = open_sheet()
    ws = sh.worksheet(POSTS_SHEET)
    values = ws.get_all_values()
    today = now_jst().date().isoformat()
    targets = []
    for i, r in enumerate(values[1:], start=2):
        r = r + [""] * (col("画像URL") + 1 - len(r))
        pid = r[col("ID")]
        if not pid or r[col("投稿ID")]:  # 出したあとの投稿は変えない
            continue
        if pid in args.redo or (not args.redo and not r[col("画像URL")] and r[col("日付")] >= today):
            targets.append((i, pid, r[col("本文")]))
    if args.limit:
        targets = targets[:args.limit]
    if not targets:
        print("画像を作る投稿はありません")
        return 0

    IMAGES_DIR.mkdir(exist_ok=True)
    made, failed = [], 0
    for row_no, pid, text in targets:
        try:
            png = generate_png(STYLE + text)
        except Exception as e:  # 1枚失敗しても他は続ける（画像が無い投稿は文章だけで出る）
            print(f"{pid}: {e}", file=sys.stderr)
            failed += 1
            continue
        # 作り直しのときに古いURLのキャッシュが使われないよう、時刻をファイル名に入れる
        # URLに日本語を入れないよう、枠名は英字にする
        ascii_id = pid.replace("朝", "am").replace("昼", "noon").replace("夜", "pm")
        name = f"{ascii_id}_{now_jst().strftime('%H%M%S')}.png"
        (IMAGES_DIR / name).write_bytes(png)
        made.append((row_no, pid, name))
        print(f"{pid}: 画像を作りました {name}")

    if made:
        push([n for _, _, n in made])
        ws.batch_update([{"range": f"{col_letter('画像URL')}{row_no}", "values": [[public_url(name)]]}
                         for row_no, _, name in made], value_input_option="RAW")
    print(f"{len(made)}枚を作成、{failed}枚が失敗")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
