"""レシート分析教材のデータ生成器（CODAP / LDA 共通の生成元）.

設計の要点:
- 「購買ミッション（買い物のシーン）」を潜在テーマとして定義し、各レシートを
  ミッションの混合から生成する。これが LDA が発見する単位になる。
- 時間帯・曜日（平日/土日）・支店・年代・性別が「ミッションの出やすさ」を動かす。
  → 時間帯/曜日で中身もバスケットサイズも変わり、CODAP の単純集計で発見できる。
- 商品をミッション間でわざと共有する（例: おにぎり=朝食+ランチ, ポテチ=おやつ+夜食）。
  → 単純な「商品×時間帯」集計はぼやけるが、LDA は共起から潜在テーマを分離できる。
- 支店は単一テーマではなく複数ミッションの「配合」になる。
  → 「支店で一番売れた商品」では出せないプロファイルを LDA が出す。

再現性のため乱数シードを固定。標準ライブラリのみで動作（追加依存なし）。
"""

import csv
import random

SEED = 20260619
random.seed(SEED)

N_RECEIPTS = 1200
YEAR = 2024

# --- 商品カタログ: 商品名 -> (カテゴリ, 単価) ---
CATALOG = {
    "おにぎり": ("主食・基本食品", 140),
    "パン": ("主食・基本食品", 210),
    "卵": ("主食・基本食品", 240),
    "弁当": ("主食・基本食品", 510),
    "牛乳": ("主食・基本食品", 330),
    "サラダ": ("健康食品", 290),
    "フルーツ": ("健康食品", 270),
    "ヨーグルト": ("健康食品", 190),
    "アイス": ("お菓子・スナック", 150),
    "ガム": ("お菓子・スナック", 370),
    "キャンディ": ("お菓子・スナック", 350),
    "チョコレート": ("お菓子・スナック", 210),
    "ポテトチップス": ("お菓子・スナック", 110),
    "カップ麺": ("インスタント食品", 180),
    "サンドイッチ": ("インスタント食品", 450),
    "冷凍食品": ("インスタント食品", 300),
    "肉まん": ("インスタント食品", 190),
    "シャンプー": ("パーソナルケア", 110),
    "歯ブラシ": ("パーソナルケア", 300),
    "ティッシュ": ("掃除・衛生用品", 390),
    "トイレットペーパー": ("掃除・衛生用品", 330),
    "洗剤": ("掃除・衛生用品", 150),
    "お茶": ("飲み物", 120),
    "コーヒー": ("飲み物", 170),
    "ジュース": ("飲み物", 170),
    "栄養ドリンク": ("飲み物", 180),
    "炭酸飲料": ("飲み物", 310),
    "缶コーヒー": ("飲み物", 100),
    "野菜ジュース": ("飲み物", 180),
}

# --- 潜在テーマ（購買ミッション）: 商品 -> 出やすさの重み ---
# 商品はミッション間で共有される（共起構造を作るのが狙い）。
MISSIONS = {
    "朝食": {
        "パン": 5, "牛乳": 5, "卵": 4, "コーヒー": 4, "ヨーグルト": 3,
        "おにぎり": 3, "サンドイッチ": 3, "ジュース": 2, "野菜ジュース": 2, "お茶": 2,
    },
    "ランチ": {
        "おにぎり": 5, "弁当": 4, "サンドイッチ": 4, "サラダ": 3, "お茶": 4,
        "カップ麺": 3, "肉まん": 2, "ジュース": 2, "コーヒー": 2,
    },
    "夜食・おつまみ": {
        "ポテトチップス": 5, "冷凍食品": 4, "肉まん": 3, "カップ麺": 3,
        "炭酸飲料": 3, "缶コーヒー": 3, "アイス": 2, "チョコレート": 2,
    },
    "おやつ・嗜好品": {
        "アイス": 5, "チョコレート": 4, "キャンディ": 4, "ガム": 3,
        "ポテトチップス": 4, "炭酸飲料": 3, "ジュース": 3,
    },
    "日用品まとめ買い": {
        "トイレットペーパー": 5, "洗剤": 4, "歯ブラシ": 4, "ティッシュ": 4,
        "シャンプー": 3, "卵": 3, "牛乳": 3,
    },
    "健康志向": {
        "サラダ": 5, "フルーツ": 4, "ヨーグルト": 4, "野菜ジュース": 4,
        "栄養ドリンク": 3, "卵": 2, "お茶": 2,
    },
}
MISSION_NAMES = list(MISSIONS.keys())

