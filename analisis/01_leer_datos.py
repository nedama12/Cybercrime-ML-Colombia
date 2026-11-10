import pandas as pd

ruta = "data/raw/Delitos_Informaticos_V1_20261010.xlsx"

xls = pd.ExcelFile(ruta)
print("Hojas del Excel:", xls.sheet_names)

df = pd.read_excel(xls, sheet_name=0, dtype=str)

print("\nFilas y columnas:", df.shape)
print("\nColumnas:", df.columns.tolist())
print("\nPrimeras 10 filas:")
print(df.head(10).to_string())

print("\nNulos por columna:")
print(df.isna().sum())

print("\nDuplicados exactos:", df.duplicated().sum())

print("\nValores distintos y los 5 más frecuentes por columna:")
for col in df.columns:
    print(f"\n- {col}: {df[col].nunique()} valores distintos")
    print(df[col].value_counts().head(5).to_string())