import pandas as pd

df = pd.read_csv('ml/artifacts/predict_check_202603.csv')
print('総行数:', len(df))
print('カラム:', list(df.columns))
print()

df['hit'] = df['的中'].astype(str) == 'True'

# 日別
daily = df.groupby('日付').agg(
    bets=('日付','count'),
    hits=('hit', 'sum'),
    invest=('投資額','sum'),
    refund=('返金額','sum'),
).reset_index()
daily['roi_pct'] = (daily['refund'] / daily['invest'] - 1) * 100
daily['hit_rate_pct'] = daily['hits'] / daily['bets'] * 100
print('=== 日別ベット数 ===')
print(daily.to_string())
print()

# 月間集計
total_inv = df['投資額'].sum()
total_ret = df['返金額'].sum()
hits = df['hit'].sum()
print('=== 月間集計 ===')
print(f'総投資額: {total_inv:,.0f}円')
print(f'総返金額: {total_ret:,.0f}円')
print(f'ROI: {(total_ret/total_inv - 1)*100:.1f}%')
print(f'的中数: {hits}件 / {len(df)}ベット')
print(f'的中率: {hits/len(df)*100:.2f}%')
prob_col = [c for c in df.columns if '確率' in c][0]
ev_col = [c for c in df.columns if '期待値' in c][0]
odds_col = [c for c in df.columns if 'オッズ' in c and '実' in c][0]
print(f'平均予想確率: {df[prob_col].mean():.2f}%')
print(f'平均期待値: {df[ev_col].mean():.3f}')
hit_df = df[df['hit']]
print(f'的中数: {len(hit_df)}件')
if len(hit_df) > 0:
    print(f'的中時平均オッズ: {hit_df[odds_col].mean():.1f}x')
    print(f'的中時中央値オッズ: {hit_df[odds_col].median():.1f}x')

print()
print('=== オッズソース内訳 ===')
print(df['オッズソース'].value_counts())

print()
print('=== 会場別ベット数 ===')
print(df.groupby('会場')['hit'].agg(['count','sum']).rename(columns={'count':'bets','sum':'hits'}).sort_values('bets', ascending=False).head(20))
