# レシートデータ分析 (CODAP)

高校生向け体験授業「データで読み解くお店の売れ筋」で使用する CODAP 教材です。
コンビニのレシートデータを CODAP で集計・可視化し、データサイエンスの基本を体験します。

## ファイル構成

| ファイル | 説明 |
|---|---|
| `receipt-analysis.codap` | 生徒用 CODAP ファイル（**CODAP v3 形式**。3テーブル＝receipts/receipt-items/receipt-summary。生徒が自分でグラフを作成する）。**CSVから `build_codap.py` で再生成される成果物**（テンプレも兼ねる） |
| `receipt-analysis-teacher.codap` | 教員用 CODAP（デモ用グラフ付き）。※再設計前の **v2・旧データのまま**。使う場合は v3 で作り直しが必要（下記） |
| `receipts.csv` | レシートデータ（1,200件。レシート単位の購入情報） |
| `receipt-items.csv` | レシート商品データ（3,176件。商品単位に展開したデータ） |
| `receipt-summary.csv` | 集計用サブセット（165行。支店×時間帯×平日土日×カテゴリの集計済みデータ。CODAP が重くなるのを避けたいときに使用） |
| `generate_data.py` | 上記CSVの生成スクリプト（乱数シード固定で再現可能） |
| `build_codap.py` | 最新CSVを CODAP(v3) テンプレへ流し込み、`receipt-analysis.codap` を再生成＋ポータルへ同期 |

## 使い方

### 生徒向け

1. [CODAP](https://codap.concord.org/) を開く
2. `receipt-analysis.codap` を読み込む
3. テーブルからグラフを作成して分析する

### 教員向け

- `receipt-analysis-teacher.codap` をデモや解答例として使用する

## データについて

### receipts.csv

レシート1枚を1行として記録したデータです。

主な列: レシート番号、支店、性別、年代、曜日、日付、時刻、時間帯、金額、購入商品

### receipt-items.csv

レシート内の各商品を1行に展開したデータです。

主な列: レシート番号、支店、性別、年代、曜日、日付、時刻、時間帯、レシート金額、商品名、カテゴリ、商品単価、各種ダミー変数（単品購入、時間帯別、曜日別、年齢層別、金額帯別）

### receipt-summary.csv

商品単位データを「支店 × 時間帯 × 平日土日 × カテゴリ」で集計した軽量データです。
CODAP では数千行の生データを集計すると重くなるため、傾向比較はこの集計済みデータで行えます。
カテゴリの売れ方を見るための表なので、指標はカテゴリ横断で足してよい量（商品点数・合計金額）だけに絞っています。
レシート単位の指標（客数・客単価など）は `receipts.csv`（1,200行・軽い）を直接集計してください。

列: 支店、時間帯、平日土日、カテゴリ、商品点数、合計金額

## データ設計の考え方

このデータは「購買ミッション（買い物のシーン）」を潜在テーマとして生成しています。

- **6つのミッション**: 朝食 / ランチ / 夜食・おつまみ / おやつ・嗜好品 / 日用品まとめ買い / 健康志向
- **時間帯・曜日・支店・年代がミッションの出やすさを変える**ため、朝/昼/夜や平日/土日で
  購入内容もバスケットサイズも変わる（土日は点数が多い）。→ CODAP の単純集計で発見できる。
- **商品はミッション間で共有される**（例: おにぎり=朝食+ランチ、ポテトチップス=おやつ+夜食）。
  そのため「商品×時間帯」の単純集計はぼやけるが、**LDA は共起から潜在テーマを分離**できる。
- **支店は単一テーマではなく複数ミッションの配合**になる。「支店で一番売れた商品」では出せない
  プロファイルを LDA が示す。→ 単純集計と LDA の役割の違いを対比できる。

## データ／CODAPの再生成パイプライン

CSV が唯一の正本です。データを作り直す手順:

```sh
# 1. CSV を生成（repo直下＋LDAアプリ側 receipt_data.csv を同時更新・シード固定で再現可能）
uv run python generate_data.py

# 2. 最新CSVから CODAP(v3) を再生成（receipt-analysis.codap を更新＋ポータル配布物へ同期）
uv run python build_codap.py
```

`build_codap.py` は `receipt-analysis.codap` を**テンプレ兼出力**として使い、
表レイアウト・属性の並び・タイル構成は保持したまま、各属性の値・行・IDだけ差し替えます
（IDは決定論的＝データが同じなら出力も同一でgit差分が出ない）。これで「CSVを更新したら
CODAPが取り残される」事故を防ぎます。

- ポータル（学生配布）へのコピーをやめたいとき: `uv run python build_codap.py --no-portal`
- 教員用ファイル（`receipt-analysis-teacher.codap`）は v2・旧データのまま。グラフ付きの v3 版が
  必要なら、一度 CODAP v3 で3テーブル＋グラフを作って保存し、それをテンプレに
  `uv run python build_codap.py --template receipt-analysis-teacher.codap --out receipt-analysis-teacher.codap --no-portal` で再生成できます。

> CODAP は今回からブラウザ版（[codap.concord.org](https://codap.concord.org/)）が **v3 が既定**です。配布ファイルも v3 形式にしています。
