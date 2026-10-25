"""翌週分（1日3投稿×7日）の下書きを Claude で作り、画像付きでシートに追加する。

    python src/generate.py                  # 次の月曜から7日分
    python src/generate.py --start 2026-11-02 --days 3
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

import anthropic

from common import (ROOT, COLUMNS, POSTS_SHEET, SLOT_TARGETS, SLOTS, col, ensure_disclosure,
                    now_jst, open_sheet, read_knowledge, read_settings, write_setting)
from images import ensure_image, image_url, push_images
from threads import ThreadsError, refresh_token

MODEL = "claude-opus-5-5"
WEEKDAYS = "月火水木金土日"

# 日ごとに回すテーマのヒント（同じ話題が続かないようにする）
THEME_HINTS = {
    "朝": ["未経験から始められる研修", "ディプロマ（認定施術者）", "すり減らない働き方（ALL WOMEN SHINE）",
           "TO WORK IS TO GIVE と仲間", "お客様の「キレイになれた」に立ち会う喜び", "日本語タッチパネルの専用機で安心",
           "ノルマや高額契約の勧誘が生じにくい都度払い", "月2回のオンライン座学で学び続けられる"],
    "昼": ["都度払い・前受金なしの仕組み", "1ベッドから既存店舗に導入", "460万人会員へのアプリ告知",
           "研修は本部が設計・運営", "契約から開業まで45日（目安）", "美容業界未経験でも参入できる",
           "オーナーの声", "よくある質問", "新規事業・第2の収益源として", "個人サロンからのステージアップ"],
    "夜": ["歓喜共感", "ALL WOMEN SHINE", "GIVE → GIVE → GIVE", "ミュゼトラック",
           "SHINE（AI×IDOL）", "24年の歩み", "あなたの街にミュゼを", "脱毛の先にある前向きな変化"],
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
                    "image_kind": {"type": "string", "enum": ["message", "number", "qa", "voice"]},
                    "image_headline": {"type": "string"},
                    "image_body": {"type": "string"},
                    "image_note": {"type": "string"},
                },
                "required": ["slot", "theme", "text", "image_kind",
                             "image_headline", "image_body", "image_note"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["posts"],
    "additionalProperties": False,
}

FORMAT_RULES = """\
# 出力ルール
- 1日3投稿。slot は「朝」「昼」「夜」を1つずつ。
  - 朝：ミュゼで働きたい人（未経験者・美容職からの転職者）向け。加盟店オーナー・ミュゼのファンとして「一緒に働く仲間」に語りかける。最後に設定の「求人の誘導先」へ自然に誘導する。
  - 昼：どこでもMUSEEのオーナーになりたい人（サロン経営者・新規事業を考える法人・独立希望者）向け。先に加盟した一人として、良い点と注意点を客観的に伝える。最後に設定の「オーナー向け誘導先」へ誘導する。
  - 夜：ミュゼのファンでもある加盟店オーナーの本音・ひとりごと。ミュゼの考え方や話題への個人的な所感で共感を集める。売り込みはしない。
