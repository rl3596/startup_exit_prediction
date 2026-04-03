import pandas as pd
import numpy as np
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score, classification_report
import warnings
warnings.filterwarnings('ignore')

# ==========================================
# 1) Setup & Load Data
# ==========================================
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'data'

if not DATA_DIR.exists():
    DATA_DIR = BASE_DIR

print("Loading data... Please wait.")
funding = pd.read_csv(DATA_DIR / 'funding_rounds.csv', parse_dates=['announced_on'])
ipos = pd.read_csv(DATA_DIR / 'ipos.csv', parse_dates=['went_public_on'])
company_team = pd.read_csv(DATA_DIR / 'company_team.csv')
jobs = pd.read_csv(DATA_DIR / 'jobs.csv')

# ==========================================
# 2) Define Time Anchor (Day 0)
# ==========================================
first_funding = (
    funding.groupby('company_uuid', as_index=False)['announced_on']
    .min()
    .rename(columns={'announced_on': 'first_funding_date'})
)
first_funding = first_funding.dropna(subset=['first_funding_date'])
companies = first_funding.copy()

# 合并时间起点，计算相对日期
funding = funding.merge(companies, on='company_uuid', how='left')
ipos = ipos.merge(companies, on='company_uuid', how='left')

funding['days_since_first_funding'] = (funding['announced_on'] - funding['first_funding_date']).dt.days
ipos['days_to_ipo'] = (ipos['went_public_on'] - ipos['first_funding_date']).dt.days

# ==========================================
# 3) Dynamic Target Window (基于年龄的动态门槛)
# ==========================================
print("Calculating dynamic success labels based on company age...")

def get_success_threshold(age_months: float):
    """根据公司年龄返回对应的融资门槛 (USD)"""
    if age_months >= 120: return 140_000_000
    if age_months >= 96:  return 100_000_000
    if age_months >= 72:  return 60_000_000
    if age_months >= 48:  return 25_000_000
    if age_months >= 24:  return 5_000_000
    return np.nan  # 不足24个月暂不评估

# 1. 确定数据库的“今天”（最后一条记录的时间）
db_cutoff_date = funding['announced_on'].max()

# 2. 计算每家公司的“观察时长”
companies['potential_age_days'] = (db_cutoff_date - companies['first_funding_date']).dt.days
companies['potential_age_months'] = companies['potential_age_days'] / 30.44

# 3. 计算截至目前每家公司的总融资额
total_raised = funding.groupby('company_uuid')['money_raised_usd'].sum().reset_index()
companies = companies.merge(total_raised, on='company_uuid', how='left')
companies['money_raised_usd'] = companies['money_raised_usd'].fillna(0)

# 4. 获取 IPO 公司名单
ipo_uuids = ipos['company_uuid'].unique()

# 5. 应用动态门槛判定
companies['dynamic_threshold'] = companies['potential_age_months'].apply(get_success_threshold)

# 成功逻辑：融资额达标 OR 已经IPO
companies['is_success'] = np.where(
    (companies['money_raised_usd'] >= companies['dynamic_threshold']) | 
    (companies['company_uuid'].isin(ipo_uuids)), 
    1, 0
)

# 6. 过滤掉“发育中”的公司：年龄 < 24个月 且 还没成功的
valid_companies = companies[
    (companies['potential_age_months'] >= 24) | 
    (companies['is_success'] == 1)
].copy()

print(f"Kept {len(valid_companies)} companies for modeling.")

# ==========================================
# 4) Feature Window: First 12 Months (含清洗逻辑)
# ==========================================
print("Extracting 12-month features and cleaning missing data...")

# 1. 框定前 12 个月的数据
funding_12m = funding[funding['days_since_first_funding'] <= 365]

# 2. 【新增核心逻辑】找到在前 12 个月内有任何一笔融资额为 NaN 的公司 UUID
# 如果你想更严格：只要有一笔没记，就删掉整家公司
missing_money_uuids = funding_12m[funding_12m['money_raised_usd'].isna()]['company_uuid'].unique()

