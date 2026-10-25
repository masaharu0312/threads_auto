"""今日の指定枠の投稿のうち、承認済みのものを Threads に投稿する。

    python src/post.py --slot 朝
    python src/post.py --slot 夜 --date 2026-11-02 --dry-run
"""
from __future__ import annotations

import argparse
import sys

from common import (POSTS_SHEET, SLOTS, col, col_letter, ensure_disclosure,
                    now_jst, open_sheet, read_settings)
from images import ensure_image, image_url, push_images, wait_until_public
from threads import post_image

MAX_CHARS = 500


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", required=True, choices=list(SLOTS))
    parser.add_argument("--date", help="YYYY-MM-DD（省略時は今日）")
    parser.add_argument("--dry-run", action="store_true", help="投稿せずに内容だけ表示")
    args = parser.parse_args()

    date = args.date or now_jst().date().isoformat()
    sh = open_sheet()
    settings = read_settings(sh)
    ws = sh.worksheet(POSTS_SHEET)
    values = ws.get_all_values()

    def update(row_no: int, **fields: str) -> None:
        ws.batch_update([{"range": f"{col_letter(k)}{row_no}", "values": [[v]]} for k, v in fields.items()],
                        value_input_option="USER_ENTERED")

    targets = [(i + 1, r) for i, r in enumerate(values)
               if i > 0 and len(r) > col("状態") and r[col("日付")] == date and r[col("枠")] == args.slot]
    if not targets:
        print(f"{date} {args.slot} の投稿はシートにありません")
        return 0

    failed = False
    for row_no, r in targets:
        r = r + [""] * (len(values[0]) - len(r))
        if r[col("状態")] == "投稿済み":
            continue
        if r[col("承認")].upper() != "TRUE":
            print(f"{r[col('ID')]}: 未承認のため見送り")
            if not args.dry_run:
                update(row_no, 状態="未承認のため見送り")
            continue

        text = ensure_disclosure(r[col("本文")], settings.get("必須表記", ""))
        try:
            if len(text) > MAX_CHARS:
                raise ValueError(f"本文が{len(text)}字です（上限{MAX_CHARS}字）")
            # シートで画像の文言を直していても反映されるよう、投稿直前に作り直す
            path = ensure_image(r[col("枠")], r[col("画像タイプ")] or "message", r[col("画像見出し")],
                                r[col("画像本文")], r[col("画像注記")], r[col("写真ファイル")],
                                settings.get("表示名", ""))
            if args.dry_run:
                print(f"--- {r[col('ID')]} ---\n{text}\n画像: {path}")
                continue
            push_images([path], f"投稿画像 {r[col('ID')]}")
            url = image_url(path)
            wait_until_public(url)
            _, permalink = post_image(settings["user_id"], settings["access_token"], text, url)
            update(row_no, 画像URL=url, プレビュー=f'=IMAGE("{url}")', 状態="投稿済み", 投稿日時=now_jst().strftime("%Y-%m-%d %H:%M"),
                   投稿URL=permalink, エラー="")
            print(f"{r[col('ID')]}: 投稿しました {permalink}")
        except Exception as e:  # 1件の失敗をシートに残して、次へ進む
            failed = True
            print(f"{r[col('ID')]}: 失敗 {e}", file=sys.stderr)
            if not args.dry_run:
                update(row_no, 状態="エラー", エラー=str(e)[:300])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
