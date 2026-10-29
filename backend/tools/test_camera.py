#!/usr/bin/env python3
"""Prueba rápida de la cámara IP: abre el stream, mide FPS y muestra el video.

    cd backend
    python tools/test_camera.py                       # usa la URL de config/config.yaml
    python tools/test_camera.py --url http://192.168.0.7:8080/video --seconds 60

Criterios sugeridos: >= 15 FPS sostenidos, >= 720p, sin cortes en 10 min. Esc para salir.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402

from app.config import load_settings  # noqa: E402
from app.vision.camera import CameraReader  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=None)
    parser.add_argument("--seconds", type=float, default=30.0)
    parser.add_argument("--no-window", action="store_true", help="No abrir ventana (solo medir)")
    args = parser.parse_args()
    url = args.url or load_settings().camera.url

    camera = CameraReader(url)
    camera.start()
    print(f"Conectando a {url} ...")
    started, last_counter, frames, shape = time.time(), -1, 0, None
    while time.time() - started < args.seconds:
        frame, counter = camera.read()
        if frame is None or counter == last_counter:
            time.sleep(0.005)
            continue
        last_counter, frames, shape = counter, frames + 1, frame.shape
        if not args.no_window:
            cv2.imshow("Prueba de camara (Esc para salir)", frame)
            if cv2.waitKey(1) == 27:
                break
    elapsed = time.time() - started
    camera.stop()
    cv2.destroyAllWindows()
    if not frames:
        print("No llegó ningún fotograma. Revisa la URL, que el celular y la PC estén en la misma red "
              "y que IP Webcam esté en marcha.")
        return 1
    print(f"{frames / elapsed:.1f} FPS entregados, resolución {shape[1]}x{shape[0]}, {elapsed:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
