# Módulo de visión EPP

El módulo detecta personas con los pesos YOLO COCO `yolo26n.pt` y casco/chaqueta reflectante con un modelo YOLO ajustado al dataset público. Asocia cada pieza detectada a la región superior (casco) o central (chaleco) de una persona. Solo informa **compliant** cuando ambos elementos se detectan y asocian sin ambigüedad y la persona supera el mínimo de tamaño. Si falta alguna detección, hay ambigüedad o la persona aparece demasiado pequeña, informa **indeterminate**. La ausencia de una caja no demuestra por sí sola que el trabajador incumpla.

No se filtra por color. El conjunto contiene dos clases positivas (`safety_helmet`, `reflective_jacket`) y sus imágenes pueden incluir distintos colores. Se debe revisar la distribución visual y añadir imágenes propias etiquetadas si las condiciones de la cámara del prototipo difieren. Para una predicción más fiable de incumplimiento se requerirán ejemplos locales de casco/chaleco ausente y una etiqueta de visibilidad para no confundir oclusión con ausencia.

## Instalación de dependencias

Desde la raíz del proyecto, se recomienda un entorno virtual:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r vision/requirements.txt
```

La primera ejecución del detector de personas descarga `yolo26n.pt` si no está en la caché de Ultralytics. El modelo EPP se crea en el siguiente paso. Ambos modelos y todos los datos descargados quedan fuera del control de versiones.

## Preparar y comprobar el dataset

Descarga el conjunto de Naik desde Kaggle y descomprímelo bajo `datasets/ppe/` (puede requerir una cuenta y configurar la CLI de Kaggle):

```bash
python3 -m pip install kaggle
kaggle datasets download -d niravnaik/safety-helmet-and-reflective-jacket \
  --unzip -p datasets/ppe
find datasets/ppe -name '*.yaml' -o -name '*.yml'
```

Verifica la licencia en la fuente original y conserva la atribución. El preflight requiere un YAML Ultralytics/YOLO con `names` que incluyan clases equivalentes a casco y chaleco/chaqueta, además de las particiones `train`, `val` y `test` que necesita el flujo de entrenamiento y evaluación.

El archivo descargado suele quedar dentro de una carpeta con nombre propio del dataset. En esta descarga, el YAML está en `datasets/ppe/safety-Helmet-Reflective-Jacket/data.yaml`; el preflight corrige para lectura las rutas `../train/images`, `../valid/images` y `../test/images` del YAML original sin modificar ese archivo. Inspecciona rutas, clases y anotaciones antes de entrenar:

```bash
DATA=datasets/ppe/safety-Helmet-Reflective-Jacket/data.yaml
python3 -m vision.check_dataset --data "$DATA"
```

## Entrenar y evaluar el detector EPP

```bash
DATA=datasets/ppe/safety-Helmet-Reflective-Jacket/data.yaml
python3 -m vision.train_ppe --data "$DATA" --device cpu
mkdir -p models/ppe
cp runs/ppe/helmet-vest/weights/best.pt models/ppe/best.pt
python3 -m vision.evaluate_ppe --data "$DATA" \
  --model models/ppe/best.pt --device cpu
```

El entrenamiento usa transferencia de aprendizaje desde `yolo26n.pt`, `imgsz=640`, 30 épocas, batch 8 y CPU por defecto. Ajusta épocas, batch o dispositivo con los argumentos disponibles si la memoria o el tiempo lo requieren. El evaluador guarda métricas globales y mAP por clase en `output/vision/metrics.json`. El dataset no incluye cajas de persona ni clases negativas; las métricas reflejan detección de EPP, no cumplimiento por persona.

## Probar las imágenes y luego la webcam

```bash
python3 -m vision.ppe_vision images \
  --input assets --output output/vision --ppe-model models/ppe/best.pt --device cpu
```

El programa escribe imágenes anotadas y `results.json` sin tocar los originales. Las tres imágenes actuales son ejemplos cualitativos con marcas gráficas superpuestas y objetos pequeños; no sirven para medir precisión. Después de revisar esa salida, ejecuta el modo webcam en una computadora con cámara:

```bash
python3 -m vision.ppe_vision camera --camera 0 \
  --ppe-model models/ppe/best.pt --device cpu
```

Pulsa `q` para cerrar la ventana. Los argumentos `--confidence` y `--min-person-height` permiten ajustar el umbral y el mínimo de altura de persona en píxeles.

## Pruebas de asociación sin cámara ni modelos

```bash
python3 -m unittest vision.test_ppe_vision
```

Estas pruebas verifican emparejamiento por regiones, ambigüedad, tamaño insuficiente y el estado indeterminado ante detecciones faltantes. No sustituyen la validación real del modelo.
