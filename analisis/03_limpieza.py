import os, re, unicodedata
import pandas as pd

RAW = "data/raw/Delitos_Informaticos_V1_20261010.xlsx"
OUT = "data/processed/delitos_procesado.csv"

df = pd.read_excel(RAW, sheet_name="Data", dtype=str)

# 1. Números: mostrar qué valores no son numéricos antes de convertir
for c in ["AÑO_HECHOS", "AÑO_ENTRADA", "AÑO_DENUNCIA", "TOTAL_PROCESOS"]:
    malos = df.loc[pd.to_numeric(df[c], errors="coerce").isna(), c]
    print(c, "- no numéricos:", malos.value_counts().to_dict())
    df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
n0, p0 = len(df), int(df["TOTAL_PROCESOS"].sum())

# 2. Limpiar espacios y convertir "SIN DATO" en nulo
TXT = ["CRIMINALIDAD", "ES_ARCHIVO", "ES_PRECLUSIÓN", "ESTADO", "ETAPA_CASO", "LEY",
       "PAÍS_HECHO", "DEPARTAMENTO_HECHO", "MUNICIPIO_HECHO", "SECCIONAL",
       "DELITO", "GRUPO_DELITO", "CONSUMADO"]
for c in TXT:
    df[c] = df[c].str.strip()
    df[c] = df[c].mask(df[c].str.upper() == "SIN DATO")

# 3. Quitar filas sin ubicación (22 filas)
antes = len(df)
df = df.dropna(subset=["DEPARTAMENTO_HECHO", "MUNICIPIO_HECHO"])
print("Filas eliminadas sin ubicación:", antes - len(df))
print(df["PAÍS_HECHO"].value_counts(dropna=False))

# 4. Eliminar columnas sin información
df = df.drop(columns=["GRUPO_DELITO", "CONSUMADO", "PAÍS_HECHO"])

# 5. Nombres de lugares normalizados (para unir luego con DIVIPOLA)
def norm(t):
    if pd.isna(t):
        return t
    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", " ", t).strip()

df["DEPARTAMENTO_NORM"] = df["DEPARTAMENTO_HECHO"].map(norm)
df["MUNICIPIO_NORM"] = df["MUNICIPIO_HECHO"].map(norm)

# 6. Artículo, agravante y categoría (equivalencia aproximada, validar con el equipo)
df["ARTICULO"] = df["DELITO"].str.extract(r"ART\.?\s*(269[A-J])", expand=False)
df.loc[df["DELITO"].str.contains("ART 105 DE LEY 1453", na=False), "ARTICULO"] = "L1453"
df["ES_AGRAVADO"] = df["DELITO"].str.contains("AGRAVADO", na=False).astype(int)
MAPA = {"269A": "ACCESO_ABUSIVO", "269B": "ATAQUE_A_SISTEMAS", "269C": "ATAQUE_A_SISTEMAS",
        "269D": "ATAQUE_A_SISTEMAS", "269E": "MALWARE", "269F": "DATOS_PERSONALES",
        "269G": "PHISHING_SUPLANTACION", "269I": "HURTO_ELECTRONICO",
        "269J": "FRAUDE_TRANSFERENCIA", "L1453": "EQUIPOS_MOVILES"}
df["CATEGORIA"] = df["ARTICULO"].map(MAPA).fillna("NO_ESPECIFICADO")

# 7. Columnas SI/NO a 0/1
for c in ["CRIMINALIDAD", "ES_ARCHIVO", "ES_PRECLUSIÓN"]:
    df[c] = df[c].map({"SI": 1, "NO": 0})
df["ESTADO"] = df["ESTADO"].map({"ACTIVO": 1, "INACTIVO": 0})

# 8. Marcar el año incompleto
df["ANIO_PARCIAL"] = (df["AÑO_HECHOS"] == 2026).astype(int)

# 9. Nombres de columnas sin tildes ni mayúsculas
df.columns = [norm(c).lower().replace(" ", "_") for c in df.columns]

# 10. Guardar
os.makedirs("data/processed", exist_ok=True)
df.to_csv(OUT, index=False, encoding="utf-8-sig")

print("\nFilas antes/después:", n0, "->", len(df))
print("Procesos antes/después:", p0, "->", int(df["total_procesos"].sum()))
print(pd.DataFrame({
    "filas": df["categoria"].value_counts(),
    "procesos": df.groupby("categoria")["total_procesos"].sum()
}).sort_values("procesos", ascending=False))
print("\nNulos por columna:\n", df.isna().sum())
print("\nTipos de datos:\n", df.dtypes)
print("\nGuardado en:", OUT)