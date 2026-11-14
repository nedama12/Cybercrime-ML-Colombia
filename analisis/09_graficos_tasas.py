import os
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

POB = "data/raw/PPED-AreaMun-2018-2042_VP.xlsx"
COLOR = "#0e9aa7"
FUENTE = "Fuente: datos.gov.co (Delitos Informáticos V1) y DANE (proyecciones de población 2018-2042)"
os.makedirs("analisis/figuras", exist_ok=True)

dep = pd.read_csv("data/processed/tasas_departamento_anio.csv", dtype={"cod_dpto": str})
mun = pd.read_csv("data/processed/tasas_municipio_anio.csv", dtype={"cod_mpio": str})

# Nombres con tildes, tomados del archivo del DANE
raw = pd.read_excel(POB, sheet_name="PobMunicipalxÁrea", header=None, dtype=str)
fila = raw.index[raw[0] == "DP"][0]
nom = raw.iloc[fila + 1:, :4].dropna().drop_duplicates()
nom.columns = ["cod_dpto", "departamento", "cod_mpio", "municipio"]
dep = dep.merge(nom[["cod_dpto", "departamento"]].drop_duplicates(), on="cod_dpto", how="left")
mun = mun.merge(nom[["cod_mpio", "municipio"]].drop_duplicates(), on="cod_mpio", how="left")
print("Filas repetidas (municipio, año):", mun.duplicated(["cod_mpio", "ano_denuncia"]).sum())

def guardar(fig, nombre):
    fig.text(0.01, 0.01, FUENTE, fontsize=8, color="gray")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(f"analisis/figuras/{nombre}.png", dpi=150)
    plt.close(fig)

def etiqueta(t, n):
    return f" {t:.0f}  (n={n:,})".replace(",", ".")

# 7. Tasa nacional por año
nac = dep.groupby("ano_denuncia").agg(procesos=("total_procesos", "sum"), poblacion=("poblacion", "sum"))
nac["tasa"] = nac["procesos"] / nac["poblacion"] * 100_000
fig, ax = plt.subplots(figsize=(9, 4.5))
ax.plot(nac.index, nac["tasa"], marker="o", color=COLOR)
for x, y in zip(nac.index, nac["tasa"]):
    ax.text(x, y + 1.5, f"{y:.0f}", ha="center", fontsize=8)
ax.set_title("Procesos por 100.000 habitantes, Colombia")
ax.set_xlabel("Año de denuncia")
ax.set_ylabel("Procesos por 100.000 hab.")
guardar(fig, "07_tasa_nacional")

# 8. Top 10 departamentos por tasa en 2024
d24 = dep[dep["ano_denuncia"] == 2024].copy()
d24["pos_procesos"] = d24["total_procesos"].rank(ascending=False).astype(int)
d24["pos_tasa"] = d24["tasa_100k"].rank(ascending=False).astype(int)
top = d24.sort_values("tasa_100k", ascending=False).head(10).sort_values("tasa_100k")
fig, ax = plt.subplots(figsize=(9, 5))
ax.barh(top["departamento"], top["tasa_100k"], color=COLOR)
for i, (t, n) in enumerate(zip(top["tasa_100k"], top["total_procesos"])):
    ax.text(t, i, etiqueta(t, n), va="center", fontsize=8)
ax.set_xlim(0, top["tasa_100k"].max() * 1.3)
ax.set_title("10 departamentos con más procesos por 100.000 hab. (2024)")
ax.set_xlabel("Procesos por 100.000 hab.  (n = número de procesos)")
guardar(fig, "08_tasa_departamentos_2024")

# 9. Top 10 municipios (50.000+ habitantes) por tasa en 2024
m24 = mun[(mun["ano_denuncia"] == 2024) & (mun["poblacion"] >= 50000)]
topm = m24.sort_values("tasa_100k", ascending=False).head(10).sort_values("tasa_100k")
fig, ax = plt.subplots(figsize=(9, 5))
ax.barh(topm["municipio"], topm["tasa_100k"], color=COLOR)
for i, (t, n) in enumerate(zip(topm["tasa_100k"], topm["total_procesos"])):
    ax.text(t, i, etiqueta(t, n), va="center", fontsize=8)
ax.set_xlim(0, topm["tasa_100k"].max() * 1.3)
ax.set_title("10 municipios (50.000+ hab.) con más procesos por 100.000 hab. (2024)")
ax.set_xlabel("Procesos por 100.000 hab.  (n = número de procesos)")
guardar(fig, "09_tasa_municipios_2024")

# 10. Evolución de los 5 departamentos con mayor tasa en 2024, frente a Colombia
top5 = d24.sort_values("tasa_100k", ascending=False).head(5)["departamento"].tolist()
fig, ax = plt.subplots(figsize=(9, 5))
for nombre in top5:
    s = dep[dep["departamento"] == nombre].set_index("ano_denuncia")["tasa_100k"]
    ax.plot(s.index, s.values, marker="o", label=nombre)
ax.plot(nac.index, nac["tasa"], color="black", linestyle="--", label="Colombia")
ax.set_title("Procesos por 100.000 hab.: 5 departamentos con mayor tasa en 2024")
ax.set_xlabel("Año de denuncia")
ax.set_ylabel("Procesos por 100.000 hab.")
ax.legend(fontsize=8)
guardar(fig, "10_tasa_top5_departamentos")

print("\nTasa nacional por año:\n", nac.round(1))
print("\nDepartamentos 2024 (posición por procesos vs por tasa):")
print(d24.sort_values("pos_tasa").head(10)[["departamento", "total_procesos", "tasa_100k",
                                             "pos_procesos", "pos_tasa"]].round(1).to_string(index=False))
print("\nMunicipios 2024 con 50.000+ hab.:")
print(m24.sort_values("tasa_100k", ascending=False).head(10)[["municipio", "total_procesos",
                                                              "poblacion", "tasa_100k"]].round(1).to_string(index=False))
print("\nGráficos guardados en analisis/figuras")