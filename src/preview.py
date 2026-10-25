"""シートやAPIを使わずに、画像デザインだけを手元で確認する。

    python3 src/preview.py  →  preview/ に4種類の見本画像ができる
"""
from __future__ import annotations

from pathlib import Path
from render import render

ROOT = Path(__file__).resolve().parent.parent

SAMPLES = [
    ("message", "朝", "未経験から、\n「認定施術者」へ。",
     "直営店舗での実技研修と、最終試験に合格した人だけが受け取れるディプロマ。カリキュラムはすべて本部が設計しています。", ""),
    ("number", "昼", "460万人",
     "ミュゼパスポート会員へ、\n新店舗のオープンをアプリで告知", "※会員数は本部資料（2026年9月）より"),
    ("qa", "昼", "美容業界が未経験でも加盟できますか？",
     "できます。実技研修・月2回のオンライン座学・ディプロマ発行まで本部が設計・運営します。", ""),
    ("voice", "夜", "お客様のキレイと笑顔を一緒に喜べる、家族のように温かいサロンを目指して。",
     "佐賀大和町店オーナー", "※個人の事例です"),
]


def main() -> None:
    out = ROOT / "preview"
    out.mkdir(exist_ok=True)
    for kind, slot, head, body, note in SAMPLES:
        path = out / f"sample_{kind}.png"
        render(kind, slot, head, body, note, "どこでもミュゼ〇〇店").save(path)
        print(path)


if __name__ == "__main__":
    main()
