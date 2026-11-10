# Datos del proyecto

## data/raw (originales, no se modifican)
- Delitos_Informaticos_V1_20261010.xlsx: delitos informáticos (Ley 1273 de 2009), datos.gov.co.
  Fecha tomada del nombre del archivo: 10-oct-2026. Descargado el 10-nov-2026.
  [Confirmar la entidad que lo publica en la ficha del dataset.]
- PhiUSIIL_Phishing_URL_Dataset.csv: NO está en el repositorio (54 MB).
  Descargar de https://archive.ics.uci.edu/dataset/967/phiusiil+phishing+url+website+dataset
  y guardar en data/raw/. Prasad & Chandra. Publicado en 2024. Licencia CC BY 4.0.

## data/processed
- delitos_procesado.csv: se genera con analisis/03_limpieza.py
- phishing_procesado.csv: NO está en el repositorio. Se genera con analisis/05_preparar_phishing.py.
  Columna `particion` (train/val/test), dividida por dominio.
- grupos_de_variables.json: variables solo_url, derivadas y pagina.

## Cómo reproducir
pip install -r requirements-analisis.txt
python analisis/03_limpieza.py
python analisis/05_preparar_phishing.py