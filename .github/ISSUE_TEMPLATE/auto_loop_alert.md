---
name: Auto Loop Alert
about: auto_backtest_loop.yml による自動異常検知（手動起票不要）
title: '[auto-loop] YYYY-MM ROI +XX% (zone zone)'
labels: auto-loop, needs-investigation
assignees: ''
---

## ⚠️ 自動バックテスト異常検知

**ゾーン**: <!-- warning / danger -->
**期間**: <!-- YYYY-MM -->
**ROI**: <!-- +XXX.X% -->

## KPI サマリ

| 項目 | 値 |
|------|-----|
| 期間 | |
| ROI | |
| ベット数 | |
| 的中件数 | |
| 平均オッズ | |
| avg top_prob | |
| ゾーン | |

## 直近 6 ヶ月 ROI 推移

| 月 | ROI | ゾーン |
|----|-----|--------|
| | | |

## 想定原因チェックリスト

- [ ] オッズデータ取得エラー（boatrace.jp の HTML 変更など）
- [ ] モデルのドリフト（直近データとの乖離）
- [ ] 購入ルールの有効性低下（コース・EV 閾値の見直し）
- [ ] 季節性の影響（3 月・6 月は歴史的に低 ROI）
- [ ] レース環境の変化（新設場・規則改正等）
- [ ] その他: <!-- 自由記述 -->

## 調査ログ

<!-- 調査・対処の経過を記録してください -->

## 推奨コマンド

```bash
# セグメント別 ROI 確認
python ml/src/scripts/run_segment_analysis.py --combos-csv artifacts/combos_YYYYMM.csv

# キャリブレーション確認
python ml/src/scripts/run_calibration.py --year YYYY --month MM

# 再学習（必要な場合）
python ml/src/scripts/run_retrain.py
```

## 参照ドキュメント

- [AUTO_LOOP_PLAN.md](../../AUTO_LOOP_PLAN.md)
- [BET_RULE_REVIEW_202509_202512.md](../../BET_RULE_REVIEW_202509_202512.md)
- [CLAUDE.md 運用ルール](../../CLAUDE.md#運用ルールs6-4)
