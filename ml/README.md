# Entrenar el detector con TUS fotos y videos

Objetivo: un modelo YOLO que reconozca **casco** (`safety_helmet`) y **chaleco** (`reflective_jacket`)
en TU escenario (tu cámara, tu luz, tus compañeros). Las personas se detectan aparte con el modelo
COCO (`yolo26n.pt`); las reglas geométricas deciden si cada casco/chaleco está "puesto" en una persona.

Todos los comandos se ejecutan **desde la raíz del proyecto**, con el entorno virtual activo:
`pip install -r ml/requirements.txt`

```
videos propios ─► extract_frames ─► (prelabel) ─► etiquetar/corregir ─► prepare_dataset ─► train ─► evaluate
 ml/datasets/own/videos   own/frames    own/prelabels    own/labeled        datasets/combined    runs/    output/ml
```

## Por qué se atoró el entrenamiento anterior

10.500 imágenes × 30 épocas en CPU son muchísimas horas. No necesitas todo eso: partes de pesos ya
entrenados y lo que más importa son **tus** imágenes. Tres atajos (combinables):

- `--fraction 0.2`: usa solo el 20 % del conjunto de entrenamiento.
- `--imgsz 512` (o 416): imágenes más pequeñas = mucho más rápido.
- **GPU gratuita**: Google Colab (Entorno de ejecución → GPU T4). Sube la carpeta `ml/` y el dataset, ejecuta los
  mismos comandos con `--device 0` y descarga `best.pt`. Es la opción más cómoda para esto.

Mide antes de lanzar algo largo: `--fraction 0.05 --epochs 1` te dice cuánto tarda una época.
Si ya tienes un entrenamiento a medias, `python -m ml.train --resume runs/ppe/helmet-vest/weights/last.pt` lo retoma.

## Paso 0 — Modelo base (arranque rápido)

Opción A: entrenar poco con el dataset público de Kaggle "Safety Helmet and Reflective Jacket"
(Nirav B. Naik, 2023; licencia reportada Apache 2.0 — verifícala en la fuente y conserva la cita). Descárgalo
con `kaggle datasets download -d niravnaik/safety-helmet-and-reflective-jacket --unzip -p datasets/ppe`:

```bash
python -m ml.train --data datasets/ppe/safety-Helmet-Reflective-Jacket/data.yaml \
    --fraction 0.2 --imgsz 512 --epochs 20 --name base --export models/ppe/base.pt
```

Opción B: descargar un modelo YOLO de EPP ya entrenado (Roboflow Universe, Hugging Face) y guardarlo como
`models/ppe/base.pt`. Debe tener clases de casco y chaleco (`python -m ml.prelabel` lo comprueba).

## Paso 1 — Grabar videos (lo más importante)

Con el celular en el mismo sitio y posición que usarás en la demo (trípode). Nombres sin espacios:
`ml/datasets/own/videos/sesionA-casco-chaleco.mp4`. Graba **varios videos distintos** (≥ 6 ideal), cada uno
de 1–3 min, cubriendo:

- con casco y chaleco · sin casco · sin chaleco · sin nada · con uno solo
- caminando desde la puerta hacia adentro, de frente, de espaldas y de lado
- cerca y lejos de la cámara; 1, 2 y 3 personas a la vez (cruzándose)
- distintas ropas, colores de casco/chaleco, y todos los integrantes del grupo
- si la luz cambia en la demo (ventanas, tarde/noche), también eso

Deja **1–2 videos sin tocar para la prueba final** (el script de dataset los separa por video).

## Paso 2 — Sacar fotogramas

```bash
python -m ml.extract_frames --videos-dir ml/datasets/own/videos --out ml/datasets/own/frames --per-second 2
```
Descarta borrosos y repetidos. Revisa unas cuantas imágenes a ojo. Más de ~1.000 imágenes suele ser
demasiado trabajo de etiquetado; con 300–600 bien variadas se logra mucho.

## Paso 3 — Pre-etiquetar y corregir

```bash
python -m ml.prelabel --model models/ppe/base.pt --images ml/datasets/own/frames --out ml/datasets/own/prelabels
```
Sube imágenes + `.txt` a **Roboflow**, CVAT o Label Studio (importando como formato YOLO, clases en este
orden: `safety_helmet`, `reflective_jacket`), y CORRIGE. Reglas de etiquetado:

- Caja ajustada a **cada casco y cada chaleco visibles**. Si se ve menos de la mitad, no lo etiquetes.
- Una persona **sin** casco: simplemente no hay caja de casco (no etiquetes la cabeza descubierta).
- Las imágenes sin ningún EPP son valiosas (enseñan qué NO es casco/chaleco): inclúyelas.
- Exporta en formato **YOLO** y **sin aumentos** (YOLO ya los aplica al entrenar).

Coloca el resultado en `ml/datasets/own/labeled/` (con carpetas `images/` y `labels/`; también vale la
estructura `train/valid/test` que exporta Roboflow, se vuelve a dividir sola).

## Paso 4 — Armar el dataset

```bash
python -m ml.prepare_dataset --own ml/datasets/own/labeled \
    --public datasets/ppe/safety-Helmet-Reflective-Jacket/data.yaml --public-fraction 0.15 \
    --test-videos sesionC-prueba
python -m ml.check_dataset --data ml/datasets/combined/data.yaml
```
Divide **por video** (nunca el mismo video en train y test) y valida que cada partición tenga ambas clases.
El `test` es solo tuyo. `--public` mezcla una muestra pequeña del público para no "olvidar" lo aprendido.

## Paso 5 — Ajuste fino

```bash
python -m ml.train --data ml/datasets/combined/data.yaml --model models/ppe/base.pt \
    --epochs 40 --freeze 10 --lr0 0.002 --imgsz 640 --name finetune --export models/ppe/best.pt
```

## Paso 6 — Medir y comparar

```bash
python -m ml.evaluate --data ml/datasets/combined/data.yaml --model models/ppe/base.pt  --output output/ml/base.json
python -m ml.evaluate --data ml/datasets/combined/data.yaml --model models/ppe/best.pt  --output output/ml/finetune.json
```
Si `finetune` no mejora sobre `base` en el test, faltan imágenes variadas o hay errores de etiquetado.

## Paso 7 — Prueba real sobre video (lo que de verdad importa)

```bash
cd backend && python tools/run_on_video.py --video ../ml/datasets/own/videos/sesionC-prueba.mp4 \
    --ppe-model ../models/ppe/best.pt --out ../output/sesionC_anotado.mp4
```
Mira el video anotado y los porcentajes. En un video donde TODOS cumplen, `not_detected` debe ser casi 0 %
sostenido: una advertencia falsa exige 30 s seguidos, así que lo grave es una racha larga, no fotogramas sueltos.
Ajusta `vision.confidence`, `min_person_height` y el encuadre de la cámara antes de reentrenar.

## Paso 8 — Activarlo en el sistema

`config/config.yaml` → `vision.enabled: true` (y `vision.ppe_model: models/ppe/best.pt`). Reinicia el backend.
