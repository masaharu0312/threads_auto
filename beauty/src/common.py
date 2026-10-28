"""美容のお仕事案内アカウント：スプレッドシート・設定・日時まわりの共通処理。

Threads API の処理はリポジトリ直下の src/threads.py を共用する。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

import gspread

ROOT = Path(__file__).resolve().parent.parent  # beauty/
# src/threads.py を読み込めるようにする（この common.py が先に見つかるよう末尾に足す）
sys.path.append(str(ROOT.parent / "src"))

JST = dt.timezone(dt.timedelta(hours=9))

POSTS_SHEET = "投稿"
SETTINGS_SHEET = "設定"

# 枠 → 投稿時刻（.github/workflows/beauty-post.yml の見回りで拾う）
SLOTS = {"朝": "07:30", "昼": "12:30", "夜": "21:00"}

# 教材の4種類。認知・興味関心：7割／検索・行動：3割
KINDS = ["認知", "興味関心", "検索", "行動"]
LINK_KINDS = {"検索", "行動"}  # コメント欄に紹介文とリンクを付ける種類

# 紹介先 → 設定シートのサービス名・リンクのキー
OFFERS = {
    "経験者": ("経験者向け_サービス名", "経験者向け_リンク"),
    "未経験": ("未経験向け_サービス名", "未経験向け_リンク"),
    "条件": ("条件検索向け_サービス名", "条件検索向け_リンク"),
}
PLACEHOLDER = "○○"

COLUMNS = [
    "ID", "日付", "枠", "種類", "テーマ", "本文", "紹介先", "コメント",
    "承認", "状態", "投稿日時", "投稿URL", "コメントURL", "エラー", "投稿ID",
]

# 設定シートの初期値（キー, 値, 説明）
SETTINGS_DEFAULTS = [
    ("立場", "美容サロンを経営している人。雇う側だから分かる、ブラックなサロンの見分け方と長く働ける職場の条件を正直に話す",
     "AIに伝えるアカウントの立場"),
    ("必須表記", "#PR", "検索・行動の投稿の本文末尾と、コメント（紹介文）の先頭に付ける広告表記"),
    ("経験者向け_サービス名", "", "経験者向けに紹介する転職サービス名（コメントの ○○ に入る）"),
    ("経験者向け_リンク", "", "ASPで発行したアフィリエイトリンク"),
    ("未経験向け_サービス名", "", "未経験・ブランク向けに紹介するサービス名"),
    ("未経験向け_リンク", "", "ASPで発行したアフィリエイトリンク"),
    ("条件検索向け_サービス名", "", "給与・休日などの条件で探せるサービス名"),
    ("条件検索向け_リンク", "", "ASPで発行したアフィリエイトリンク"),
    ("禁止表現", "", "案件ごとの禁止キーワード（読点区切り）。AIに避けさせる"),
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


def slot_kind(day: dt.date, slot: str) -> str:
    """その日の枠の種類。朝は認知、昼は興味関心、夜は検索と行動を交互に（日曜の夜だけ認知）。

    1週間で 認知8・興味関心7・検索3・行動3 になり、教材の 7:3 に近くなる。
    """
    if slot == "朝":
        return "認知"
    if slot == "昼":
        return "興味関心"
    if day.weekday() == 6:
        return "認知"
    return "検索" if day.weekday() % 2 == 0 else "行動"


def open_sheet() -> gspread.Spreadsheet:
    info = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if info:
        gc = gspread.service_account_from_dict(json.loads(info))
    else:
        path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", str(ROOT.parent / "service_account.json"))
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


def next_post_row(ws: gspread.Worksheet) -> int:
    """ID列（A列）の最後のデータの次の行番号。チェックボックスだけの行は数えない。"""
    return len(ws.col_values(1)) + 1


def format_post_rows(sh: gspread.Spreadsheet, ws: gspread.Worksheet, first: int, last: int) -> None:
    """投稿行（first〜last 行目）に、承認チェックボックスと本文・コメントの折り返しを付ける。"""
    if last < first:
        return
    rows = {"sheetId": ws.id, "startRowIndex": first - 1, "endRowIndex": last}
    wrap = {"userEnteredFormat": {"wrapStrategy": "WRAP", "verticalAlignment": "TOP"}}
    sh.batch_update({"requests": [
        {"setDataValidation": {
            "range": {**rows, "startColumnIndex": col("承認"), "endColumnIndex": col("承認") + 1},
            "rule": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}}},
        {"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "ROWS", "startIndex": first - 1, "endIndex": last},
            "properties": {"pixelSize": 200}, "fields": "pixelSize"}},
        {"repeatCell": {
            "range": {**rows, "startColumnIndex": col("本文"), "endColumnIndex": col("コメント") + 1},
            "cell": wrap, "fields": "userEnteredFormat(wrapStrategy,verticalAlignment)"}},
    ]})


def read_knowledge() -> str:
    return (ROOT / "knowledge.md").read_text(encoding="utf-8")


def with_disclosure(text: str, kind: str, disclosure: str) -> str:
    """検索・行動の投稿だけ、本文の末尾に広告表記を付ける（認知・興味関心はリンクも紹介もしないので付けない）。"""
    text = text.rstrip()
    if kind in LINK_KINDS and disclosure and disclosure not in text:
        text = f"{text}\n\n{disclosure}"
    return text


def build_comment(template: str, offer: str, settings: dict[str, str]) -> str:
    """コメント（紹介文）の ○○ をサービス名に置き換え、先頭に広告表記・末尾にリンクを付ける。

    サービス名やリンクが未設定なら ValueError（本文だけ出て「コメント欄に」が空振りしないようにする）。
    """
    if offer not in OFFERS:
        raise ValueError(f"紹介先「{offer}」が不明です（{' / '.join(OFFERS)} のどれか）")
    name_key, link_key = OFFERS[offer]
    name, link = settings.get(name_key, ""), settings.get(link_key, "")
    if not name or not link:
        raise ValueError(f"設定シートの「{name_key}」「{link_key}」が未入力です")
    disclosure = settings.get("必須表記", "")
    body = template.strip().replace(PLACEHOLDER, name)
    if disclosure and disclosure not in body:
        body = f"{disclosure}\n{body}"
    return f"{body}\n{link}"