- text：Threadsの本文。350字以内。1行目で手を止めさせる。短い段落と改行で読みやすく。絵文字は0〜2個。ハッシュタグは書かない（Threadsは1投稿1つまでで、必須表記の #PR などに使うため）。必須表記はプログラムが付けるので書かない。
- image_kind：message（見出し＋説明）／number（大きな数字＋説明）／qa（質問と答え）／voice（オーナーの声の引用）から内容に合うものを選ぶ。3投稿で同じ種類が続きすぎないようにする。
- image_headline：画像の見出し。message は20字以内（改行したい位置に \\n 可）、number は数字と単位だけ（例：460万人）、qa は質問文、voice は引用文。
- image_body：画像の説明文。60字以内。voice の場合は「〇〇店オーナー」。
- image_note：画像下部の注記（No.1表記の出典、「個人の事例です」など）。不要なら空文字。
"""


def build_system(settings: dict[str, str]) -> str:
    profile = "\n".join(f"- {k}：{settings.get(k) or '（未設定）'}" for k in
                        ["立場", "表示名", "オーナー向け誘導先", "求人の誘導先", "求人条件", "追加の指示"])
    return (
        "あなたは、どこでもMUSEEに加盟した店舗オーナーであり、ミュゼのファンでもある本人として、Threadsに投稿を書きます。"
        "加盟した一人の客観的な視点と個人的な所感で、ミュゼで働く仲間と、一緒にやるオーナー仲間を増やすことが目的です。\n"
        "以下のナレッジに書かれた事実と投稿ルールだけを使ってください。\n\n"
        f"{read_knowledge()}\n\n"
        f"# アカウント設定\n{profile}\n\n{FORMAT_RULES}\n{read_voice_examples()}"
    )


def read_voice_examples() -> str:
    """オーナー本人が確認した過去の投稿を、語り口の見本として渡す。"""
    path = ROOT / "voice_examples.json"
    if not path.exists():
        return ""
    examples = "\n\n".join(f"【{p['slot']}】\n{p['text']}" for p in json.loads(path.read_text(encoding="utf-8")))
    return ("\n# 語り口の見本（オーナー本人が「自分の実感と合っている」と確認した投稿）\n"
            "語り口・所感の入れ方・温度感はこの見本に合わせる。ただし同じ文章やテーマの焼き直しはしない。\n\n"
            f"{examples}\n")


def generate_day(client: anthropic.Anthropic, system: str, day: dt.date, recent: list[str]) -> list[dict]:
    hints = "\n".join(
        f"- {slot}（{SLOT_TARGETS[slot]}）：テーマのヒント「{THEME_HINTS[slot][day.toordinal() % len(THEME_HINTS[slot])]}」"
        for slot in SLOTS
    )
    recent_text = "\n".join(f"- {r}" for r in recent[-30:]) or "（なし）"
    prompt = (
        f"{day.isoformat()}（{WEEKDAYS[day.weekday()]}）の3投稿を作ってください。\n"
        f"{hints}\n\n最近の投稿（テーマや書き出しが重ならないようにする）：\n{recent_text}"
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
    display_name = settings.get("表示名", "")
    disclosure = settings.get("必須表記", "")

    rows, paths = [], []
    for i in range(args.days):
        day = start + dt.timedelta(days=i)
        if all(f"{day.isoformat()}-{s}" in existing for s in SLOTS):
            print(f"{day}: 作成済みのためスキップ")
            continue
        if args.from_json:
            day_posts = prepared.get(day.isoformat(), [])
        else:
            day_posts = generate_day(client, system, day, recent)
        for p in day_posts:
            post_id = f"{day.isoformat()}-{p['slot']}"
            if post_id in existing:
                continue
            path = ensure_image(p["slot"], p["image_kind"], p["image_headline"],
                                p["image_body"], p["image_note"], "", display_name)
            paths.append(path)
            url = image_url(path)
            row = [""] * len(COLUMNS)
            row[col("ID")] = post_id
            row[col("日付")] = day.isoformat()
            row[col("枠")] = p["slot"]
            row[col("ターゲット")] = SLOT_TARGETS[p["slot"]]
            row[col("テーマ")] = p["theme"]
            row[col("本文")] = ensure_disclosure(p["text"], disclosure)
            row[col("画像タイプ")] = p["image_kind"]
            row[col("画像見出し")] = p["image_headline"]
            row[col("画像本文")] = p["image_body"]
            row[col("画像注記")] = p["image_note"]
            row[col("画像URL")] = url
            row[col("プレビュー")] = f'=IMAGE("{url}")'
            row[col("承認")] = "FALSE"
            row[col("状態")] = "下書き"
            rows.append(row)
            recent.append(f"{p['theme']}：{p['text'][:40]}")
        print(f"{day}: {len(day_posts)}投稿を追加")

    if rows:
        push_images(paths, f"下書き画像を追加（{start.isoformat()}〜）")
        # append_rows は「承認」列のチェックボックス設定（1000行目まで）を使用中とみなし、
        # 1001行目以降に追記してしまうので、最後のデータ行の次に明示的に書き込む
        start_row = len(ws.get_all_values()) + 1
        end_row = start_row + len(rows) - 1
        if end_row > ws.row_count:
            ws.add_rows(end_row - ws.row_count)
        ws.update(values=rows, range_name=f"A{start_row}", value_input_option="USER_ENTERED")
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
