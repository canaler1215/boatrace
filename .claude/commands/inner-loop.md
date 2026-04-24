---
description: 内ループを実行する（GitHub Actions でバックテスト→分析→対策→再実行）
argument-hint: <year> <month> [max-iterations]
---

# /inner-loop — 自律バックテスト改善ループ

引数: `$ARGUMENTS`（例: `2025 12` または `2025 12 3`）

**重要: バックテストは必ず GitHub Actions (`claude_fix.yml`) 経由で実行すること。
ローカルの `python ml/src/scripts/run_backtest.py` は絶対に使わない。**

理由:
- ローカル実行は実オッズダウンロードに数時間かかる（本人の PC を占有してしまう）
- GitHub Actions 側でオッズキャッシュが効くので繰り返し実行が高速
- 全イテレーションの履歴が `gh run list` で追跡可能

---

## 前提チェック

実行前に以下を確認すること。欠けていれば **即座にユーザーに質問** して止まる。

```bash
# 1. gh CLI が使えるか
gh --version

# 2. 認証済みか
gh auth status

# 3. 正しいリポジトリにいるか（canaler1215/boatrace のはず）
gh repo view --json nameWithOwner -q '.nameWithOwner'
```

未インストールなら以下を案内:

> `gh` CLI が未インストールです。
> Windows: `winget install --id GitHub.cli` でインストール後、`gh auth login` で認証してください。

---

## 実行手順（この順番を厳守）

### Step 1: 引数パース

`$ARGUMENTS` を空白で分割:
- 1番目 = YEAR（必須）
- 2番目 = MONTH（必須）
- 3番目 = MAX_ITER（省略時 3）

引数が足りなければユーザーに質問して停止。

### Step 2: baseline ラン（現行パラメータで実行）

現在の `ml/configs/strategy_default.yaml` のパラメータをそのまま使って baseline ラン。

```bash
gh workflow run claude_fix.yml \
  -f year=<YEAR> \
  -f month=<MONTH> \
  -f label=baseline
```

実行直後に run_id を取得:

```bash
# 数秒待ってから最新ランを取得（workflow_dispatch から反映に1〜2秒かかる）
sleep 3
RUN_ID=$(gh run list --workflow=claude_fix.yml --limit=1 --json databaseId -q '.[0].databaseId')
echo "Started run: ${RUN_ID}"
```

### Step 3: 完了まで待機

```bash
gh run watch ${RUN_ID} --exit-status
```

`--exit-status` でワークフローが失敗した場合は非0終了するので、そこで停止してユーザーに報告する。

**注意**: ウォッチ中はユーザーに「GitHub Actions で実行中（〇〇分経過）」と進捗を伝える。

### Step 4: Artifacts をダウンロード

```bash
mkdir -p /tmp/inner-loop/baseline
gh run download ${RUN_ID} -D /tmp/inner-loop/baseline
ls -la /tmp/inner-loop/baseline/
```

ダウンロード対象: `backtest_*.csv`, `gate_result_*.json`, `gate_result_*.txt`,
`segment_*.txt`, `combos_*.csv`

### Step 5: 結果の読み込みと分析

以下を順に Read して内容を把握:

1. `gate_result_YYYYMM.json` → zone / roi_pct / total_bets / wins / avg_odds を確認
2. `gate_result_YYYYMM_baseline.txt` → 人間可読な KPI サマリ
3. `segment_YYYYMM_baseline.txt` → コース/場/確率帯/EV帯別の ROI
4. 必要なら `backtest_YYYYMM_baseline.csv` を pandas で読み込んで追加分析

分析の観点（`.claude/AGENT_BRIEF.md` を参照）:
- コース別 ROI: 最下位コース ROI < −30% かつ 100 ベット以上 → `exclude_courses` 追加候補
- 場別 ROI: 最下位場 ROI < −50% かつ 100 ベット以上 → `exclude_stadiums` 追加候補
- 確率帯別 ROI: 低確率帯（7〜9%）が全体平均より −20pp 低い → `prob_threshold` を 0.09 に引き上げ候補
- EV 帯別 ROI: 低 EV 帯（2.0〜2.5）が赤字 → `ev_threshold` を 2.5 に引き上げ候補

### Step 6: zone 判定と分岐

gate_result JSON の `zone` フィールドで分岐:

- **normal**: 「baseline が既に normal ゾーンです。改善の必要なし」と報告して終了
- **caution**: パラメータ調整を試みるか、ユーザーに「現状維持でいいか」を確認
- **warning / danger**: 必ず改善案を立案して Step 7 に進む

### Step 7: 対策立案と strategy_default.yaml 修正

分析結果から**最も効果が大きそうな単一パラメータ**を1つ選んで修正する。
一度に複数のパラメータを変えないこと（原因切り分けが不能になる）。

```bash
# 修正前をバックアップ
cp ml/configs/strategy_default.yaml /tmp/inner-loop/strategy_before.yaml
```

`Edit` ツールで `ml/configs/strategy_default.yaml` を修正。コミットは**まだしない**。

### Step 8: candidate ラン

修正した YAML を使って再実行する必要があるが、`claude_fix.yml` は CLI 引数でパラメータを受け取る仕様なので、
**YAML の新しい値を CLI 引数として渡す**。

