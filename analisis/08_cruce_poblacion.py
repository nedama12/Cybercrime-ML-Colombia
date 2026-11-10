import re, unicodedata
import pandas as pd

POB = "data/raw/PPED-AreaMun-2018-2042_VP.xlsx"
DEL = "data/processed/delitos_procesado.csv"

def norm(t):
    if pd.isna(t):
        return t
    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", " ", t).strip()

# 1. Población municipal: buscar la fila de encabezados y quedarnos con "Total"
raw = pd.read_excel(POB, sheet_name="PobMunicipalxÁrea", header=None, dtype=str)
fila = raw.index[raw[0] == "DP"][0]
pob = raw.iloc[fila + 1:].copy()
pob.columns = raw.iloc[fila].tolist()
pob = pob.rename(columns={"DP": "cod_dpto", "DPNOM": "departamento_pob", "MPIO": "cod_mpio",
                          "DPMP": "municipio_pob", "AÑO": "anio",
                          "ÁREA GEOGRÁFICA": "area", "TOTAL": "poblacion"})
pob = pob[pob["area"] == "Total"].copy()
pob["anio"] = pd.to_numeric(pob["anio"], errors="coerce")
pob["poblacion"] = pd.to_numeric(pob["poblacion"], errors="coerce")
pob = pob.dropna(subset=["anio", "poblacion", "cod_mpio"])
pob["anio"] = pob["anio"].astype(int)
pob["dep_norm"] = pob["departamento_pob"].map(norm)
pob["mun_norm"] = pob["municipio_pob"].map(norm)
print("Población: municipios", pob["cod_mpio"].nunique(), "| años", pob["anio"].min(), "a", pob["anio"].max())
print("Población total 2024:", int(pob[pob["anio"] == 2024]["poblacion"].sum()))
print("Filas repetidas (depto, municipio, año):", pob.duplicated(["dep_norm", "mun_norm", "anio"]).sum())

# 2. Delitos 2018-2025, sin categorías pequeñas
d = pd.read_csv(DEL)
d = d[(d["ano_denuncia"] >= 2018) & (d["ano_denuncia"] <= 2025)]
d = d[~d["categoria"].isin(["NO_ESPECIFICADO", "EQUIPOS_MOVILES"])]
total = d["total_procesos"].sum()
print("\nProcesos 2018-2025 a cruzar:", int(total))

# 3. Departamentos
dep_pob = pob.groupby(["dep_norm", "cod_dpto", "anio"], as_index=False)["poblacion"].sum()
dep = d.groupby(["departamento_norm", "ano_denuncia"], as_index=False)["total_procesos"].sum()
dep = dep.merge(dep_pob, left_on=["departamento_norm", "ano_denuncia"],
                right_on=["dep_norm", "anio"], how="left")
sin = dep[dep["poblacion"].isna()]
print("\nDEPARTAMENTOS sin coincidencia:", sin["departamento_norm"].nunique(),
      "| % de procesos perdidos:", round(sin["total_procesos"].sum() / total * 100, 2))
print(sin.groupby("departamento_norm")["total_procesos"].sum().sort_values(ascending=False).head(10))
dep["tasa_100k"] = dep["total_procesos"] / dep["poblacion"] * 100_000

# 4. Municipios (con segundo intento para nombres distintos)
def clave(t):
    return norm(t).replace(" ", "")

cat = pob[["dep_norm", "mun_norm", "cod_mpio"]].drop_duplicates().copy()
cat["clave"] = cat["mun_norm"].map(clave)

mun = d.groupby(["departamento_norm", "municipio_norm", "ano_denuncia"], as_index=False)["total_procesos"].sum()

# 4a. Primer intento: mismo nombre dentro del mismo departamento
mapa = cat.rename(columns={"dep_norm": "departamento_norm", "mun_norm": "municipio_norm"})[
    ["departamento_norm", "municipio_norm", "cod_mpio"]]
nombres = (d[["departamento_norm", "municipio_norm"]].drop_duplicates()
           .merge(mapa, how="left", on=["departamento_norm", "municipio_norm"]))
usados = set(nombres["cod_mpio"].dropna())
pend = nombres[nombres["cod_mpio"].isna()]

# 4b. Segundo intento: el nombre corto está contenido en el nombre del DANE
auto, dudosos = [], []
for _, r in pend.iterrows():
    c = cat[cat["dep_norm"] == r["departamento_norm"]]
    k = clave(r["municipio_norm"])
    cand = c[c["clave"].map(lambda x: k == x or k in x)]
    libres = cand[~cand["cod_mpio"].isin(usados)]
    if len(libres) == 1:
        auto.append((r["departamento_norm"], r["municipio_norm"],
                     libres.iloc[0]["cod_mpio"], libres.iloc[0]["mun_norm"]))
    else:
        dudosos.append((r["departamento_norm"], r["municipio_norm"], list(cand["mun_norm"])))

if auto:
    a = pd.DataFrame(auto, columns=["departamento_norm", "municipio_norm", "cod_auto", "nombre_dane"])
    print("\nCoincidencias automáticas (revisa que tengan sentido):")
    print(a[["departamento_norm", "municipio_norm", "nombre_dane"]].to_string(index=False))
    nombres = nombres.merge(a[["departamento_norm", "municipio_norm", "cod_auto"]],
                            how="left", on=["departamento_norm", "municipio_norm"])
    nombres["cod_mpio"] = nombres["cod_mpio"].fillna(nombres["cod_auto"])
    nombres = nombres.drop(columns="cod_auto")
if dudosos:
    print("\nSin resolver (revisar a mano):")
    for dep_, mun_, cands in dudosos:
        print(" -", dep_, "|", mun_, "| posibles:", cands)

mun = mun.merge(nombres, how="left", on=["departamento_norm", "municipio_norm"])
mun = mun.merge(pob[["cod_mpio", "anio", "poblacion"]], how="left",
                left_on=["cod_mpio", "ano_denuncia"], right_on=["cod_mpio", "anio"])
sin = mun[mun["poblacion"].isna()]
print("\nMUNICIPIOS que siguen sin población:",
      sin[["departamento_norm", "municipio_norm"]].drop_duplicates().shape[0],
      "| % de procesos perdidos:", round(sin["total_procesos"].sum() / total * 100, 2))
mun["tasa_100k"] = mun["total_procesos"] / mun["poblacion"] * 100_000

# 5. Guardar tablas
cols_dep = ["cod_dpto", "departamento_norm", "ano_denuncia", "total_procesos", "poblacion", "tasa_100k"]
cols_mun = ["cod_mpio", "departamento_norm", "municipio_norm", "ano_denuncia",
            "total_procesos", "poblacion", "tasa_100k"]
dep.dropna(subset=["poblacion"])[cols_dep].to_csv("data/processed/tasas_departamento_anio.csv", index=False)
mun.dropna(subset=["poblacion"])[cols_mun].to_csv("data/processed/tasas_municipio_anio.csv", index=False)

# 6. Vista previa 2024
print("\nTop 10 departamentos por tasa en 2024:")
print(dep[dep["ano_denuncia"] == 2024].sort_values("tasa_100k", ascending=False)
      .head(10)[["departamento_norm", "total_procesos", "poblacion", "tasa_100k"]].round(1).to_string(index=False))
m24 = mun[(mun["ano_denuncia"] == 2024) & (mun["poblacion"] >= 50000)]
print("\nTop 10 municipios (50.000+ habitantes) por tasa en 2024:")
print(m24.sort_values("tasa_100k", ascending=False)
      .head(10)[["municipio_norm", "total_procesos", "poblacion", "tasa_100k"]].round(1).to_string(index=False))