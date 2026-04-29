"""場名 ⇔ 場 ID (1〜24) の双方向解決ヘルパ.

入力形式:
  - 整数 1〜24
  - 文字列 "1" 〜 "24" / "01" 〜 "24"
  - 漢字名 ("桐生" 等) / ひらがな別名 ("きりゅう" 等)
"""
from __future__ import annotations

# JCD コード → 漢字 / ひらがな別名
STADIUMS: dict[int, tuple[str, str]] = {
    1:  ("桐生",   "きりゅう"),
    2:  ("戸田",   "とだ"),
    3:  ("江戸川", "えどがわ"),
    4:  ("平和島", "へいわじま"),
    5:  ("多摩川", "たまがわ"),
    6:  ("浜名湖", "はまなこ"),
    7:  ("蒲郡",   "がまごおり"),
    8:  ("常滑",   "とこなめ"),
    9:  ("津",     "つ"),
    10: ("三国",   "みくに"),
    11: ("びわこ", "びわこ"),
    12: ("住之江", "すみのえ"),
    13: ("尼崎",   "あまがさき"),
    14: ("鳴門",   "なると"),
    15: ("丸亀",   "まるがめ"),
    16: ("児島",   "こじま"),
    17: ("宮島",   "みやじま"),
    18: ("徳山",   "とくやま"),
    19: ("下関",   "しものせき"),
    20: ("若松",   "わかまつ"),
    21: ("芦屋",   "あしや"),
    22: ("福岡",   "ふくおか"),
    23: ("唐津",   "からつ"),
    24: ("大村",   "おおむら"),
}

# JCD コード → 場固定特性 (水質 / ナイター / 標高)
# 出典: kyotei-pr.jp 水質分類 (海水10 / 汽水5 / 淡水9)、boatrace.jp 公式ナイター場
# 標高は際立つ 2 場 (桐生 124m / びわこ 85m) のみ計上、他は 0 (海抜近傍)
# water_type: "fresh" (淡水) / "brackish" (汽水) / "salt" (海水)
STADIUM_FEATURES: dict[int, dict[str, object]] = {
    1:  {"water_type": "fresh",    "is_night": True,  "elevation_m": 124},
    2:  {"water_type": "fresh",    "is_night": False, "elevation_m": 0},
    3:  {"water_type": "brackish", "is_night": False, "elevation_m": 0},
    4:  {"water_type": "salt",     "is_night": False, "elevation_m": 0},
    5:  {"water_type": "fresh",    "is_night": False, "elevation_m": 0},
    6:  {"water_type": "brackish", "is_night": False, "elevation_m": 0},
    7:  {"water_type": "salt",     "is_night": True,  "elevation_m": 0},
    8:  {"water_type": "salt",     "is_night": False, "elevation_m": 0},
    9:  {"water_type": "salt",     "is_night": False, "elevation_m": 0},
    10: {"water_type": "fresh",    "is_night": False, "elevation_m": 0},
    11: {"water_type": "fresh",    "is_night": False, "elevation_m": 85},
    12: {"water_type": "fresh",    "is_night": True,  "elevation_m": 0},
    13: {"water_type": "brackish", "is_night": False, "elevation_m": 0},
    14: {"water_type": "salt",     "is_night": False, "elevation_m": 0},
    15: {"water_type": "fresh",    "is_night": True,  "elevation_m": 0},
    16: {"water_type": "fresh",    "is_night": False, "elevation_m": 0},
    17: {"water_type": "salt",     "is_night": False, "elevation_m": 0},
    18: {"water_type": "salt",     "is_night": False, "elevation_m": 0},
    19: {"water_type": "salt",     "is_night": False, "elevation_m": 0},
    20: {"water_type": "salt",     "is_night": True,  "elevation_m": 0},
    21: {"water_type": "fresh",    "is_night": False, "elevation_m": 0},
    22: {"water_type": "brackish", "is_night": False, "elevation_m": 0},
    23: {"water_type": "brackish", "is_night": False, "elevation_m": 0},
    24: {"water_type": "salt",     "is_night": True,  "elevation_m": 0},
}

# 水質コード → 日本語ラベル
WATER_TYPE_LABEL: dict[str, str] = {
    "fresh":    "淡水",
    "brackish": "汽水",
    "salt":     "海水",
}

# 双方向ルックアップを構築 (漢字 / ひらがな の両方を ID にマップ)
_NAME_TO_ID: dict[str, int] = {}
for _id, (_kanji, _kana) in STADIUMS.items():
    _NAME_TO_ID[_kanji] = _id
    _NAME_TO_ID[_kana] = _id


class UnknownStadiumError(ValueError):
    """場名 / ID が解決できなかった."""


def resolve(query: int | str) -> int:
    """場名 / ID 文字列 / 整数 を JCD ID (1〜24) に解決する.

    Examples
    --------
    >>> resolve(1)
    1
    >>> resolve("01")
    1
    >>> resolve("桐生")
    1
    >>> resolve("きりゅう")
    1
    """
    if isinstance(query, int):
        if 1 <= query <= 24:
            return query
        raise UnknownStadiumError(f"stadium id {query} out of range 1..24")

    s = query.strip()
    if not s:
        raise UnknownStadiumError("empty stadium query")

    # 数字 (ゼロ埋め含む)
    if s.isdigit():
        n = int(s)
        if 1 <= n <= 24:
            return n
        raise UnknownStadiumError(f"stadium id {n} out of range 1..24")

    # 漢字 / ひらがな
    if s in _NAME_TO_ID:
        return _NAME_TO_ID[s]

    raise UnknownStadiumError(f"unknown stadium name: {query!r}")


def name_of(stadium_id: int) -> str:
    """JCD ID から漢字名を返す."""
    if stadium_id not in STADIUMS:
        raise UnknownStadiumError(f"unknown stadium id: {stadium_id}")
    return STADIUMS[stadium_id][0]


def features_of(stadium_id: int) -> dict[str, object]:
    """JCD ID から場固定特性 (water_type / is_night / elevation_m) を返す.

    未登録 ID はデフォルト (淡水・デイ・標高 0) を返す.
    """
    return STADIUM_FEATURES.get(
        stadium_id,
        {"water_type": "fresh", "is_night": False, "elevation_m": 0},
    )
