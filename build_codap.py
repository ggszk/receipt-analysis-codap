"""build_codap.py — 最新CSVから CODAP (v3) ファイルを再生成する.

generate_data.py が出力した receipts / receipt-items / receipt-summary の最新CSVを、
テンプレ CODAP(v3) の各データセットへ流し込んで再生成する。
**表レイアウト・属性の並びと書式・タイル構成などはテンプレを保持**し、
データ（各属性の値・行・ID）だけを差し替える。これで「CSVを更新したら
CODAPファイルが取り残される」問題が起きなくなる（CSVが唯一の正本）。

使い方:
  uv run python build_codap.py                # receipt-analysis.codap を自テンプレに再生成＋ポータルへ同期
  uv run python build_codap.py --no-portal    # repo の codap だけ再生成（ポータルへコピーしない）
  uv run python build_codap.py --template foo.codap --out bar.codap  # 任意のテンプレ/出力

前提・設計メモ（CODAP v3 形式）:
  content.sharedModelMap[*].sharedModel(type=SharedDataSet).dataSet:
    - attributesMap[ATTR] = {id, name, clientKey, values:[...]} … 値は全て文字列。name が CSV ヘッダと一致。
    - _itemIds:[ITEM...]                  … 行ごとのアイテムID
    - collections[0]._groupKeyCaseIds:[[ITEM, CASE], ...]  … item↔case の 1:1 対応（フラット表）
    - snapSelection / setAsideItemIds     … 選択状態（リセットする）
  ITEM/CASE のIDはデータセット内にしか現れない（metadata・タイル・レイアウトは行非依存）ため、
  上記4箇所だけ置き換えればよい。IDは決定論的に振り直す（同じデータなら同じ出力＝差分が出ない）。

  ※ データセットは「1コレクションのフラット表」を前提（receipts/items/summary はいずれもフラット）。
     親子階層を持つテンプレには未対応（assert で検出）。
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent

# データセット名 → 読み込むCSV（repo直下）
CSV_FOR_DATASET = {
    "receipts": "receipts.csv",
    "receipt-items": "receipt-items.csv",
    "receipt-summary": "receipt-summary.csv",
}

# 既定のテンプレ兼出力（repo に置く正本アーティファクト）
DEFAULT_CODAP = REPO / "receipt-analysis.codap"

# ポータル（学生配布）側の同期先。存在すれば自動コピーする。
PORTAL_CODAP = (
    REPO.parent.parent / "courses" / "ggszk-lab-public"
    / "ds_for_high_school" / "data" / "レシート分析.codap"
)


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """ヘッダ（BOM除去）と行（dict）を返す。"""
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        rows = [dict(r) for r in reader]
    return header, rows


def inject(template: Path, csv_dir: Path) -> dict:
    """テンプレCODAPを読み、各データセットへ最新CSVを流し込んだ dict を返す。"""
    doc = json.loads(template.read_text(encoding="utf-8"))
    shared = doc["content"]["sharedModelMap"]

    # データセットごとに決定論的IDの接頭辞を割り当て（出現順）
    ds_index = 0
    for entry in shared.values():
        sm = entry.get("sharedModel", {})
        if sm.get("type") != "SharedDataSet":
            continue
        ds = sm["dataSet"]
        name = ds["name"]
        ds_index += 1
        prefix = str(ds_index)  # ITEM1.../ITEM2... のように一意化

        if name not in CSV_FOR_DATASET:
            raise SystemExit(f"未知のデータセット '{name}'（CSV_FOR_DATASET に追加してください）")
        csv_path = csv_dir / CSV_FOR_DATASET[name]
        header, rows = read_csv(csv_path)
        n = len(rows)

        attrs = ds["attributesMap"]
        attr_names = [a["name"] for a in attrs.values()]

        # 属性名↔CSVヘッダの整合チェック（取り違え・列増減を早期に検出）
        missing = [a for a in attr_names if a not in header]
        extra = [h for h in header if h not in attr_names]
        if missing or extra:
            raise SystemExit(
                f"[{name}] 列が一致しません。CODAPにあってCSVに無い: {missing} / "
                f"CSVにあってCODAPに無い: {extra}"
            )

        # 値の差し替え（全て文字列で格納＝CODAPの保存形式に合わせる）
        for attr in attrs.values():
            col = attr["name"]
            attr["values"] = [str(r.get(col, "")) for r in rows]

        # ID（item / case）を決定論的に振り直す
        item_ids = [f"ITEM{prefix}{i:09d}" for i in range(n)]
        case_ids = [f"CASE{prefix}{i:09d}" for i in range(n)]
        ds["_itemIds"] = item_ids

        colls = ds.get("collections", [])
        if len(colls) != 1:
            raise SystemExit(
                f"[{name}] フラット表（1コレクション）前提ですが {len(colls)} コレクションあります。未対応。"
            )
        colls[0]["_groupKeyCaseIds"] = [[item_ids[i], case_ids[i]] for i in range(n)]

        # 選択状態はリセット
        ds["snapSelection"] = []
        ds["setAsideItemIds"] = []

        print(f"  {name:16s}: {n:5d} 行 / 属性 {len(attr_names)} 列 を流し込み")

    return doc


def write_codap(doc: dict, out: Path) -> None:
    """テンプレと同じ圧縮JSON（1行）で書き出す。"""
    out.write_text(
        json.dumps(doc, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="最新CSVから CODAP(v3) を再生成")
    ap.add_argument("--template", type=Path, default=DEFAULT_CODAP,
                    help="テンプレCODAP（既定: receipt-analysis.codap・出力と同じ）")
    ap.add_argument("--out", type=Path, default=None,
                    help="出力先（既定: テンプレと同じパスに上書き）")
    ap.add_argument("--csv-dir", type=Path, default=REPO,
                    help="CSVの場所（既定: repo直下）")
    ap.add_argument("--no-portal", action="store_true",
                    help="ポータル（学生配布）への同期コピーをしない")
    args = ap.parse_args()

    template = args.template
    out = args.out or template
    if not template.exists():
        raise SystemExit(
            f"テンプレが見つかりません: {template}\n"
            "（初回は CODAP v3 で3テーブルを作って保存したファイルをテンプレに置いてください）"
        )

    print(f"テンプレ: {template}")
    doc = inject(template, args.csv_dir)
    write_codap(doc, out)
    print(f"✅ 出力: {out}")

    # ポータルへ同期（学生配布物を最新化）
    if not args.no_portal and out != PORTAL_CODAP:
        if PORTAL_CODAP.exists() or PORTAL_CODAP.parent.exists():
            shutil.copyfile(out, PORTAL_CODAP)
            print(f"✅ ポータルへ同期: {PORTAL_CODAP}")
        else:
            print(f"（ポータル未検出のためスキップ: {PORTAL_CODAP}）")


if __name__ == "__main__":
    main()
