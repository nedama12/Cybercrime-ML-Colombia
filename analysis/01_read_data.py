import pandas as pd

path = "data/raw/Delitos_Informaticos_V1_20261010.xlsx"

xls = pd.ExcelFile(path)
print("Excel sheets:", xls.sheet_names)

df = pd.read_excel(xls, sheet_name=0, dtype=str)

print("\nRows and columns:", df.shape)
print("\nColumns:", df.columns.tolist())
print("\nFirst 10 rows:")
print(df.head(10).to_string())

print("\nNulls per column:")
print(df.isna().sum())

print("\nExact duplicates:", df.duplicated().sum())

print("\nDistinct values and top 5 most frequent per column:")
for col in df.columns:
    print(f"\n- {col}: {df[col].nunique()} distinct values")
    print(df[col].value_counts().head(5).to_string())
