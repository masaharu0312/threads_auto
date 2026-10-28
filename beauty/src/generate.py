"""翌週分（1日3投稿×7日）の下書きを Claude で作り、シートに追加する（文章のみ）。

    python beauty/src/generate.py                  # 次の月曜から7日分
    python beauty/src/generate.py --start 2026-11-02 --days 3
    python beauty/src/generate.py --from-json beauty/drafts/2026-11-02_week.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

import anthropic

from common import (COLUMNS, KINDS, LINK_KINDS, OFFERS, POSTS_SHEET, ROOT, SLOTS, col, format_post_rows,
                    next_post_row, now_jst, open_sheet, read_knowledge, read_settings, slot_kind,
                    with_disclosure, write_setting)
from threads import ThreadsError, refresh_token

MODEL = "claude-opus-5-5"
WEEKDAYS = "月火水木金土日"

# 種類ごとに回すテーマのヒント（同じ話題が続かないようにする）
THEME_HINTS = {
    "認知": ["ブラックなサロンの求人票の特徴", "美容の仕事で辞めたくなる悩み", "長く働ける職場の条件",
             "面接で気をつけたい言葉", "職種を問わないブラックな職場の共通点", "美容業界はどこもブラックなのか",
             "業界ごと辞めてしまうもったいなさ", "練習・講習と勤務時間", "指名と給料の関係"],
    "興味関心": ["面接で聞くべき質問", "求人票の固定残業代の読み方", "在職中に比べる材料を集める",
               "未経験は研修の中身を見る", "ブランクのあるママの働き方", "評価の仕組みがある職場",
               "辞めるのは逃げではない", "辞めるタイミングの考え方", "休みの取りやすさの確かめ方"],
    "検索": ["求人サイトと転職エージェントの違い", "美容特化の転職サービスがしてくれること",
             "目的別のサービスの使い分け", "エージェントに聞いてもらえること"],
    "行動": ["登録の流れ", "登録すると職場にバレるか", "登録してもすぐ転職しなくていい",
             "登録後に来る連絡の内容", "希望条件が固まっていなくても相談できる"],
}

POST_SCHEMA = {
    "type": "object",
    "properties": {
        "posts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "slot": {"type": "string", "enum": list(SLOTS)},
                    "theme": {"type": "string"},
                    "text": {"type": "string"},
                    "offer": {"type": "string", "enum": [*OFFERS, "なし"]},
                    "comment": {"type": "string"},
                },
                "required": ["slot", "theme", "text", "offer", "comment"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["posts"],
    "additionalProperties": False,
}

FORMAT_RULES = f"""\
# 出力ルール
- 1日3投稿。slot は「朝」「昼」「夜」を1つずつ。種類はプロンプトで枠ごとに指定する。
- text：Threadsの本文。300字以内、文章のみ。1行目で手を止めさせる（「〇〇な人の特徴3つ」「雇う側だから言える〜」など）。
  短い段落と改行で読みやすく。絵文字は0〜1個。ハッシュタグ・URLは書かない。広告表記はプログラムが付けるので書かない。
- 種類ごとの書き方
  - 認知：美容の仕事に就いている人が「あるある」と手を止める話。リンクも紹介もしない。offer は「なし」、comment は空文字。
  - 興味関心：「職場を変えれば変わるかも」と思わせる具体的なコツ。リンクも紹介もしない。offer は「なし」、comment は空文字。
  - 検索：紹介する転職サービスを調べたくさせる（何をしてくれるか・違い・使い分け）。本文の最後に「（使っているサービスはコメント欄に）」のように一言添える。
  - 行動：登録前の「面倒」「不安」を先回りして消す（流れ・バレないか・すぐ転職しなくていい）。本文の最後に同じくコメント欄へ一言誘導する。
- offer（検索・行動のみ）：本文を読んだ人が次に欲しいものに合う紹介先を選ぶ。経験者（今の職場を変えたい経験者）／未経験（未経験・ブランク）／条件（給与・休日などで探したい人）。
- comment（検索・行動のみ）：コメント欄に貼る紹介文。PASONA（問題→共感→解決策→提案→後押し）で4〜5文、200字以内。
  サービス名は必ず「○○」と書く（プログラムが置き換える）。広告表記・URLは書かない（プログラムが付ける）。
