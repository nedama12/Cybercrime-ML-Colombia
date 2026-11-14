import os, re, unicodedata
import pandas as pd

RAW = "data/raw/Delitos_Informaticos_V1_20261010.xlsx"
OUT = "data/processed/crimes_processed.csv"

df = pd.read_excel(RAW, sheet_name="Data", dtype=str)

# 1. Numbers: show which values are not numeric before converting
for c in ["AÑO_HECHOS", "AÑO_ENTRADA", "AÑO_DENUNCIA", "TOTAL_PROCESOS"]:
    bad = df.loc[pd.to_numeric(df[c], errors="coerce").isna(), c]
    print(c, "- non-numeric:", bad.value_counts().to_dict())
    df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
n0, p0 = len(df), int(df["TOTAL_PROCESOS"].sum())

# 2. Strip whitespace and turn "SIN DATO" (no data) into null
TXT = ["CRIMINALIDAD", "ES_ARCHIVO", "ES_PRECLUSIÓN", "ESTADO", "ETAPA_CASO", "LEY",
       "PAÍS_HECHO", "DEPARTAMENTO_HECHO", "MUNICIPIO_HECHO", "SECCIONAL",
       "DELITO", "GRUPO_DELITO", "CONSUMADO"]
for c in TXT:
    df[c] = df[c].str.strip()
    df[c] = df[c].mask(df[c].str.upper() == "SIN DATO")

# 3. Drop rows without location (22 rows)
before = len(df)
df = df.dropna(subset=["DEPARTAMENTO_HECHO", "MUNICIPIO_HECHO"])
print("Rows dropped without location:", before - len(df))
print(df["PAÍS_HECHO"].value_counts(dropna=False))

# 4. Drop columns with no information
df = df.drop(columns=["GRUPO_DELITO", "CONSUMADO", "PAÍS_HECHO"])

# 5. Normalized place names (to join later with DIVIPOLA)
def norm(t):
    if pd.isna(t):
        return t
    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", " ", t).strip()

df["DEPARTMENT_NORM"] = df["DEPARTAMENTO_HECHO"].map(norm)
df["MUNICIPALITY_NORM"] = df["MUNICIPIO_HECHO"].map(norm)

# 6. Article, aggravating factor and category (approximate mapping, validate with the team)
df["ARTICLE"] = df["DELITO"].str.extract(r"ART\.?\s*(269[A-J])", expand=False)
df.loc[df["DELITO"].str.contains("ART 105 DE LEY 1453", na=False), "ARTICLE"] = "L1453"
df["IS_AGGRAVATED"] = df["DELITO"].str.contains("AGRAVADO", na=False).astype(int)
CATEGORY_MAP = {"269A": "ABUSIVE_ACCESS", "269B": "SYSTEM_ATTACK", "269C": "SYSTEM_ATTACK",
                "269D": "SYSTEM_ATTACK", "269E": "MALWARE", "269F": "PERSONAL_DATA",
                "269G": "PHISHING_SPOOFING", "269I": "ELECTRONIC_THEFT",
                "269J": "TRANSFER_FRAUD", "L1453": "MOBILE_DEVICES"}
df["CATEGORY"] = df["ARTICLE"].map(CATEGORY_MAP).fillna("UNSPECIFIED")

# 7. YES/NO columns to 1/0 (source values are in Spanish: SI/NO, ACTIVO/INACTIVO)
for c in ["CRIMINALIDAD", "ES_ARCHIVO", "ES_PRECLUSIÓN"]:
    df[c] = df[c].map({"SI": 1, "NO": 0})
df["ESTADO"] = df["ESTADO"].map({"ACTIVO": 1, "INACTIVO": 0})

# 8. Flag the incomplete year
df["PARTIAL_YEAR"] = (df["AÑO_HECHOS"] == 2026).astype(int)

# 9. English column names in lowercase
df = df.rename(columns={
    "CRIMINALIDAD": "criminality", "ES_ARCHIVO": "is_archived", "ES_PRECLUSIÓN": "is_precluded",
    "ESTADO": "is_active", "ETAPA_CASO": "case_stage", "LEY": "law",
    "DEPARTAMENTO_HECHO": "department", "MUNICIPIO_HECHO": "municipality",
    "SECCIONAL": "regional_office", "AÑO_HECHOS": "offense_year", "AÑO_ENTRADA": "entry_year",
    "AÑO_DENUNCIA": "report_year", "DELITO": "offense", "TOTAL_PROCESOS": "total_cases",
})
df.columns = [c.lower() for c in df.columns]

# 10. Save
os.makedirs("data/processed", exist_ok=True)
df.to_csv(OUT, index=False, encoding="utf-8-sig")

print("\nRows before/after:", n0, "->", len(df))
print("Cases before/after:", p0, "->", int(df["total_cases"].sum()))
print(pd.DataFrame({
    "rows": df["category"].value_counts(),
    "cases": df.groupby("category")["total_cases"].sum()
}).sort_values("cases", ascending=False))
print("\nNulls per column:\n", df.isna().sum())
print("\nData types:\n", df.dtypes)
print("\nSaved to:", OUT)
