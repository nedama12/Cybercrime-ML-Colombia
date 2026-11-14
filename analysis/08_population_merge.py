import re, unicodedata
import pandas as pd

POP = "data/raw/PPED-AreaMun-2018-2042_VP.xlsx"
CRIMES = "data/processed/crimes_processed.csv"

def norm(t):
    if pd.isna(t):
        return t
    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", " ", t).strip()

# 1. Municipal population: find the header row and keep only the "Total" area
raw = pd.read_excel(POP, sheet_name="PobMunicipalxÁrea", header=None, dtype=str)
row = raw.index[raw[0] == "DP"][0]
pop = raw.iloc[row + 1:].copy()
pop.columns = raw.iloc[row].tolist()
pop = pop.rename(columns={"DP": "dept_code", "DPNOM": "department_pop", "MPIO": "mun_code",
                          "DPMP": "municipality_pop", "AÑO": "year",
                          "ÁREA GEOGRÁFICA": "area", "TOTAL": "population"})
pop = pop[pop["area"] == "Total"].copy()
pop["year"] = pd.to_numeric(pop["year"], errors="coerce")
pop["population"] = pd.to_numeric(pop["population"], errors="coerce")
pop = pop.dropna(subset=["year", "population", "mun_code"])
pop["year"] = pop["year"].astype(int)
pop["dep_norm"] = pop["department_pop"].map(norm)
pop["mun_norm"] = pop["municipality_pop"].map(norm)
print("Population: municipalities", pop["mun_code"].nunique(), "| years", pop["year"].min(), "to", pop["year"].max())
print("Total population 2024:", int(pop[pop["year"] == 2024]["population"].sum()))
print("Repeated rows (department, municipality, year):", pop.duplicated(["dep_norm", "mun_norm", "year"]).sum())

# 2. Crimes 2018-2025, without small categories
d = pd.read_csv(CRIMES)
d = d[(d["report_year"] >= 2018) & (d["report_year"] <= 2025)]
d = d[~d["category"].isin(["UNSPECIFIED", "MOBILE_DEVICES"])]
total = d["total_cases"].sum()
print("\nCases 2018-2025 to merge:", int(total))

# 3. Departments
dep_pop = pop.groupby(["dep_norm", "dept_code", "year"], as_index=False)["population"].sum()
dep = d.groupby(["department_norm", "report_year"], as_index=False)["total_cases"].sum()
dep = dep.merge(dep_pop, left_on=["department_norm", "report_year"],
                right_on=["dep_norm", "year"], how="left")
missing = dep[dep["population"].isna()]
print("\nDEPARTMENTS without a match:", missing["department_norm"].nunique(),
      "| % of cases lost:", round(missing["total_cases"].sum() / total * 100, 2))
print(missing.groupby("department_norm")["total_cases"].sum().sort_values(ascending=False).head(10))
dep["rate_100k"] = dep["total_cases"] / dep["population"] * 100_000

# 4. Municipalities (with a second attempt for different names)
def key(t):
    return norm(t).replace(" ", "")

cat = pop[["dep_norm", "mun_norm", "mun_code"]].drop_duplicates().copy()
cat["key"] = cat["mun_norm"].map(key)

mun = d.groupby(["department_norm", "municipality_norm", "report_year"], as_index=False)["total_cases"].sum()

# 4a. First attempt: same name within the same department
mapping = cat.rename(columns={"dep_norm": "department_norm", "mun_norm": "municipality_norm"})[
    ["department_norm", "municipality_norm", "mun_code"]]
names = (d[["department_norm", "municipality_norm"]].drop_duplicates()
         .merge(mapping, how="left", on=["department_norm", "municipality_norm"]))
used = set(names["mun_code"].dropna())
pending = names[names["mun_code"].isna()]

# 4b. Second attempt: the short name is contained in the DANE name
auto, doubtful = [], []
for _, r in pending.iterrows():
    c = cat[cat["dep_norm"] == r["department_norm"]]
    k = key(r["municipality_norm"])
    cand = c[c["key"].map(lambda x: k == x or k in x)]
    free = cand[~cand["mun_code"].isin(used)]
    if len(free) == 1:
        auto.append((r["department_norm"], r["municipality_norm"],
                     free.iloc[0]["mun_code"], free.iloc[0]["mun_norm"]))
    else:
        doubtful.append((r["department_norm"], r["municipality_norm"], list(cand["mun_norm"])))

if auto:
    a = pd.DataFrame(auto, columns=["department_norm", "municipality_norm", "auto_code", "dane_name"])
    print("\nAutomatic matches (check that they make sense):")
    print(a[["department_norm", "municipality_norm", "dane_name"]].to_string(index=False))
    names = names.merge(a[["department_norm", "municipality_norm", "auto_code"]],
                        how="left", on=["department_norm", "municipality_norm"])
    names["mun_code"] = names["mun_code"].fillna(names["auto_code"])
    names = names.drop(columns="auto_code")
if doubtful:
    print("\nUnresolved (review manually):")
    for dep_, mun_, cands in doubtful:
        print(" -", dep_, "|", mun_, "| candidates:", cands)

mun = mun.merge(names, how="left", on=["department_norm", "municipality_norm"])
mun = mun.merge(pop[["mun_code", "year", "population"]], how="left",
                left_on=["mun_code", "report_year"], right_on=["mun_code", "year"])
missing = mun[mun["population"].isna()]
print("\nMUNICIPALITIES still without population:",
      missing[["department_norm", "municipality_norm"]].drop_duplicates().shape[0],
      "| % of cases lost:", round(missing["total_cases"].sum() / total * 100, 2))
mun["rate_100k"] = mun["total_cases"] / mun["population"] * 100_000

# 5. Save tables
cols_dep = ["dept_code", "department_norm", "report_year", "total_cases", "population", "rate_100k"]
cols_mun = ["mun_code", "department_norm", "municipality_norm", "report_year",
            "total_cases", "population", "rate_100k"]
dep.dropna(subset=["population"])[cols_dep].to_csv("data/processed/rates_department_year.csv", index=False)
mun.dropna(subset=["population"])[cols_mun].to_csv("data/processed/rates_municipality_year.csv", index=False)

# 6. 2024 preview
print("\nTop 10 departments by rate in 2024:")
print(dep[dep["report_year"] == 2024].sort_values("rate_100k", ascending=False)
      .head(10)[["department_norm", "total_cases", "population", "rate_100k"]].round(1).to_string(index=False))
m24 = mun[(mun["report_year"] == 2024) & (mun["population"] >= 50000)]
print("\nTop 10 municipalities (50,000+ inhabitants) by rate in 2024:")
print(m24.sort_values("rate_100k", ascending=False)
      .head(10)[["municipality_norm", "total_cases", "population", "rate_100k"]].round(1).to_string(index=False))
