"""承認済みの下書きを Threads に投稿する（文章のみ）。

本文（つかみ）を出したあと、「コメント」列の中身を自分の返信として順に付ける。
検索・行動の投稿は、最後のコメントに紹介文とリンクを付ける。

    python beauty/src/post.py                     # 見回り：予定時刻を過ぎた承認済みの投稿を1件だけ投稿する
    python beauty/src/post.py --slot 朝           # 今日の朝の枠を今すぐ投稿する
    python beauty/src/post.py --slot 夜 --date 2026-11-02 --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time

from common import (COLUMNS, JST, POSTS_SHEET, SLOTS, build_comment, col, col_letter, now_jst,
                    open_sheet, read_settings, split_replies, with_disclosure)
from threads import post_text

MAX_CHARS = 500
# 予定時刻からこれ以上遅れたら、深夜などの不自然な時間に出ないよう自動では投稿しない
GRACE = dt.timedelta(hours=3)
# もう投稿しない状態（見回りの対象から外す）
DONE_STATES = {"投稿済み", "投稿済み（コメント途中）", "未承認のため見送り", "見送り（時間切れ）"}
# コメントを1つ付けるごとの待ち時間（Meta の推奨は約30秒）
REPLY_WAIT = 30


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
    width = max(len(values[0]), len(COLUMNS))
    rows = [(i + 1, r + [""] * (width - len(r))) for i, r in enumerate(values) if i > 0 and r and r[0]]

    def update(row_no: int, **fields: str) -> None:
        if args.dry_run:
            return
        ws.batch_update([{"range": f"{col_letter(k)}{row_no}", "values": [[v]]} for k, v in fields.items()],
                        value_input_option="RAW")

    def publish(row_no: int, r: list[str]) -> bool:
        pid = r[col("ID")]
        text = with_disclosure(r[col("本文")], r[col("種類")], settings.get("必須表記", ""))
        offer = r[col("紹介先")].strip()
        try:
            replies = split_replies(r[col("コメント")])
            # 紹介先があるのにリンクが未設定なら、本文も出さない（「次のコメントに」が空振りするため）
            if offer:
                replies.append(build_comment(r[col("紹介文")], offer, settings))
            for label, t in [("本文", text), *((f"コメント{i}", c) for i, c in enumerate(replies, 1))]:
                if len(t) > MAX_CHARS:
                    raise ValueError(f"{label}が{len(t)}字です（上限{MAX_CHARS}字）")
            if args.dry_run:
                print(f"--- {pid} ---\n{text}")
                for i, c in enumerate(replies, 1):
                    print(f"[コメント{i}]\n{c}")
                return True
        except Exception as e:
            print(f"{pid}: 失敗 {e}", file=sys.stderr)
            update(row_no, 状態="エラー", エラー=str(e)[:300])
            return False

        user_id, token = settings["user_id"], settings["access_token"]
        media_id = r[col("投稿ID")]
        # 途中で失敗したときは、付け終わったコメントの続きから付け直す
        reply_ids = [x for x in r[col("コメントID")].splitlines() if x]
        reply_urls = [x for x in r[col("コメントURL")].splitlines() if x]
        try:
            if not media_id:
                media_id, permalink = post_text(user_id, token, text)
                update(row_no, 投稿ID=media_id, 投稿URL=permalink,
                       投稿日時=now_jst().strftime("%Y-%m-%d %H:%M"),
                       状態="投稿済み" if not replies else "コメント中", エラー="")
                print(f"{pid}: 投稿しました {permalink}")
            for c in replies[len(reply_ids):]:
                time.sleep(REPLY_WAIT)
                # 直前のコメントへの返信にして、1本のスレッドとしてつなげる
                cid, curl = post_text(user_id, token, c, reply_to_id=reply_ids[-1] if reply_ids else media_id)
                reply_ids.append(cid)
                reply_urls.append(curl)
                done = len(reply_ids) == len(replies)
                update(row_no, コメントID="\n".join(reply_ids), コメントURL="\n".join(reply_urls),
                       状態="投稿済み" if done else "コメント中", エラー="")
                print(f"{pid}: コメント{len(reply_ids)}/{len(replies)}を付けました {curl}")
            return True
        except Exception as e:  # 失敗はシートに残す（見回りなら猶予時間内は次回また試す）
            print(f"{pid}: 失敗 {e}", file=sys.stderr)
            update(row_no, 状態="コメント失敗" if media_id else "エラー", エラー=str(e)[:300])
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
            if r[col("状態")] in ("投稿済み", "投稿済み（コメント途中）"):
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
            if r[col("投稿ID")]:  # 本文は出ていてコメントを付けきれなかった
                state = "投稿済み（コメント途中）"
            else:
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