# --- 時間帯ごとのミッション事前重み ---
TIME_PRIOR = {
    "朝": {"朝食": 6.0, "ランチ": 1.0, "夜食・おつまみ": 0.2, "おやつ・嗜好品": 0.8, "日用品まとめ買い": 1.5, "健康志向": 2.0},
    "昼": {"朝食": 1.0, "ランチ": 6.0, "夜食・おつまみ": 0.8, "おやつ・嗜好品": 2.0, "日用品まとめ買い": 1.0, "健康志向": 2.0},
    "夜": {"朝食": 0.3, "ランチ": 2.0, "夜食・おつまみ": 5.0, "おやつ・嗜好品": 4.0, "日用品まとめ買い": 2.0, "健康志向": 1.0},
}

# --- 平日/土日のミッション補正（乗算） ---
DAY_MULT = {
    "平日": {"朝食": 1.2, "ランチ": 1.3, "夜食・おつまみ": 1.0, "おやつ・嗜好品": 0.9, "日用品まとめ買い": 0.8, "健康志向": 1.0},
    "土日": {"朝食": 0.9, "ランチ": 0.7, "夜食・おつまみ": 1.3, "おやつ・嗜好品": 1.5, "日用品まとめ買い": 2.0, "健康志向": 1.1},
}

# --- 支店ごとのミッション配合（乗算）。全ミッションが全店で非ゼロ ---
# 各店の「看板ミッション」を強めに（単純集計の売れ筋でも個性が見える＝1bの読み取り
# とLDAの両方が効く）。ただし全ミッション非ゼロ＋共通商品の重なりは残し、単純集計
# だけで全部わかる＝LDA不要、にはならないようにする。中央区は意図的に均す（オフィス街
# ＝幅広い客層）。
STORE_MULT = {
    "中央区": {"朝食": 1.6, "ランチ": 1.8, "夜食・おつまみ": 0.6, "おやつ・嗜好品": 0.7, "日用品まとめ買い": 0.5, "健康志向": 1.4},
    "北区":   {"朝食": 1.2, "ランチ": 0.7, "夜食・おつまみ": 0.5, "おやつ・嗜好品": 0.6, "日用品まとめ買い": 3.4, "健康志向": 1.6},
    "東区":   {"朝食": 0.7, "ランチ": 1.6, "夜食・おつまみ": 2.6, "おやつ・嗜好品": 0.9, "日用品まとめ買い": 0.6, "健康志向": 0.6},
    "西区":   {"朝食": 0.8, "ランチ": 0.9, "夜食・おつまみ": 1.3, "おやつ・嗜好品": 2.8, "日用品まとめ買い": 0.5, "健康志向": 0.6},
}
STORE_WEIGHT = {"中央区": 330, "北区": 270, "東区": 290, "西区": 310}

# --- 年代・性別の軽い相関（ミッションごとの相対好み） ---
AGE_GROUPS = {"若年層": ["10代", "20代"], "中年層": ["30代", "40代"], "高年層": ["50代", "60代以上"]}
AGE_PREF = {  # ミッション -> 年齢層の相対重み
    "朝食": {"若年層": 1.0, "中年層": 1.0, "高年層": 1.0},
    "ランチ": {"若年層": 1.2, "中年層": 1.0, "高年層": 0.8},
    "夜食・おつまみ": {"若年層": 1.3, "中年層": 1.0, "高年層": 0.7},
    "おやつ・嗜好品": {"若年層": 1.6, "中年層": 0.9, "高年層": 0.6},
    "日用品まとめ買い": {"若年層": 0.7, "中年層": 1.1, "高年層": 1.4},
    "健康志向": {"若年層": 0.7, "中年層": 1.0, "高年層": 1.5},
}
GENDER_PREF = {  # ミッション -> 男性の確率
    "朝食": 0.5, "ランチ": 0.52, "夜食・おつまみ": 0.62,
    "おやつ・嗜好品": 0.42, "日用品まとめ買い": 0.48, "健康志向": 0.43,
}

