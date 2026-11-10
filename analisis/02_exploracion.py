import pandas as pd

ruta = "data/raw/Delitos_Informaticos_V1_20261010.xlsx"
df = pd.read_excel(ruta, sheet_name="Data", dtype=str)

# 1. Convertir a número
for c in ["AÑO_HECHOS", "AÑO_ENTRADA", "AÑO_DENUNCIA", "TOTAL_PROCESOS"]:
    df[c] = pd.to_numeric(df[c], errors="coerce")

print("Total de procesos (suma):", df["TOTAL_PROCESOS"].sum())
print(df["TOTAL_PROCESOS"].describe())

# 2. Rango de años y coherencia
for c in ["AÑO_HECHOS", "AÑO_ENTRADA", "AÑO_DENUNCIA"]:
    print(c, "min:", df[c].min(), "max:", df[c].max())
print("Hechos posterior a denuncia:", (df["AÑO_HECHOS"] > df["AÑO_DENUNCIA"]).sum())
print("Denuncia posterior a entrada:", (df["AÑO_DENUNCIA"] > df["AÑO_ENTRADA"]).sum())

# 3. Valores vacíos disfrazados
for c in df.columns:
    n = df[c].astype(str).str.upper().str.contains("SIN DATO|NO APLICA|NO REPORTA", na=False).sum()
    if n:
        print("Vacíos disfrazados en", c, ":", n)

# 4. Artículo de la Ley 1273 de cada delito
df["ARTICULO"] = df["DELITO"].str.extract(r"ART\.?\s*(269[A-J])", expand=False)
print("\nDelitos sin artículo 269X:", df["ARTICULO"].isna().sum())
print(df[df["ARTICULO"].isna()]["DELITO"].value_counts().head(10))

# 5. Filas vs procesos por artículo
print(pd.DataFrame({
    "filas": df["ARTICULO"].value_counts(),
    "procesos": df.groupby("ARTICULO")["TOTAL_PROCESOS"].sum()
}).sort_values("procesos", ascending=False))

# 6. Los 68 delitos
print("\n", df["DELITO"].value_counts().to_string())

# 7. Nombres de departamento
print("\n", sorted(df["DEPARTAMENTO_HECHO"].unique()))

# 8. Repetidos ignorando TOTAL_PROCESOS
cols = [c for c in df.columns if c not in ["TOTAL_PROCESOS", "ARTICULO"]]
print("\nFilas repetidas ignorando TOTAL_PROCESOS:", df.duplicated(subset=cols).sum())