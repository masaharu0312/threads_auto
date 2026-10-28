"""スプレッドシートに「投稿」「設定」シートを用意する（最初に1回だけ実行）。"""
from __future__ import annotations

from common import (COLUMNS, POSTS_SHEET, SETTINGS_DEFAULTS, SETTINGS_SHEET, col,
                    format_post_rows, next_post_row, open_sheet)


def get_or_add(sh, title: str, cols: int):
    try:
        return sh.worksheet(title)
    except Exception:
        return sh.add_worksheet(title=title, rows=1000, cols=cols)


def main() -> None:
    sh = open_sheet()

    posts = get_or_add(sh, POSTS_SHEET, len(COLUMNS))
    if posts.col_count < len(COLUMNS):
        posts.add_cols(len(COLUMNS) - posts.col_count)
    if posts.row_values(1) != COLUMNS:  # 新しい列が増えたときも見出しを最新にする（列は末尾にしか足さない）
        posts.update(values=[COLUMNS], range_name="A1")
    posts.freeze(rows=1)

    settings = get_or_add(sh, SETTINGS_SHEET, 3)
    existing = settings.col_values(1)
    if not existing:
        settings.update(values=[["項目", "値", "説明"]], range_name="A1")
        existing = ["項目"]
    new_rows = [list(r) for r in SETTINGS_DEFAULTS if r[0] not in existing]
    if new_rows:
        settings.append_rows(new_rows, value_input_option="RAW")

    # 列幅を見やすく。チェックボックスと行の高さはデータのある行にだけ付ける
    def dims(dimension: str, start: int, end: int, size: int) -> dict:
        return {"updateDimensionProperties": {
            "range": {"sheetId": posts.id, "dimension": dimension, "startIndex": start, "endIndex": end},
            "properties": {"pixelSize": size}, "fields": "pixelSize"}}

    sh.batch_update({"requests": [
        dims("COLUMNS", col("本文"), col("本文") + 1, 420),
        dims("COLUMNS", col("プレビュー"), col("プレビュー") + 1, 160),
    ]})
    format_post_rows(sh, posts, 2, next_post_row(posts) - 1)
    print("シートの準備ができました。「設定」シートの値を埋めてください。")


if __name__ == "__main__":
    main()