# --- バスケットサイズ（点数）の平均（ミッション別） ---
BASKET_MEAN = {
    "朝食": 2.3, "ランチ": 2.0, "夜食・おつまみ": 2.6,
    "おやつ・嗜好品": 2.2, "日用品まとめ買い": 3.6, "健康志向": 2.8,
}

# 時間帯ごとのバスケット点数の補正（金額に時間帯差を出すため）。
# 朝＝さっと少なめ／夜＝多め。支店・年代・テーマとは直交（全店一律に乗る）。
TIME_BASKET_ADJ = {"朝": -0.4, "昼": 0.0, "夜": 0.1}

WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]
TIME_BANDS = {"朝": (6 * 60, 10 * 60 + 30), "昼": (11 * 60, 15 * 60), "夜": (17 * 60, 22 * 60 + 30)}


def weighted_choice(weights: dict):
    """{key: weight} から重み付きで1つ選ぶ."""
    items = list(weights.items())
    total = sum(w for _, w in items)
    r = random.uniform(0, total)
    upto = 0.0
    for k, w in items:
        upto += w
        if r <= upto:
            return k
    return items[-1][0]


def mission_prior(time_band, day_type, store):
    """時間帯×曜日×支店からミッション事前分布を合成."""
    pri = {}
    for m in MISSION_NAMES:
        pri[m] = TIME_PRIOR[time_band][m] * DAY_MULT[day_type][m] * STORE_MULT[store][m]
    return pri


def pick_time_band(day_type):
    if day_type == "土日":
        return weighted_choice({"朝": 0.18, "昼": 0.42, "夜": 0.40})
    return weighted_choice({"朝": 0.27, "昼": 0.40, "夜": 0.33})


def sample_basket_size(dominant, day_type, time_band):
    mean = BASKET_MEAN[dominant]
    if day_type == "土日":
        mean += 0.6
    mean += TIME_BASKET_ADJ[time_band]
    # 平均周りに散らして 1..6 にクランプ
    n = round(random.gauss(mean, 1.0))
    return max(1, min(6, n))


def draw_items(prior, dominant, size):
    """ドミナントミッション中心に、一部を別ミッションから引いて混合バスケットを作る."""
    chosen = []
    attempts = 0
    while len(chosen) < size and attempts < size * 6:
        attempts += 1
        if random.random() < 0.75:
            mission = dominant
        else:
            mission = weighted_choice(prior)
        product = weighted_choice(MISSIONS[mission])
        if product not in chosen:
            chosen.append(product)
    return chosen


def amount_band(total):
    if total < 400:
        return "低額"
    if total < 800:
        return "中額"
    return "高額"


def age_group_of(nendai):
    for g, members in AGE_GROUPS.items():
        if nendai in members:
            return g
    raise ValueError(nendai)


def random_date():
    """2024年の通日からランダムに日付を生成（曜日も返す）."""
    import datetime
    start = datetime.date(YEAR, 1, 1)
    day = random.randint(0, 365)  # 2024 はうるう年=366日
    d = start + datetime.timedelta(days=day)
    wd = WEEKDAY_JP[d.weekday()]
    day_type = "土日" if d.weekday() >= 5 else "平日"
    return d, wd, day_type


