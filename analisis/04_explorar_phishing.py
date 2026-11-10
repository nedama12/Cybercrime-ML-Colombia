import pandas as pd

ruta = "data/raw/PhiUSIIL_Phishing_URL_Dataset.csv"
df = pd.read_csv(ruta)

print("Filas y columnas:", df.shape)
print("Columnas:", df.columns.tolist())

y = "label" if "label" in df.columns else df.columns[-1]
print("\nColumna objetivo:", y)
print(df[y].value_counts())
print("(En este dataset: 1 = legítima, 0 = phishing)")

print("\nNulos totales:", int(df.isna().sum().sum()))
print("Duplicados exactos:", df.duplicated().sum())
if "URL" in df.columns:
    print("URLs repetidas:", df["URL"].duplicated().sum())
print("\nTipos de datos:")
print(df.dtypes.value_counts())
print("\nPrimeras 5 filas:")
print(df.head().to_string())