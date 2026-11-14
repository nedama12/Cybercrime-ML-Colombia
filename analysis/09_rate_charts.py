import os
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

POP = "data/raw/PPED-AreaMun-2018-2042_VP.xlsx"
COLOR = "#0e9aa7"
SOURCE = "Source: datos.gov.co (Delitos Informáticos V1) and DANE (population projections 2018-2042)"
os.makedirs("analysis/figures", exist_ok=True)

dep = pd.read_csv("data/processed/rates_department_year.csv", dtype={"dept_code": str})
mun = pd.read_csv("data/processed/rates_municipality_year.csv", dtype={"mun_code": str})

# Names with accents, taken from the DANE file
raw = pd.read_excel(POP, sheet_name="PobMunicipalxÁrea", header=None, dtype=str)
row = raw.index[raw[0] == "DP"][0]
names = raw.iloc[row + 1:, :4].dropna().drop_duplicates()
names.columns = ["dept_code", "department", "mun_code", "municipality"]
dep = dep.merge(names[["dept_code", "department"]].drop_duplicates(), on="dept_code", how="left")
mun = mun.merge(names[["mun_code", "municipality"]].drop_duplicates(), on="mun_code", how="left")
print("Repeated rows (municipality, year):", mun.duplicated(["mun_code", "report_year"]).sum())

def save(fig, name):
    fig.text(0.01, 0.01, SOURCE, fontsize=8, color="gray")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(f"analysis/figures/{name}.png", dpi=150)
    plt.close(fig)

def label(r, n):
    return f" {r:.0f}  (n={n:,})"

# 7. National rate by year
nat = dep.groupby("report_year").agg(cases=("total_cases", "sum"), population=("population", "sum"))
nat["rate"] = nat["cases"] / nat["population"] * 100_000
fig, ax = plt.subplots(figsize=(9, 4.5))
ax.plot(nat.index, nat["rate"], marker="o", color=COLOR)
for x, y in zip(nat.index, nat["rate"]):
    ax.text(x, y + 1.5, f"{y:.0f}", ha="center", fontsize=8)
ax.set_title("Cases per 100,000 inhabitants, Colombia")
ax.set_xlabel("Report year")
ax.set_ylabel("Cases per 100,000 inhabitants")
save(fig, "07_national_rate")

# 8. Top 10 departments by rate in 2024
d24 = dep[dep["report_year"] == 2024].copy()
d24["rank_cases"] = d24["total_cases"].rank(ascending=False).astype(int)
d24["rank_rate"] = d24["rate_100k"].rank(ascending=False).astype(int)
top = d24.sort_values("rate_100k", ascending=False).head(10).sort_values("rate_100k")
fig, ax = plt.subplots(figsize=(9, 5))
ax.barh(top["department"], top["rate_100k"], color=COLOR)
for i, (r, n) in enumerate(zip(top["rate_100k"], top["total_cases"])):
    ax.text(r, i, label(r, n), va="center", fontsize=8)
ax.set_xlim(0, top["rate_100k"].max() * 1.3)
ax.set_title("Top 10 departments by cases per 100,000 inhabitants (2024)")
ax.set_xlabel("Cases per 100,000 inhabitants  (n = number of cases)")
save(fig, "08_department_rates_2024")

# 9. Top 10 municipalities (50,000+ inhabitants) by rate in 2024
m24 = mun[(mun["report_year"] == 2024) & (mun["population"] >= 50000)]
topm = m24.sort_values("rate_100k", ascending=False).head(10).sort_values("rate_100k")
fig, ax = plt.subplots(figsize=(9, 5))
ax.barh(topm["municipality"], topm["rate_100k"], color=COLOR)
for i, (r, n) in enumerate(zip(topm["rate_100k"], topm["total_cases"])):
    ax.text(r, i, label(r, n), va="center", fontsize=8)
ax.set_xlim(0, topm["rate_100k"].max() * 1.3)
ax.set_title("Top 10 municipalities (50,000+ inhabitants) by cases per 100,000 (2024)")
ax.set_xlabel("Cases per 100,000 inhabitants  (n = number of cases)")
save(fig, "09_municipality_rates_2024")

# 10. Trend of the 5 departments with the highest rate in 2024, vs Colombia
top5 = d24.sort_values("rate_100k", ascending=False).head(5)["department"].tolist()
fig, ax = plt.subplots(figsize=(9, 5))
for name in top5:
    s = dep[dep["department"] == name].set_index("report_year")["rate_100k"]
    ax.plot(s.index, s.values, marker="o", label=name)
ax.plot(nat.index, nat["rate"], color="black", linestyle="--", label="Colombia")
ax.set_title("Cases per 100,000 inhabitants: 5 departments with the highest rate in 2024")
ax.set_xlabel("Report year")
ax.set_ylabel("Cases per 100,000 inhabitants")
ax.legend(fontsize=8)
save(fig, "10_top5_department_rates")

print("\nNational rate by year:\n", nat.round(1))
print("\nDepartments 2024 (rank by cases vs by rate):")
print(d24.sort_values("rank_rate").head(10)[["department", "total_cases", "rate_100k",
                                             "rank_cases", "rank_rate"]].round(1).to_string(index=False))
print("\nMunicipalities 2024 with 50,000+ inhabitants:")
print(m24.sort_values("rate_100k", ascending=False).head(10)[["municipality", "total_cases",
                                                              "population", "rate_100k"]].round(1).to_string(index=False))