"""


def build_system(settings: dict[str, str]) -> str:
    profile = "\n".join(f"- {k}：{settings.get(k) or '（未設定）'}" for k in ["立場", "禁止表現", "追加の指示"])
    return (
        "あなたは、美容サロンを経営している人として、Threadsの「ブラックじゃない美容のお仕事案内」アカウントに投稿を書きます。"
        "美容の仕事で悩む人に、ブラックな職場の見分け方と、長く働ける職場の探し方を正直に伝えることが目的です。\n"
        "以下のナレッジの投稿ルールを必ず守ってください。\n\n"
        f"{read_knowledge()}\n\n# アカウント設定\n{profile}\n\n{FORMAT_RULES}\n{read_voice_examples()}"
    )


def read_voice_examples() -> str:
    path = ROOT / "voice_examples.json"
    if not path.exists():
        return ""
    examples = "\n\n".join(f"【{p['kind']}】\n{p['text']}" for p in json.loads(path.read_text(encoding="utf-8")))
    return ("\n# 語り口の見本\n語り口・温度感はこの見本に合わせる。ただし同じ文章やテーマの焼き直しはしない。\n\n"
            f"{examples}\n")


def generate_day(client: anthropic.Anthropic, system: str, day: dt.date, recent: list[str]) -> list[dict]:
    lines = []
    for slot in SLOTS:
        kind = slot_kind(day, slot)
        hints = THEME_HINTS[kind]
        lines.append(f"- {slot}：種類「{kind}」、テーマのヒント「{hints[day.toordinal() % len(hints)]}」")
    recent_text = "\n".join(f"- {r}" for r in recent[-30:]) or "（なし）"
    prompt = (
        f"{day.isoformat()}（{WEEKDAYS[day.weekday()]}）の3投稿を作ってください。\n"
        + "\n".join(lines)
        + f"\n\n最近の投稿（テーマや書き出しが重ならないようにする）：\n{recent_text}"
    )
    for _ in range(2):
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            output_config={"format": {"type": "json_schema", "schema": POST_SCHEMA}},
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason == "refusal":
            raise RuntimeError(f"{day}: 生成が拒否されました")
        text = "".join(b.text for b in response.content if b.type == "text")
        posts = json.loads(text)["posts"]
        if sorted(p["slot"] for p in posts) == sorted(SLOTS):
            for p in posts:
                p["kind"] = slot_kind(day, p["slot"])
            return sorted(posts, key=lambda p: list(SLOTS).index(p["slot"]))
    raise RuntimeError(f"{day}: 3枠そろった投稿を生成できませんでした")


def next_monday(today: dt.date) -> dt.date:
    return today + dt.timedelta(days=(7 - today.weekday()) % 7 or 7)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", help="開始日 YYYY-MM-DD（省略時は次の月曜）")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--from-json", help="Claude を呼ばず、このJSONの投稿をそのままシートに入れる")
    args = parser.parse_args()

    start = dt.date.fromisoformat(args.start) if args.start else next_monday(now_jst().date())
    sh = open_sheet()
    settings = read_settings(sh)
    ws = sh.worksheet(POSTS_SHEET)
    values = ws.get_all_values()[1:]
    existing = {r[col("ID")] for r in values if r}
    recent = [f"{r[col('テーマ')]}：{r[col('本文')][:40]}" for r in values if len(r) > col("本文")]

    prepared: dict[str, list[dict]] = {}
    if args.from_json:
        for p in json.loads(open(args.from_json, encoding="utf-8").read()):
            prepared.setdefault(p["date"], []).append(p)
        start = min(dt.date.fromisoformat(d) for d in prepared)
        args.days = (max(dt.date.fromisoformat(d) for d in prepared) - start).days + 1
    else:
        client = anthropic.Anthropic()
        system = build_system(settings)
    disclosure = settings.get("必須表記", "")

    rows = []
    for i in range(args.days):
        day = start + dt.timedelta(days=i)
        if all(f"{day.isoformat()}-{s}" in existing for s in SLOTS):
            print(f"{day}: 作成済みのためスキップ")
            continue
        day_posts = prepared.get(day.isoformat(), []) if args.from_json else generate_day(client, system, day, recent)
        for p in day_posts:
            post_id = f"{day.isoformat()}-{p['slot']}"
            if post_id in existing:
                continue
            kind = p.get("kind") or slot_kind(day, p["slot"])
            assert kind in KINDS, f"{post_id}: 種類「{kind}」が不明です"
            offer = p.get("offer", "なし")
            linked = kind in LINK_KINDS and offer in OFFERS
            row = [""] * len(COLUMNS)
            row[col("ID")] = post_id
            row[col("日付")] = day.isoformat()
            row[col("枠")] = p["slot"]
            row[col("種類")] = kind
            row[col("テーマ")] = p["theme"]
            row[col("本文")] = with_disclosure(p["text"], kind, disclosure)
            row[col("紹介先")] = offer if linked else ""
            row[col("コメント")] = p.get("comment", "") if linked else ""
            row[col("承認")] = "FALSE"
            row[col("状態")] = "下書き"
            rows.append(row)
            recent.append(f"{p['theme']}：{p['text'][:40]}")
        print(f"{day}: {len(day_posts)}投稿を追加")

    if rows:
        start_row = next_post_row(ws)
        end_row = start_row + len(rows) - 1
        if end_row > ws.row_count:
            ws.add_rows(end_row - ws.row_count)
        ws.update(values=rows, range_name=f"A{start_row}", value_input_option="USER_ENTERED")
        format_post_rows(sh, ws, start_row, end_row)
    print(f"{len(rows)}件をシートに追加しました")

    # 長期トークンは60日で切れるので、毎週更新しておく
    token = settings.get("access_token")
    if token:
        try:
            new_token = refresh_token(token)
            write_setting(sh, "access_token", new_token)
            write_setting(sh, "token_updated", now_jst().strftime("%Y-%m-%d %H:%M"))
            print("Threadsトークンを更新しました")
        except ThreadsError as e:
            print(f"トークン更新に失敗: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
