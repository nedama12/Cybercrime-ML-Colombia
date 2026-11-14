import os
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

df = pd.read_csv("data/processed/crimes_processed.csv")
os.makedirs("analysis/figures", exist_ok=True)

LABELS = {"ELECTRONIC_THEFT": "Electronic theft", "ABUSIVE_ACCESS": "Abusive access",
          "PERSONAL_DATA": "Personal data", "PHISHING_SPOOFING": "Phishing / spoofing",
          "TRANSFER_FRAUD": "Transfer fraud", "SYSTEM_ATTACK": "System attack",
          "MALWARE": "Malware"}
COLOR = "#0e9aa7"
SOURCE = "Source: datos.gov.co, Delitos Informáticos V1 (Oct 10, 2026)"

# Exclude very small or unspecified categories
d = df[~df["category"].isin(["UNSPECIFIED", "MOBILE_DEVICES"])].copy()

def save(fig, name):
    fig.text(0.01, 0.01, SOURCE, fontsize=8, color="gray")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(f"analysis/figures/{name}.png", dpi=150)
    plt.close(fig)

# 1. Cases by report year (2026 incomplete, in gray)
yearly = d.groupby("report_year")["total_cases"].sum()
fig, ax = plt.subplots(figsize=(9, 4.5))
ax.bar(yearly.index.astype(str), yearly.values,
       color=["#bdbdbd" if y == 2026 else COLOR for y in yearly.index])
ax.set_title("Cybercrime cases by report year")
ax.set_xlabel("Report year (2026 incomplete, in gray)")
ax.set_ylabel("Cases")
plt.xticks(rotation=45)
save(fig, "01_cases_by_year")

# 2. Cases by category
cat = d.groupby("category")["total_cases"].sum().sort_values()
pct = cat / cat.sum() * 100
fig, ax = plt.subplots(figsize=(9, 4.5))
ax.barh([LABELS[c] for c in cat.index], cat.values, color=COLOR)
for i, (v, p) in enumerate(zip(cat.values, pct.values)):
    ax.text(v, i, f" {p:.1f}%", va="center")
ax.set_title("Cases by cybercrime category")
ax.set_xlabel("Cases")
ax.set_xlim(0, cat.max() * 1.15)
save(fig, "02_cases_by_category")

# 3. Trend by category (without 2026, log scale)
t = (d[d["report_year"] < 2026]
     .pivot_table(index="report_year", columns="category", values="total_cases",
                  aggfunc="sum", fill_value=0))
t.columns = [LABELS[c] for c in t.columns]
fig, ax = plt.subplots(figsize=(9, 5))
t.plot(ax=ax, marker="o", logy=True)
ax.set_title("Trend by category (log scale, without 2026)")
ax.set_xlabel("Report year")
ax.set_ylabel("Cases")
ax.legend(fontsize=8)
save(fig, "03_trend_by_category")

# 4. Top 10 departments
dep = (d.groupby("department")["total_cases"].sum()
       .sort_values(ascending=False).head(10).sort_values())
fig, ax = plt.subplots(figsize=(9, 4.5))
ax.barh(dep.index, dep.values, color=COLOR)
ax.set_title("Top 10 departments by number of cases")
ax.set_xlabel("Cases")
save(fig, "04_top_departments")

# 5. Top 10 municipalities
mun = (d.groupby("municipality")["total_cases"].sum()
       .sort_values(ascending=False).head(10).sort_values())
fig, ax = plt.subplots(figsize=(9, 4.5))
ax.barh(mun.index, mun.values, color=COLOR)
ax.set_title("Top 10 municipalities by number of cases")
ax.set_xlabel("Cases")
save(fig, "05_top_municipalities")

# 6. Share of cases with is_archived = 1, by category
#    (confirm the meaning of ES_ARCHIVO in the data dictionary)
d["archived_cases"] = d["total_cases"] * d["is_archived"]
arch = (d.groupby("category")["archived_cases"].sum()
        / d.groupby("category")["total_cases"].sum() * 100).sort_values()
fig, ax = plt.subplots(figsize=(9, 4.5))
ax.barh([LABELS[c] for c in arch.index], arch.values, color=COLOR)
ax.set_title("% of cases with ES_ARCHIVO = 1, by category")
ax.set_xlabel("% of cases")
save(fig, "06_archived_by_category")

# Summary tables (for the website and the report)
d.pivot_table(index="report_year", columns="category", values="total_cases",
              aggfunc="sum", fill_value=0).to_csv("data/processed/summary_year_category.csv")
(d.groupby(["department", "category"])["total_cases"].sum()
 .reset_index().to_csv("data/processed/summary_department_category.csv", index=False))

print("Cases by report year:\n", yearly)
print("\nTop departments:\n", dep.sort_values(ascending=False))
print("\nTop municipalities:\n", mun.sort_values(ascending=False))
print("\n% with ES_ARCHIVO = 1:\n", arch.round(1))
print("\nCharts saved to analysis/figures")
