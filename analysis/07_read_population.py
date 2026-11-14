import pandas as pd

path = "data/raw/PPED-AreaMun-2018-2042_VP.xlsx"

sheets = pd.read_excel(path, sheet_name=None, header=None)
print("File sheets:", list(sheets.keys()))

for name, s in list(sheets.items())[:3]:
    print("\n=== Sheet:", name, "| rows, columns:", s.shape)
    print(s.head(15).to_string())
