import os, json
import pandas as pd
from sklearn.model_selection import GroupShuffleSplit

RAW = "data/raw/PhiUSIIL_Phishing_URL_Dataset.csv"
OUT = "data/processed"
os.makedirs(OUT, exist_ok=True)

df = pd.read_csv(RAW)
n0 = len(df)

# 1. Etiqueta clara: 1 = phishing, 0 = legítima
df["es_phishing"] = (df["label"] == 0).astype(int)

# 2. URLs repetidas: ¿tienen etiquetas contradictorias?
rep = df[df["URL"].duplicated(keep=False)]
conflicto = rep.groupby("URL")["es_phishing"].nunique()
urls_conflicto = conflicto[conflicto > 1].index
print("Filas con URL repetida:", len(rep), "| URLs con etiquetas contradictorias:", len(urls_conflicto))
df = df[~df["URL"].isin(urls_conflicto)]
df = df.drop_duplicates(subset="URL", keep="first")
print("Filas antes/después:", n0, "->", len(df))

# 3. Quitar columnas que no usaremos
df = df.drop(columns=["FILENAME", "Title", "label"])

# 4. Grupos de variables
SOLO_URL = ["URLLength", "DomainLength", "IsDomainIP", "TLDLength", "NoOfSubDomain",
            "HasObfuscation", "NoOfObfuscatedChar", "ObfuscationRatio", "NoOfLettersInURL",
            "LetterRatioInURL", "NoOfDegitsInURL", "DegitRatioInURL", "NoOfEqualsInURL",
            "NoOfQMarkInURL", "NoOfAmpersandInURL", "NoOfOtherSpecialCharsInURL",
            "SpacialCharRatioInURL", "IsHTTPS"]
DERIVADAS = ["URLSimilarityIndex", "CharContinuationRate", "TLDLegitimateProb", "URLCharProb"]
PAGINA = [c for c in df.columns
          if c not in SOLO_URL + DERIVADAS + ["URL", "Domain", "TLD", "es_phishing"]]
print("Variables: solo URL", len(SOLO_URL), "| derivadas", len(DERIVADAS), "| página", len(PAGINA))

# 5. Relación de cada variable con la etiqueta (para orientarnos)
num = SOLO_URL + DERIVADAS + PAGINA
corr = df[num].corrwith(df["es_phishing"]).abs().sort_values(ascending=False)
print("\nTop 12 correlaciones con es_phishing:\n", corr.head(12))
print("\nCorrelación de las 18 variables de solo URL:\n",
      df[SOLO_URL].corrwith(df["es_phishing"]).abs().sort_values(ascending=False))

# 6. Partición 70 / 15 / 15 con la misma proporción de phishing
g1 = GroupShuffleSplit(n_splits=1, test_size=0.30, random_state=42)
idx_train, idx_temp = next(g1.split(df, groups=df["Domain"]))
train, temp = df.iloc[idx_train], df.iloc[idx_temp]
g2 = GroupShuffleSplit(n_splits=1, test_size=0.50, random_state=42)
idx_val, idx_test = next(g2.split(temp, groups=temp["Domain"]))
val, test = temp.iloc[idx_val], temp.iloc[idx_test]
df["particion"] = "train"
df.loc[val.index, "particion"] = "val"
df.loc[test.index, "particion"] = "test"
for nombre, d in [("train", train), ("val", val), ("test", test)]:
    print(nombre, len(d), "| % phishing:", round(d["es_phishing"].mean() * 100, 1))
print("Dominios compartidos entre train y test:", len(set(train["Domain"]) & set(test["Domain"])))

# 7. Guardar
df.to_csv(f"{OUT}/phishing_procesado.csv", index=False)
with open(f"{OUT}/grupos_de_variables.json", "w", encoding="utf-8") as f:
    json.dump({"solo_url": SOLO_URL, "derivadas": DERIVADAS, "pagina": PAGINA,
               "objetivo": "es_phishing"}, f, indent=2)
print("\nGuardado en:", OUT)