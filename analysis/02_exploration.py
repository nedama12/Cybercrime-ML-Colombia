import pandas as pd

path = "data/raw/Delitos_Informaticos_V1_20261010.xlsx"
df = pd.read_excel(path, sheet_name="Data", dtype=str)

# 1. Convert to numbers
for c in ["AÑO_HECHOS", "AÑO_ENTRADA", "AÑO_DENUNCIA", "TOTAL_PROCESOS"]:
    df[c] = pd.to_numeric(df[c], errors="coerce")

print("Total cases (sum):", df["TOTAL_PROCESOS"].sum())
print(df["TOTAL_PROCESOS"].describe())

# 2. Year ranges and consistency
for c in ["AÑO_HECHOS", "AÑO_ENTRADA", "AÑO_DENUNCIA"]:
    print(c, "min:", df[c].min(), "max:", df[c].max())
print("Offense year after report year:", (df["AÑO_HECHOS"] > df["AÑO_DENUNCIA"]).sum())
print("Report year after entry year:", (df["AÑO_DENUNCIA"] > df["AÑO_ENTRADA"]).sum())

# 3. Disguised missing values
for c in df.columns:
    n = df[c].astype(str).str.upper().str.contains("SIN DATO|NO APLICA|NO REPORTA", na=False).sum()
    if n:
        print("Disguised missing values in", c, ":", n)

# 4. Law 1273 article of each offense
df["ARTICLE"] = df["DELITO"].str.extract(r"ART\.?\s*(269[A-J])", expand=False)
print("\nOffenses without a 269X article:", df["ARTICLE"].isna().sum())
print(df[df["ARTICLE"].isna()]["DELITO"].value_counts().head(10))

# 5. Rows vs cases per article
print(pd.DataFrame({
    "rows": df["ARTICLE"].value_counts(),
    "cases": df.groupby("ARTICLE")["TOTAL_PROCESOS"].sum()
}).sort_values("cases", ascending=False))

# 6. The 68 offenses
print("\n", df["DELITO"].value_counts().to_string())

# 7. Department names
print("\n", sorted(df["DEPARTAMENTO_HECHO"].unique()))

# 8. Repeated rows ignoring TOTAL_PROCESOS
cols = [c for c in df.columns if c not in ["TOTAL_PROCESOS", "ARTICLE"]]
print("\nRepeated rows ignoring TOTAL_PROCESOS:", df.duplicated(subset=cols).sum())
