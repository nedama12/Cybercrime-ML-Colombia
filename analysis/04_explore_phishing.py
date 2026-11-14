import pandas as pd

path = "data/raw/PhiUSIIL_Phishing_URL_Dataset.csv"
df = pd.read_csv(path)

print("Rows and columns:", df.shape)
print("Columns:", df.columns.tolist())

y = "label" if "label" in df.columns else df.columns[-1]
print("\nTarget column:", y)
print(df[y].value_counts())
print("(In this dataset: 1 = legitimate, 0 = phishing)")

print("\nTotal nulls:", int(df.isna().sum().sum()))
print("Exact duplicates:", df.duplicated().sum())
if "URL" in df.columns:
    print("Repeated URLs:", df["URL"].duplicated().sum())
print("\nData types:")
print(df.dtypes.value_counts())
print("\nFirst 5 rows:")
print(df.head().to_string())