def generate():
    receipts = []  # dict rows for receipts.csv
    item_rows = []  # dict rows for receipt-items.csv

    for i in range(1, N_RECEIPTS + 1):
        rid = f"R{i:04d}"
        store = weighted_choice(STORE_WEIGHT)
        d, wd, day_type = random_date()
        time_band = pick_time_band(day_type)
        lo, hi = TIME_BANDS[time_band]
        minute = random.randint(lo, hi)
        jikoku = f"{minute // 60:02d}:{minute % 60:02d}"

        prior = mission_prior(time_band, day_type, store)
        dominant = weighted_choice(prior)

        size = sample_basket_size(dominant, day_type, time_band)
        products = draw_items(prior, dominant, size)
        if not products:  # フォールバック
            products = [weighted_choice(MISSIONS[dominant])]

        # 年代・性別（ドミナントミッションに軽く相関）
        age_group = weighted_choice(AGE_PREF[dominant])
        nendai = random.choice(AGE_GROUPS[age_group])
        gender = "男性" if random.random() < GENDER_PREF[dominant] else "女性"

        total = sum(CATALOG[p][1] for p in products)
        band = amount_band(total)

        receipts.append({
            "レシート番号": rid, "支店": store, "性別": gender, "年代": nendai,
            "曜日": wd, "日付": d.strftime("%Y/%m/%d"), "時刻": jikoku,
            "時間帯": time_band, "金額": total, "購入商品": " ".join(products),
        })

        for order, p in enumerate(products, start=1):
            cat, price = CATALOG[p]
            item_rows.append({
                "レシート番号": rid, "支店": store, "性別": gender, "年代": nendai,
                "曜日": wd, "日付": d.strftime("%Y/%m/%d"), "時刻": jikoku,
                "時間帯": time_band, "レシート金額": total, "商品名": p,
                "購入商品数": len(products), "商品順": order,
                "単品購入": 1 if len(products) == 1 else 0,
                "朝の購入": 1 if time_band == "朝" else 0,
                "昼の購入": 1 if time_band == "昼" else 0,
                "夜の購入": 1 if time_band == "夜" else 0,
                "平日": 1 if day_type == "平日" else 0,
                "土日": 1 if day_type == "土日" else 0,
                "若年層": 1 if age_group == "若年層" else 0,
                "中年層": 1 if age_group == "中年層" else 0,
                "高年層": 1 if age_group == "高年層" else 0,
                "低額": 1 if band == "低額" else 0,
                "中額": 1 if band == "中額" else 0,
                "高額": 1 if band == "高額" else 0,
                "カテゴリ": cat, "商品単価": price,
            })

    return receipts, item_rows


def write_csv(path, rows, fieldnames):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def build_summary(item_rows):
    """CODAP 集計用の軽量サブセット（long形式）.

    支店 × 時間帯 × 平日土日 × カテゴリ -> 商品点数・合計金額。
    重い明細（数千行）を集計させずにカテゴリの売れ方を見るための表。指標は
    カテゴリ横断で足してよい量（商品点数・合計金額）だけに絞る。レシート単位の
    指標（客数・客単価など）はレシート単位の receipts.csv 側で扱う。
    """
    agg = {}
    for r in item_rows:
        day_type = "土日" if r["土日"] == 1 else "平日"
        key = (r["支店"], r["時間帯"], day_type, r["カテゴリ"])
        a = agg.setdefault(key, {"商品点数": 0, "合計金額": 0})
        a["商品点数"] += 1
        a["合計金額"] += r["商品単価"]
    out = []
    for (store, tb, dt, cat), a in sorted(agg.items()):
        out.append({
            "支店": store, "時間帯": tb, "平日土日": dt, "カテゴリ": cat,
            "商品点数": a["商品点数"], "合計金額": a["合計金額"],
        })
    return out


def main():
    receipts, item_rows = generate()

    receipt_fields = ["レシート番号", "支店", "性別", "年代", "曜日", "日付", "時刻", "時間帯", "金額", "購入商品"]
    item_fields = list(item_rows[0].keys())
    summary = build_summary(item_rows)
    summary_fields = ["支店", "時間帯", "平日土日", "カテゴリ", "商品点数", "合計金額"]

    write_csv("receipts.csv", receipts, receipt_fields)
    write_csv("receipt-items.csv", item_rows, item_fields)
    write_csv("receipt-summary.csv", summary, summary_fields)

    # LDA アプリ側は receipts.csv と同形式の receipt_data.csv を読む
    write_csv("../receipt-analysis-lda/receipt_data.csv", receipts, receipt_fields)

    print(f"receipts.csv: {len(receipts)} 行")
    print(f"receipt-items.csv: {len(item_rows)} 行")
    print(f"receipt-summary.csv: {len(summary)} 行")
    print("../receipt-analysis-lda/receipt_data.csv も更新")


if __name__ == "__main__":
    main()
