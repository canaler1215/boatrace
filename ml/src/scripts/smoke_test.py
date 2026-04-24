"""
Smoke test: DB 接続・テーブル存在確認・1 日分バックテスト（合成オッズ）を行う。

実行方法:
  python ml/src/scripts/smoke_test.py

完走すれば "Smoke test passed." を出力して exit 0。
いずれかのチェックで失敗すれば [FAIL] を出力して exit 1。

CI 利用例:
  python ml/src/scripts/smoke_test.py || exit 1
"""
import os
import sys
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).parents[1]))


def _ok(msg: str) -> None:
    print(f"[OK] {msg}")


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


# ── 1. DATABASE_URL 確認 ──────────────────────────────────────────────────────

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

db_url = os.environ.get("DATABASE_URL")
if not db_url:
    _fail("DATABASE_URL が設定されていません。.env ファイルを確認してください。")
_ok("DATABASE_URL が設定されています")


# ── 2. DB 接続確認 ────────────────────────────────────────────────────────────

try:
    import psycopg
    conn = psycopg.connect(db_url)
    conn.close()
except Exception as e:
    _fail(f"PostgreSQL に接続できません: {e}")
_ok("PostgreSQL に接続できました")


# ── 3. 必須テーブル存在確認 ───────────────────────────────────────────────────

REQUIRED_TABLES = [
    "races", "race_entries", "racers", "odds",
    "predictions", "model_versions",
]

try:
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public'
                """
            )
            existing = {row[0] for row in cur.fetchall()}
    missing = [t for t in REQUIRED_TABLES if t not in existing]
    if missing:
        _fail(f"必須テーブルが存在しません: {missing}")
except Exception as e:
    _fail(f"テーブル確認中にエラー: {e}")
_ok("必須テーブルが存在します")


# ── 4. 1 日分バックテスト（合成オッズ、最新モデル使用）──────────────────────

try:
    import joblib
    import pandas as pd

    artifacts_dir = Path(__file__).parents[3] / "artifacts"
    models = sorted(artifacts_dir.glob("model_*.pkl"), reverse=True)
    if not models:
        print(f"[SKIP] 学習済みモデルが見つかりません ({artifacts_dir})")
        print("       run_retrain.py を実行してモデルを作成してください")
    else:
        model = joblib.load(models[0])

        from features.feature_builder import build_features_from_history
        from backtest.engine import run_race

        # 1 日分の K ファイルキャッシュを探す（直近 30 日以内）
        data_dir = Path(__file__).parents[3] / "data"
        sample_csv = None
        for i in range(30):
            d = date.today() - timedelta(days=i + 1)
            pattern = f"k{str(d.year)[2:]}{d.month:02d}{d.day:02d}.csv"
            candidates = list(data_dir.rglob(pattern))
            if candidates:
                sample_csv = candidates[0]
                break

        if sample_csv is None:
            print("[SKIP] キャッシュデータが見つからないため 1 日バックテストをスキップします")
            print("       run_backtest.py を一度実行してデータをキャッシュしてください")
        else:
            df_day = pd.read_csv(sample_csv)
            if df_day.empty:
                print(f"[SKIP] {sample_csv} が空のためスキップ")
            else:
                features = build_features_from_history(df_day)
                race_ids = features["race_id"].unique()[:3]
                for rid in race_ids:
                    df_race = features[features["race_id"] == rid]
                    run_race(
                        race_df=df_race,
                        model=model,
                        prob_threshold=0.07,
                        bet_amount=100,
                        max_bets_per_race=5,
                        race_odds=None,  # 合成オッズ使用
                        ev_threshold=2.0,
                        exclude_courses=[2, 4, 5],
                        min_odds=100,
                        exclude_stadiums=[11],
                    )
                _ok(f"バックテストが 1 日分完走しました（合成オッズ、race_ids={len(race_ids)}件）")

except Exception as e:
    _fail(f"バックテスト中にエラー: {e}")


print("\nSmoke test passed.")
