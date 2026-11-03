"""まだ出していない投稿に、本文（つかみ）に合うイラストを OpenAI の画像生成で作って付ける。

画像は beauty/images/ に置いて push し、Threads から読める公開URLを「画像URL」列に書く。
OPENAI_API_KEY が無いときは何もしない（投稿は文章だけで出る）。

    python beauty/src/illust.py               # 今日以降の、画像がまだ無い投稿すべて
    python beauty/src/illust.py --limit 1     # 1枚だけ（お試し）
    python beauty/src/illust.py --redo 2026-11-03-朝   # この投稿の画像を作り直す
    python beauty/src/illust.py --all                  # 今日以降のまだ出していない投稿を、すべて作り直す
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

from common import POSTS_SHEET, ROOT, col, col_letter, now_jst, open_sheet, split_replies

IMAGES_DIR = ROOT / "images"
MODEL = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-2.5-flare")

STYLE = """\
Cute anime-style chibi illustration (super-deformed: big head, about 2.5 heads tall, large sparkly eyes, rounded simple shapes)
for a Japanese Threads account that helps people working in the beauty industry
(hair salon, esthetic salon, nail salon, eyelash salon) find workplaces that are not exploitative.
Draw one scene that shows the content of the post below at a glance, so that people stop scrolling.
- Style: clean anime line art, soft cel shading, pastel colors (warm beige, off-white, dusty pink, soft mint).
  Cheerful and kawaii, gentle and trustworthy. Even when the topic is a worry, keep it light and cute, not dark.
- Characters: chibi Japanese women working in beauty (vary hairstyle, hair color, uniform and job each time).
  Friendly, not sexualized.
- Absolutely no text, letters, numbers, logos or signs anywhere in the image. Speech bubbles may contain only simple icons.
- Square composition with simple background and some empty space around the subject.
"""

# 同じ構図ばかりにならないよう、投稿ごとに構図を変える（頬杖で考える構図は使わない）
COMPOSITIONS = [
    "two characters talking face to face across a small table, like a job interview or consultation",
    "close-up of the character's hands holding a job listing paper or smartphone, with her surprised face behind it",
    "the character working energetically at a salon station with a customer, full body",
    "several small chibi characters lined up side by side, each showing a different situation, like an infographic without text",
    "the character on her day off, relaxing happily at a cafe or park, with a small salon icon in a thought bubble",
    "before/after split image: left side a tired chibi in a gloomy salon, right side the same chibi smiling in a bright salon",
    "the character walking forward through an open door toward a bright, sparkling salon, seen from a low angle",
    "a senior chibi stylist kindly teaching a beginner chibi, both holding tools",
    "the character standing confidently with one finger raised as if explaining a tip, with simple icon symbols floating around",
]
# 使わない構図（毎回これになりがちなので明示して避ける）
AVOID = "Do not draw a character resting her chin on her hand or thinking with a hand on her cheek."


def build_prompt(pid: str, theme: str, text: str, first_reply: str) -> str:
    composition = COMPOSITIONS[sum(map(ord, pid)) % len(COMPOSITIONS)]
    return (f"{STYLE}- Composition: {composition}. Adapt it naturally to the post content.\n- {AVOID}\n\n"
            f"Post theme: {theme}\nPost hook (Japanese):\n{text}\n\nThe answer in the thread (Japanese):\n{first_reply}\n")


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
    parser.add_argument("--all", action="store_true", help="今日以降のまだ出していない投稿の画像を、すべて作り直す")
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
        upcoming = r[col("日付")] >= today
        if pid in args.redo or (args.all and upcoming) or (not args.redo and not r[col("画像URL")] and upcoming):
            replies = split_replies(r[col("コメント")])
            targets.append((i, pid, build_prompt(pid, r[col("テーマ")], r[col("本文")], replies[0] if replies else "")))
    if args.limit:
        targets = targets[:args.limit]
    if not targets:
        print("画像を作る投稿はありません")
        return 0

    IMAGES_DIR.mkdir(exist_ok=True)
    made, failed = [], 0
    for row_no, pid, prompt in targets:
        try:
            png = generate_png(prompt)
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
