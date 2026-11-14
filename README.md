# Cybercrime-ML-Colombia

Plataforma académica para clasificar categorías de incidentes de ciberdelincuencia a partir del dataset procesado del proyecto.

## Ejecutar localmente

```powershell
pip install -r requirements.txt
python app.py
```

Abre `http://127.0.0.1:5000`. Regístrate, inicia sesión, entra a **Predecir** y completa los campos requeridos por el pipeline guardado. La plataforma muestra categoría y probabilidades y guarda la entrada y el resultado en el historial de esa cuenta.

El modelo predice `categoria` usando `criminalidad`, `departamento_hecho`, `municipio_hecho`, `seccional`, `ano_hechos`, `ano_entrada`, `ano_denuncia` y `anio_parcial`. Es un clasificador multiclase; no acepta solicitudes arbitrarias de otros tipos de predicción.

## Datos y artefactos

- Dataset: `data/processed/delitos_procesado.csv`.
- Modelos entrenados: `models/*.joblib`.
- Comparación y evaluación: `reports/`.
- Entrenamiento reproducible: `python -m src.train`.
- Validación de artefactos/predicción: `python -m src.verify_models`.
- Prueba de cuentas e historial: `python -m unittest discover -s tests -v`.

Las cuentas y predicciones se almacenan en `instance/cybercrime.sqlite3`, que está excluido de Git. Las contraseñas se guardan con hash. Para un despliegue HTTPS, configura una `FLASK_SECRET_KEY` privada y estable y `COOKIE_SECURE=1`; la clave generada en desarrollo no debe usarse como secreto de producción.

El modelo actual tiene rendimiento bajo (F1 macro de prueba 0,118); sus predicciones son demostrativas y no deben tratarse como clasificación confiable. Revisa `reports/INFORME_MODEL_ENGINEERING.md` para métricas, limitaciones y contexto del dataset.