```bash
# 修正後の YAML からパラメータを抽出
NEW_PROB=$(python -c "import yaml; print(yaml.safe_load(open('ml/configs/strategy_default.yaml'))['filters']['prob_threshold'])")
NEW_EV=$(python -c "import yaml; print(yaml.safe_load(open('ml/configs/strategy_default.yaml'))['filters']['ev_threshold'])")
NEW_COURSES=$(python -c "import yaml; c=yaml.safe_load(open('ml/configs/strategy_default.yaml'))['filters'].get('exclude_courses', []); print(' '.join(map(str,c)))")
NEW_MIN_ODDS=$(python -c "import yaml; print(yaml.safe_load(open('ml/configs/strategy_default.yaml'))['filters'].get('min_odds', ''))")
NEW_STADIUMS=$(python -c "import yaml; s=yaml.safe_load(open('ml/configs/strategy_default.yaml'))['filters'].get('exclude_stadiums', []); print(' '.join(map(str,s)))")

gh workflow run claude_fix.yml \
  -f year=<YEAR> \
  -f month=<MONTH> \
  -f prob_threshold="${NEW_PROB}" \
  -f ev_threshold="${NEW_EV}" \
  -f exclude_courses="${NEW_COURSES}" \
  -f min_odds="${NEW_MIN_ODDS}" \
  -f exclude_stadiums="${NEW_STADIUMS}" \
  -f label=candidate-iter1
```

Step 3〜4 と同様に watch & download:

```bash
sleep 3
CAND_RUN=$(gh run list --workflow=claude_fix.yml --limit=1 --json databaseId -q '.[0].databaseId')
gh run watch ${CAND_RUN} --exit-status
mkdir -p /tmp/inner-loop/candidate-iter1
gh run download ${CAND_RUN} -D /tmp/inner-loop/candidate-iter1
```

### Step 9: baseline vs candidate 比較

両方の `gate_result_YYYYMM.json` / `segment_*.txt` を読んで比較:

| 指標 | baseline | candidate | Δ |
|------|----------|-----------|---|
| ROI  | X%       | Y%        | +N pp |
| ベット数 | A   | B        | -M  |
| 的中率 | P%    | Q%       | +R pp |
| ゾーン | ...   | ...      | ... |

分岐:
- **ΔROI ≥ +50pp かつ ゾーンが改善 / 維持** → Step 10（PR 作成）へ進む
- **ΔROI < +50pp かつ イテレーション < MAX_ITER** → `strategy_before.yaml` を復元して別パラメータで再試行（Step 7 に戻る、label=candidate-iter2）
- **MAX_ITER に到達 or 悪化のみ** → `strategy_before.yaml` を復元して撤退報告

### Step 10: PR 作成

改善が確認できた場合のみ PR を作成。

```bash
# 新ブランチ作成
BRANCH="auto-loop/fix-$(date +%Y%m)-$(date +%H%M)"
git checkout -b ${BRANCH}

# 修正済み YAML を commit
git add ml/configs/strategy_default.yaml
git commit -m "fix(strategy): <対策の要約> (auto-loop <YEAR>-<MONTH>)"
git push -u origin ${BRANCH}

# PR 作成
gh pr create \
  --title "[auto-loop] <YEAR>-<MONTH> ROI改善案: <変更内容>" \
  --body "$(cat <<'EOF'
## 変更前後のパラメータ

| パラメータ | before | after |
|-----------|--------|-------|
| ... | ... | ... |

## 分析根拠

<segment分析で何が悪かったか>

## 検証結果（candidate ラン）

| 指標 | baseline | candidate |
|------|----------|-----------|
| ROI | X% | Y% |
| ベット数 | ... | ... |

## 懸念事項

<副作用・サンプルサイズの問題など>

---
*このPRは `/inner-loop` により作成されました（オーケストレーター: ローカル Claude セッション）。*
EOF
)" \
  --label "auto-loop-candidate"

# main ブランチに戻る
git checkout main
```

### Step 11: 終了報告

ユーザーに結果をまとめて報告:

```
内ループ完了（イテレーション数: N）
- baseline ROI: X%（ゾーン: ...）
- 最終 candidate ROI: Y%（ゾーン: ...）
- PR: <PR URL>  または  撤退（理由: ...）
```

---

## 絶対にやってはいけないこと

- ❌ `python ml/src/scripts/run_backtest.py` をローカル実行する（前提を破壊）
- ❌ 一度に複数パラメータを変更する（原因切り分け不能）
- ❌ `ml/configs/` 以外のファイルを変更する（CODEOWNERS 違反）
- ❌ PR をローカルでマージする（Branch Protection に引っかかるし、レビュー必須）
- ❌ `--retrain` をデフォルトで付ける（1時間以上かかる、必要時のみユーザーに相談して付ける）

## 撤退条件

- 3 イテレーションしても ΔROI が +50pp 未満
- 変更すべき場所が `ml/configs/` 外（モデル再学習が必要な症状）
- segment 分析で「全セグメントが悪い」（構造的問題、パラメータ調整では不可）

撤退時は strategy_default.yaml を baseline に戻し（`cp /tmp/inner-loop/strategy_before.yaml ml/configs/strategy_default.yaml`）、ユーザーに理由を報告する。
