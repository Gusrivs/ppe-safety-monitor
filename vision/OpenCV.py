import cv2

# Reemplaza con la IP que te dio la app en tu celular
url = "http://192.168.0.7:8080/video"

cap = cv2.VideoCapture(url)

if not cap.isOpened():
    print("Error: No se pudo abrir la cámara del celular")
    exit()

while True:
    ret, frame = cap.read()
    if not ret:
        print("No se recibe video...")
        break

    # Aquí iría tu modelo de IA para detectar cascos y chalecos
    cv2.imshow("IA - Deteccion de Seguridad", frame)

    # Presiona 'Esc' para salir
    if cv2.waitKey(1) == 27:
        break

cap.release()
cv2.destroyAllWindows()