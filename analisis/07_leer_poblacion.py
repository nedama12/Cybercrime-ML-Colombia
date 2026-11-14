import pandas as pd

ruta = "data/raw/PPED-AreaMun-2018-2042_VP.xlsx"

hojas = pd.read_excel(ruta, sheet_name=None, header=None)
print("Hojas del archivo:", list(hojas.keys()))

for nombre, h in list(hojas.items())[:3]:
    print("\n=== Hoja:", nombre, "| filas, columnas:", h.shape)
    print(h.head(15).to_string())