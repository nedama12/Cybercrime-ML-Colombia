import os
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

df = pd.read_csv("data/processed/delitos_procesado.csv")
os.makedirs("analisis/figuras", exist_ok=True)

ETIQ = {"HURTO_ELECTRONICO": "Hurto electrónico", "ACCESO_ABUSIVO": "Acceso abusivo",
        "DATOS_PERSONALES": "Datos personales", "PHISHING_SUPLANTACION": "Phishing / suplantación",
        "FRAUDE_TRANSFERENCIA": "Fraude por transferencia", "ATAQUE_A_SISTEMAS": "Ataque a sistemas",
        "MALWARE": "Malware"}
COLOR = "#0e9aa7"
FUENTE = "Fuente: datos.gov.co, Delitos Informáticos V1 (10-oct-2026)"

# Sin categorías muy pequeñas o no específicas
d = df[~df["categoria"].isin(["NO_ESPECIFICADO", "EQUIPOS_MOVILES"])].copy()

def guardar(fig, nombre):
    fig.text(0.01, 0.01, FUENTE, fontsize=8, color="gray")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(f"analisis/figuras/{nombre}.png", dpi=150)
    plt.close(fig)

# 1. Procesos por año de denuncia (2026 incompleto en gris)
anual = d.groupby("ano_denuncia")["total_procesos"].sum()
fig, ax = plt.subplots(figsize=(9, 4.5))
ax.bar(anual.index.astype(str), anual.values,
       color=["#bdbdbd" if a == 2026 else COLOR for a in anual.index])
ax.set_title("Procesos por delitos informáticos, por año de denuncia")
ax.set_xlabel("Año de denuncia (2026 incompleto, en gris)")
ax.set_ylabel("Procesos")
plt.xticks(rotation=45)
guardar(fig, "01_procesos_por_anio")

# 2. Procesos por categoría
cat = d.groupby("categoria")["total_procesos"].sum().sort_values()
pct = cat / cat.sum() * 100
fig, ax = plt.subplots(figsize=(9, 4.5))
ax.barh([ETIQ[c] for c in cat.index], cat.values, color=COLOR)
for i, (v, p) in enumerate(zip(cat.values, pct.values)):
    ax.text(v, i, f" {p:.1f}%", va="center")
ax.set_title("Procesos por categoría de ciberdelito")
ax.set_xlabel("Procesos")
ax.set_xlim(0, cat.max() * 1.15)
guardar(fig, "02_procesos_por_categoria")

# 3. Evolución por categoría (sin 2026, escala logarítmica)
t = (d[d["ano_denuncia"] < 2026]
     .pivot_table(index="ano_denuncia", columns="categoria", values="total_procesos",
                  aggfunc="sum", fill_value=0))
t.columns = [ETIQ[c] for c in t.columns]
fig, ax = plt.subplots(figsize=(9, 5))
t.plot(ax=ax, marker="o", logy=True)
ax.set_title("Evolución por categoría (escala logarítmica, sin 2026)")
ax.set_xlabel("Año de denuncia")
ax.set_ylabel("Procesos")
ax.legend(fontsize=8)
guardar(fig, "03_evolucion_por_categoria")

# 4. Top 10 departamentos
dep = (d.groupby("departamento_hecho")["total_procesos"].sum()
       .sort_values(ascending=False).head(10).sort_values())
fig, ax = plt.subplots(figsize=(9, 4.5))
ax.barh(dep.index, dep.values, color=COLOR)
ax.set_title("10 departamentos con más procesos")
ax.set_xlabel("Procesos")
guardar(fig, "04_top_departamentos")

# 5. Top 10 municipios
mun = (d.groupby("municipio_hecho")["total_procesos"].sum()
       .sort_values(ascending=False).head(10).sort_values())
fig, ax = plt.subplots(figsize=(9, 4.5))
ax.barh(mun.index, mun.values, color=COLOR)
ax.set_title("10 municipios con más procesos")
ax.set_xlabel("Procesos")
guardar(fig, "05_top_municipios")

# 6. Proporción de procesos con es_archivo = 1, por categoría
#    (confirmar el significado de ES_ARCHIVO en el diccionario de datos)
d["con_archivo"] = d["total_procesos"] * d["es_archivo"]
arch = (d.groupby("categoria")["con_archivo"].sum()
        / d.groupby("categoria")["total_procesos"].sum() * 100).sort_values()
fig, ax = plt.subplots(figsize=(9, 4.5))
ax.barh([ETIQ[c] for c in arch.index], arch.values, color=COLOR)
ax.set_title("% de procesos con ES_ARCHIVO = 1, por categoría")
ax.set_xlabel("% de procesos")
guardar(fig, "06_es_archivo_por_categoria")

# Tablas resumen (para la página y el informe)
d.pivot_table(index="ano_denuncia", columns="categoria", values="total_procesos",
              aggfunc="sum", fill_value=0).to_csv("data/processed/resumen_anio_categoria.csv")
(d.groupby(["departamento_hecho", "categoria"])["total_procesos"].sum()
 .reset_index().to_csv("data/processed/resumen_departamento_categoria.csv", index=False))

print("Procesos por año de denuncia:\n", anual)
print("\nTop departamentos:\n", dep.sort_values(ascending=False))
print("\nTop municipios:\n", mun.sort_values(ascending=False))
print("\n% con ES_ARCHIVO = 1:\n", arch.round(1))
print("\nGráficos guardados en analisis/figuras")