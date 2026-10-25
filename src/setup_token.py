"""Threads のアクセストークンを設定シートに登録する（最初に1回だけ実行）。

    # Metaの管理画面で発行したトークンを登録（短期トークンなら THREADS_APP_SECRET を設定すると長期に交換）
    python src/setup_token.py --token <トークン>
"""
from __future__ import annotations

import argparse
import os

from common import now_jst, open_sheet, write_setting
from threads import ThreadsError, exchange_token, get_me


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True)
    args = parser.parse_args()

    token = args.token
    secret = os.environ.get("THREADS_APP_SECRET")
    if secret:
        try:
            token = exchange_token(token, secret)
            print("長期トークンに交換しました")
        except ThreadsError as e:
            print(f"交換できなかったので、そのまま使います（すでに長期トークンの可能性）: {e}")

    me = get_me(token)
    sh = open_sheet()
    write_setting(sh, "access_token", token)
    write_setting(sh, "user_id", me["id"])
    write_setting(sh, "username", me.get("username", ""))
    write_setting(sh, "token_updated", now_jst().strftime("%Y-%m-%d %H:%M"))
    print(f"@{me.get('username')} を登録しました")


if __name__ == "__main__":
    main()
