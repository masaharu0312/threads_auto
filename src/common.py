"""スプレッドシート・設定・日時まわりの共通処理。"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import gspread

ROOT = Path(__file__).resolve().parent.parent
JST = dt.timezone(dt.timedelta(hours=9))

POSTS_SHEET = "投稿"
SETTINGS_SHEET = "設定"

# 枠 → 投稿時刻（GitHub Actions の cron と合わせる）
SLOTS = {"朝": "08:00", "昼": "12:30", "夜": "20:30"}
SLOT_TARGETS = {"朝": "働きたい人", "昼": "オーナー候補", "夜": "本音・共感"}

COLUMNS = [
    "ID", "日付", "枠", "ターゲット", "テーマ", "本文",
    "画像タイプ", "画像見出し", "画像本文", "画像注記", "写真ファイル",
    "画像URL", "プレビュー", "承認", "状態", "投稿日時", "投稿URL", "エラー",
]

# 設定シートの初期値（キー, 値, 説明）
SETTINGS_DEFAULTS = [
    ("立場", "どこでもMUSEEに加盟した店舗オーナーで、ミュゼのファン（個人の視点で発信）", "AIに伝えるアカウントの立場。本部公式と誤解されない書き方にする"),
    ("表示名", "", "画像の下に入れる名前（例：どこでもミュゼ〇〇店）"),
    ("必須表記", "#PR", "毎回の本文末尾に自動で付ける表記。紹介報酬を受ける場合は広告であることの明示が必要"),
    ("オーナー向け誘導先", "LINE公式アカウント（プロフィールのリンクから友だち追加）", "FC説明会・資料請求のURL、または「プロフィールのリンクから」など"),
    ("求人の誘導先", "LINE公式アカウント（プロフィールのリンクから友だち追加）", "求人ページのURL、またはLINE公式アカウントなど"),
    ("求人条件", "", "勤務地・雇用形態・給与など。空欄ならAIは条件を書かない"),
    ("追加の指示", "", "口調や避けたい話題など、AIへの追加指示"),
    ("access_token", "", "Threadsの長期アクセストークン（setup_token.py が書き込む）"),
    ("user_id", "", "ThreadsのユーザーID（setup_token.py が書き込む）"),
    ("username", "", "Threadsのユーザー名（setup_token.py が書き込む）"),
    ("token_updated", "", "トークンを最後に更新した日時"),
]


def col(name: str) -> int:
    """列名 → 0始まりの列番号。"""
    return COLUMNS.index(name)


def col_letter(name: str) -> str:
    return chr(ord("A") + col(name))


def now_jst() -> dt.datetime:
    return dt.datetime.now(JST)


def open_sheet() -> gspread.Spreadsheet:
    info = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if info:
        gc = gspread.service_account_from_dict(json.loads(info))
    else:
        path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", str(ROOT / "service_account.json"))
        gc = gspread.service_account(filename=path)
    return gc.open_by_key(os.environ["SHEET_ID"])


def read_settings(sh: gspread.Spreadsheet) -> dict[str, str]:
    rows = sh.worksheet(SETTINGS_SHEET).get_all_values()
    return {r[0].strip(): (r[1].strip() if len(r) > 1 else "") for r in rows[1:] if r and r[0].strip()}


def write_setting(sh: gspread.Spreadsheet, key: str, value: str) -> None:
    ws = sh.worksheet(SETTINGS_SHEET)
    keys = ws.col_values(1)
    if key in keys:
        ws.update_cell(keys.index(key) + 1, 2, value)
    else:
        ws.append_row([key, value, ""], value_input_option="RAW")


def read_knowledge() -> str:
    return (ROOT / "knowledge.md").read_text(encoding="utf-8")


def ensure_disclosure(text: str, disclosure: str) -> str:
    """必須表記が本文に無ければ末尾に付ける。"""
    text = text.rstrip()
    if disclosure and disclosure not in text:
        text = f"{text}\n\n{disclosure}"
    return text
