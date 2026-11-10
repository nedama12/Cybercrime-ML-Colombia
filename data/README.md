# Datos del proyecto

## data/raw (originales, no se modifican)
- Delitos_Informaticos_V1_20261010.xlsx: delitos informáticos (Ley 1273 de 2009), datos.gov.co.
  Fecha tomada del nombre del archivo: 10-oct-2026. Descargado el 10-nov-2026.
  [Confirmar la entidad que lo publica en la ficha del dataset.]
- PhiUSIIL_Phishing_URL_Dataset.csv: NO está en el repositorio (54 MB).
  Descargar de https://archive.ics.uci.edu/dataset/967/phiusiil+phishing+url+website+dataset
  y guardar en data/raw/. Prasad & Chandra. Publicado en 2024. Licencia CC BY 4.0.
- PPED-AreaMun-2018-2042_VP.xlsx: NO está en el repositorio.
  Población municipal por área, 2018-2042 (DANE, proyecciones con base en el Censo 2018,
  publicada el 8-ago-2025). Descargar "Serie municipal de población por área, para el periodo
  2018-2042" de https://www.dane.gov.co/index.php/estadisticas-por-tema/demografia-y-poblacion/proyecciones-de-poblacion
  y guardar en data/raw/.

## data/processed
- delitos_procesado.csv: se genera con analisis/03_limpieza.py
- resumen_anio_categoria.csv y resumen_departamento_categoria.csv: analisis/06_eda_delitos.py
- tasas_departamento_anio.csv y tasas_municipio_anio.csv: procesos por 100.000 habitantes
  (2018-2025), con analisis/08_cruce_poblacion.py
- phishing_procesado.csv: NO está en el repositorio. Se genera con analisis/05_preparar_phishing.py.
  Columna `particion` (train/val/test), dividida por dominio.
- grupos_de_variables.json: variables solo_url, derivadas y pagina.

## Gráficos
- analisis/figuras/: gráficos del análisis exploratorio (01 a 10).

## Cómo reproducir
```
pip install -r requirements-analisis.txt
python analisis/03_limpieza.py
python analisis/05_preparar_phishing.py
python analisis/06_eda_delitos.py
python analisis/08_cruce_poblacion.py
python analisis/09_graficos_tasas.py
```