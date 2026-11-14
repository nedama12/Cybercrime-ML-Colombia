import os, json
import pandas as pd
from sklearn.model_selection import GroupShuffleSplit

RAW = "data/raw/PhiUSIIL_Phishing_URL_Dataset.csv"
OUT = "data/processed"
os.makedirs(OUT, exist_ok=True)

df = pd.read_csv(RAW)
n0 = len(df)

# 1. Clear label: 1 = phishing, 0 = legitimate
df["is_phishing"] = (df["label"] == 0).astype(int)

# 2. Repeated URLs: do they have contradictory labels?
rep = df[df["URL"].duplicated(keep=False)]
conflict = rep.groupby("URL")["is_phishing"].nunique()
conflict_urls = conflict[conflict > 1].index
print("Rows with repeated URL:", len(rep), "| URLs with contradictory labels:", len(conflict_urls))
df = df[~df["URL"].isin(conflict_urls)]
df = df.drop_duplicates(subset="URL", keep="first")
print("Rows before/after:", n0, "->", len(df))

# 3. Drop columns we will not use
df = df.drop(columns=["FILENAME", "Title", "label"])

# 4. Feature groups
URL_ONLY = ["URLLength", "DomainLength", "IsDomainIP", "TLDLength", "NoOfSubDomain",
            "HasObfuscation", "NoOfObfuscatedChar", "ObfuscationRatio", "NoOfLettersInURL",
            "LetterRatioInURL", "NoOfDegitsInURL", "DegitRatioInURL", "NoOfEqualsInURL",
            "NoOfQMarkInURL", "NoOfAmpersandInURL", "NoOfOtherSpecialCharsInURL",
            "SpacialCharRatioInURL", "IsHTTPS"]
DERIVED = ["URLSimilarityIndex", "CharContinuationRate", "TLDLegitimateProb", "URLCharProb"]
PAGE = [c for c in df.columns
        if c not in URL_ONLY + DERIVED + ["URL", "Domain", "TLD", "is_phishing"]]
print("Features: URL only", len(URL_ONLY), "| derived", len(DERIVED), "| page", len(PAGE))

# 5. Relationship of each feature with the label (for orientation)
num = URL_ONLY + DERIVED + PAGE
corr = df[num].corrwith(df["is_phishing"]).abs().sort_values(ascending=False)
print("\nTop 12 correlations with is_phishing:\n", corr.head(12))
print("\nCorrelation of the 18 URL-only features:\n",
      df[URL_ONLY].corrwith(df["is_phishing"]).abs().sort_values(ascending=False))

# 6. 70 / 15 / 15 split grouped by domain
g1 = GroupShuffleSplit(n_splits=1, test_size=0.30, random_state=42)
idx_train, idx_temp = next(g1.split(df, groups=df["Domain"]))
train, temp = df.iloc[idx_train], df.iloc[idx_temp]
g2 = GroupShuffleSplit(n_splits=1, test_size=0.50, random_state=42)
idx_val, idx_test = next(g2.split(temp, groups=temp["Domain"]))
val, test = temp.iloc[idx_val], temp.iloc[idx_test]
df["split"] = "train"
df.loc[val.index, "split"] = "val"
df.loc[test.index, "split"] = "test"
for name, d in [("train", train), ("val", val), ("test", test)]:
    print(name, len(d), "| % phishing:", round(d["is_phishing"].mean() * 100, 1))
print("Domains shared between train and test:", len(set(train["Domain"]) & set(test["Domain"])))

# 7. Save
df.to_csv(f"{OUT}/phishing_processed.csv", index=False)
with open(f"{OUT}/feature_groups.json", "w", encoding="utf-8") as f:
    json.dump({"url_only": URL_ONLY, "derived": DERIVED, "page": PAGE,
               "target": "is_phishing"}, f, indent=2)
print("\nSaved to:", OUT)
