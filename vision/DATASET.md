# Dataset de casco y chaqueta reflectante

El conjunto de referencia es **Safety Helmet and Reflective Jacket**, de Nirav B. Naik. La ficha consultada describe 10.500 imágenes, cajas para `safety_helmet` y `reflective_jacket`, y licencia Apache 2.0. El conjunto no se incluye en este repositorio; la ficha advierte que quien lo use debe verificar las condiciones de la fuente original.

- Fuente: <https://www.kaggle.com/datasets/niravnaik/safety-helmet-and-reflective-jacket>
- Ficha/estadísticas/licencia reportada: <https://datasetninja.com/safety-helmet-and-reflective-jacket>
- Licencia del repositorio de metadatos: <https://github.com/dataset-ninja/safety-helmet-and-reflective-jacket/blob/main/LICENSE.md>
- Cita: Nirav B. Naik (2023), *Safety Helmet and Reflective Jacket*, Kaggle.

Antes de entrenar, descarga el archivo desde su fuente, conserva la licencia y cita, y ejecuta el preflight `train_ppe.py --data RUTA/data.yaml`. El preflight verifica que el YAML declare ambas clases necesarias. Este conjunto etiqueta objetos de EPP detectados; no proporciona por sí solo una verdad de terreno completa para declarar que una persona no lleva casco o chaleco. Por eso una ausencia de detección se informa como **indeterminada**, no como infracción confirmada.

Las tres imágenes en `assets/` se reservan para revisión cualitativa. Sus marcas gráficas y la falta de anotaciones impiden usarlas como conjunto de evaluación cuantitativa.
