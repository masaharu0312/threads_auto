"""承認済みの下書きを Threads に投稿する。

    python src/post.py                     # 見回り：予定時刻を過ぎた承認済みの投稿を1件だけ投稿する
    python src/post.py --slot 朝           # 今日の朝の枠を今すぐ投稿する
    python src/post.py --slot 夜 --date 2026-11-02 --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

from common import (JST, POSTS_SHEET, SLOTS, col, col_letter, ensure_disclosure,
                    now_jst, open_sheet, read_settings)
from images import ensure_image, image_url, push_images, wait_until_public
from threads import post_image

MAX_CHARS = 500
# 予定時刻からこれ以上遅れたら、深夜などの不自然な時間に出ないよう自動では投稿しない
GRACE = dt.timedelta(hours=3)
# もう投稿しない状態（見回りの対象から外す）
DONE_STATES = {"投稿済み", "未承認のため見送り", "見送り（時間切れ）"}


def scheduled_at(r: list[str]) -> dt.datetime | None:
    try:
        day = dt.date.fromisoformat(r[col("日付")])
        hh, mm = map(int, SLOTS[r[col("枠")]].split(":"))
    except (ValueError, KeyError):
        return None
    return dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=JST)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", choices=list(SLOTS), help="この枠を今すぐ投稿する（省略時は見回り）")
    parser.add_argument("--date", help="--slot と一緒に使う日付 YYYY-MM-DD（省略時は今日）")
    parser.add_argument("--dry-run", action="store_true", help="投稿せずに内容だけ表示")
    args = parser.parse_args()

    sh = open_sheet()
    settings = read_settings(sh)
    ws = sh.worksheet(POSTS_SHEET)
    values = ws.get_all_values()
    width = len(values[0])
    rows = [(i + 1, r + [""] * (width - len(r))) for i, r in enumerate(values) if i > 0 and r and r[0]]

    def update(row_no: int, **fields: str) -> None:
        if args.dry_run:
            return
        ws.batch_update([{"range": f"{col_letter(k)}{row_no}", "values": [[v]]} for k, v in fields.items()],
                        value_input_option="USER_ENTERED")

    def publish(row_no: int, r: list[str]) -> bool:
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
                return True
            push_images([path], f"投稿画像 {r[col('ID')]}")
            url = image_url(path)
            wait_until_public(url)
            _, permalink = post_image(settings["user_id"], settings["access_token"], text, url)
            update(row_no, 画像URL=url, プレビュー=f'=IMAGE("{url}")', 状態="投稿済み",
                   投稿日時=now_jst().strftime("%Y-%m-%d %H:%M"), 投稿URL=permalink, エラー="")
            print(f"{r[col('ID')]}: 投稿しました {permalink}")
            return True
        except Exception as e:  # 失敗はシートに残す（見回りなら猶予時間内は次回また試す）
            print(f"{r[col('ID')]}: 失敗 {e}", file=sys.stderr)
            update(row_no, 状態="エラー", エラー=str(e)[:300])
            return False

    def approved(r: list[str]) -> bool:
        return r[col("承認")].upper() == "TRUE"

    # 枠を指定したとき：その日のその枠を今すぐ投稿する
    if args.slot:
        date = args.date or now_jst().date().isoformat()
        targets = [(n, r) for n, r in rows if r[col("日付")] == date and r[col("枠")] == args.slot]
        if not targets:
            print(f"{date} {args.slot} の投稿はシートにありません")
            return 0
        ok = True
        for n, r in targets:
            if r[col("状態")] == "投稿済み":
                continue
            if not approved(r):
                print(f"{r[col('ID')]}: 未承認のため見送り")
                update(n, 状態="未承認のため見送り")
                continue
            ok = publish(n, r) and ok
        return 0 if ok else 1

    # 見回り：GitHub の定時実行は飛ばされることがあるので、30分ごとに予定時刻を過ぎた分を拾う
    now = now_jst()
    due = []
    for n, r in rows:
        at = scheduled_at(r)
        if at is None or at > now or r[col("状態")] in DONE_STATES:
            continue
        if now - at > GRACE:
            state = "見送り（時間切れ）" if approved(r) else "未承認のため見送り"
            print(f"{r[col('ID')]}: {state}")
            update(n, 状態=state)
        elif approved(r):
            due.append((at, n, r))
    if not due:
        print("投稿する予定のものはありません")
        return 0
    # 一度にまとめて出さないよう、いちばん古い1件だけ投稿する（残りは次の見回りで）
    _, n, r = min(due, key=lambda x: x[0])
    return 0 if publish(n, r) else 1


if __name__ == "__main__":
    sys.exit(main())