# 3. 从 valid_companies 中剔除这些公司
before_count = len(valid_companies)
valid_companies = valid_companies[~valid_companies['company_uuid'].isin(missing_money_uuids)]
after_count = len(valid_companies)

print(f"Dropped {before_count - after_count} companies due to missing funding data in the first 12 months.")

# 4. 接下来的特征提取会自动只针对剩余的“干净”公司进行
features_12m = funding_12m.groupby('company_uuid', as_index=False).agg(
    first_year_funding_usd=('money_raised_usd', 'sum'),
    first_year_round_count=('round_uuid', 'count'),
    first_year_investor_count=('num_investors', 'sum')
)

print("Extracting 12-month Point-in-Time features...")
funding_12m = funding[funding['days_since_first_funding'] <= 365]

# a) 融资特征
features_12m = funding_12m.groupby('company_uuid', as_index=False).agg(
    first_year_funding_usd=('money_raised_usd', 'sum'),
    first_year_round_count=('round_uuid', 'count'),
    first_year_investor_count=('num_investors', 'sum')
)

# b) 轮次标记
for stage in ['pre_seed', 'seed', 'series_a']:
    stage_flag = (
        funding_12m.assign(flag=(funding_12m['investment_type'] == stage).astype(int))
        .groupby('company_uuid')['flag']
        .max()
        .reset_index()
        .rename(columns={'flag': f'first_year_has_{stage}'})
    )
    features_12m = features_12m.merge(stage_flag, on='company_uuid', how='left')

# c) 创始人特征
founder_team = company_team[company_team['title'].str.contains('Founder|CEO', case=False, na=False)]
team_counts = founder_team.groupby('company_uuid', as_index=False).size().rename(columns={'size': 'founder_count'})

founder_jobs = jobs[jobs['person_uuid'].isin(founder_team['person_uuid'])]
prior_jobs = founder_jobs.groupby('person_uuid', as_index=False).size().rename(columns={'size': 'prior_jobs_count'})
founder_exp = founder_team.merge(prior_jobs, on='person_uuid', how='left')
company_founder_exp = founder_exp.groupby('company_uuid', as_index=False)['prior_jobs_count'].mean().rename(columns={'prior_jobs_count': 'founder_avg_prior_jobs'})

# 合并生成最终模型表
model_df = valid_companies[['company_uuid', 'is_success']].copy()
model_df = model_df.merge(features_12m, on='company_uuid', how='left')
model_df = model_df.merge(team_counts, on='company_uuid', how='left')
model_df = model_df.merge(company_founder_exp, on='company_uuid', how='left')

# 填充空值
flag_cols = ['first_year_has_pre_seed', 'first_year_has_seed', 'first_year_has_series_a']
for col in flag_cols:
    if col in model_df.columns:
        model_df[col] = model_df[col].fillna(0)

# ==========================================
# 5) Train & Evaluate
# ==========================================
feature_cols = [
    'first_year_funding_usd', 'first_year_round_count', 'first_year_investor_count',
    'first_year_has_pre_seed', 'first_year_has_seed', 'first_year_has_series_a',
    'founder_count', 'founder_avg_prior_jobs'
]

X = model_df[feature_cols]
y = model_df['is_success']

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.25, random_state=42, stratify=y
)

pipeline = Pipeline([
    ('imputer', SimpleImputer(strategy='median')),
    ('scaler', StandardScaler()),
    ('classifier', RandomForestClassifier(n_estimators=100, class_weight='balanced', max_depth=7, random_state=42))
])

print("Training model...")
pipeline.fit(X_train, y_train)

# 评估
y_prob = pipeline.predict_proba(X_test)[:, 1]
print("\n" + "="*20 + " Dynamic Model Summary " + "="*20)
print(f"Success Rate in Dataset: {y.mean():.2%}")
print(f"ROC-AUC: {roc_auc_score(y_test, y_prob):.4f}")
print("\nFeature Importance:")
importances = pipeline.named_steps['classifier'].feature_importances_
print(pd.DataFrame({'feature': feature_cols, 'importance': importances}).sort_values('importance', ascending=False).to_string(index=False))