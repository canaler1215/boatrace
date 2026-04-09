"""
predict.yml から呼び出される推論・期待値計算スクリプト
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[2]))

from collector.db_writer import get_connection, upsert_prediction
from model.predictor import load_model, predict_win_prob, calc_trifecta_probs, calc_expected_values
from features.feature_builder import build_features
import pandas as pd
import os


def main():
    model_path = Path("ml/artifacts/model_latest.pkl")
    if not model_path.exists():
        print("No model found. Run retrain first.")
        return

    model = load_model(model_path)
    print("Model loaded.")

    with get_connection() as conn:
        # 本日の未予測レースを取得
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.id, r.stadium_id, r.race_date, r.race_no
                FROM races r
                LEFT JOIN predictions p ON p.race_id = r.id
                WHERE r.race_date = CURRENT_DATE AND p.id IS NULL AND r.status != 'finished'
            """)
            races = cur.fetchall()

        for race in races:
            race_id = race[0]
            print(f"Predicting race {race_id}...")
            # TODO: 実際の特徴量取得・推論実装
            # X = build_features(...)
            # probs = predict_win_prob(model, X)
            # trifecta = calc_trifecta_probs(probs[0])
            # odds = fetch current odds from db
            # results = calc_expected_values(trifecta, odds)
            # for r in results:
            #     upsert_prediction(conn, {...})
        conn.commit()
    print("Done.")


if __name__ == "__main__":
    main()
