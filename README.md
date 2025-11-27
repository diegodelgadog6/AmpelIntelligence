# AmpelIntelligence

Monitor de **tráfico urbano** y **calidad del aire** basado en IoT. El sistema integra una Raspberry Pi, una ESP32 con sensores y un visor web desarrollado con Flask para mostrar en tiempo real el estado de dos semáforos, sus mediciones ambientales y algunas estadísticas básicas.

Este proyecto fue desarrollado como parte del curso de **IoT** y está pensado para funcionar en un entorno escolar / universitario.

---

## 1. Arquitectura general

- **ESP32**
  - Lee los sensores (por ejemplo MQ‑135, ultrasonido, conteo de vehículos).
  - Publica los datos por MQTT usando un *topic* por nodo de semáforo.

- **Broker MQTT**
  - Recibe los mensajes de los nodos (por ejemplo `broker.mqtt.cool` o un broker local).

- **Raspberry Pi**
  - Ejecuta `app.py` (Flask) y se suscribe a los topics MQTT.
  - Procesa los mensajes entrantes y los guarda en la base de datos MySQL/MariaDB.
  - Sirve el visor web con gráficas en tiempo real e histórico.

- **Base de datos MySQL/MariaDB**
  - Base de datos `ampelintelligence` con tablas:
    - `administrador`
    - `telefono_administrador`
    - `ubicacion`
    - `semaforo`
    - `sensor`
    - `actuador`
    - `medicion`

---

## 2. Tecnologías usadas

- Python 3
- Flask
- paho‑mqtt
- MySQL / MariaDB
- HTML + CSS + JavaScript puro (gráficas con `<canvas>`)

Dependencias Python principales (también en `requirements.txt`):

```txt
Flask==3.0.0
paho-mqtt==1.6.1
mysql-connector-python==8.2.0
```

---

## 3. Estructura del proyecto

```text
ampelintelligence/
├── app.py             # Servidor Flask y lógica MQTT/DB
├── styles.css         # Estilos del visor
├── imagen.png         # Ilustración principal del dashboard
├── logotipo.png       # Logotipo de AmpelIntelligence
├── logotipo_mini.png  # Versión pequeña del logotipo
└── README.md          # Este archivo
```

> Nota: en versiones anteriores se usaban también `Procfile` y `requirements.txt` para desplegar en Railway. Si el proyecto se ejecuta sólo en la Raspberry Pi, esos archivos son opcionales.

---

## 4. Configuración previa

### 4.1. Entorno Python

1. Clonar o copiar el proyecto en la Raspberry Pi o PC.
2. (Opcional pero recomendado) Crear un entorno virtual:

```bash
python -m venv venv
source venv/bin/activate    # Linux / Raspberry Pi
# .venv\Scripts\activate   # Windows
```

3. Instalar dependencias:

```bash
pip install -r requirements.txt
```

Si no se usa `requirements.txt`, instalar manualmente:

```bash
pip install Flask paho-mqtt mysql-connector-python
```

### 4.2. Base de datos MySQL / MariaDB

1. Crear la base de datos (si aún no existe):

```sql
CREATE DATABASE ampelintelligence CHARACTER SET utf8mb4;
```

2. Crear las tablas de acuerdo al diagrama ER (tablas `administrador`, `semaforo`, `medicion`, etc.).
3. Insertar al menos un administrador, por ejemplo:

```sql
INSERT INTO administrador (Nombre, Email, Password)
VALUES ('Diego Alejandro Delgado Gontes', 'diegodelgadog1@gmail.com', 'admin123');
```

4. Revisar y ajustar en `app.py` los datos de conexión a la base de datos:

```python
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "TU_PASSWORD",
    "database": "ampelintelligence",
}
```

### 4.3. Broker MQTT

En la parte superior de `app.py` también se configuran el host, puerto y topics MQTT:

```python
BROKER_HOST = "broker.mqtt.cool"   # o la IP de tu broker
BROKER_PORT = 1883
TOPICS = [
    ("ampel/sem-001", 0),
    ("ampel/sem-002", 0),
]
```

Ajustar estos valores a la configuración real de la ESP32 y del broker.

---

## 5. Ejecución del visor

En la Raspberry Pi (o PC), dentro de la carpeta del proyecto:

```bash
python app.py
```

Por defecto Flask levanta el servidor en `http://0.0.0.0:5000`.

- Si se abre el navegador en **la misma Raspberry**, basta ir a:

  - `http://localhost:5000`

- Si se quiere ver el visor desde otra computadora o celular en la misma red, usar la IP de la Raspberry:

  - `http://<IP_DE_LA_RPI>:5000`

---

## 6. Secciones del visor

> El HTML se genera desde `app.py` usando `render_template_string`.

### 6.1. Dashboard principal

- Vista general de los dos semáforos (`sem-001` y `sem-002`).
- Tarjetas con último valor de:
  - Porcentaje MQ (calidad del aire)
  - Distancia del sensor
  - Conteo de vehículos
- Gráficas de líneas en tiempo real para ambos nodos.
- Línea de tendencia / predicción simple sobrepuesta.
- Botones para cambiar de vista (tiempo real / histórico) y para cada tipo de dato.

### 6.2. Panel de administrador

La aplicación incluye una sección para administración básica de la base de datos:

- Acceso mediante **correo** y **contraseña** que se validan contra la tabla `administrador`.
- Una vez autenticado, el administrador puede ver:
  - Resumen de lecturas almacenadas.
  - Una **terminal SQL sencilla** para ejecutar consultas de solo lectura sobre la base de datos.
  - Un botón para abrir **phpMyAdmin** (si está instalado en el sistema).

> Importante: si se cambia el `Email` o `Password` del administrador en la tabla `administrador`, el inicio de sesión del visor se actualiza automáticamente porque siempre consulta la base de datos.

---

## 7. phpMyAdmin

Para que el botón de phpMyAdmin del visor funcione:

1. Instalar phpMyAdmin junto con MySQL/MariaDB (por ejemplo con Apache o Nginx).
2. Asegurarse de que phpMyAdmin sea accesible en una URL, por ejemplo:

   - `http://localhost/phpmyadmin` en la Raspberry Pi.

3. En `app.py` el botón del panel de administración apunta a esa URL (por ejemplo con un `<a href="http://localhost/phpmyadmin" target="_blank">`).

Mientras esa ruta funcione en la Raspberry Pi, el botón del visor también funcionará.

---

## 8. Consultas de prueba para la terminal SQL

Algunos ejemplos de consultas seguras (solo lectura) para probar la terminal del admin:

```sql
-- Ver todos los administradores
SELECT * FROM administrador;

-- Contar mediciones registradas
SELECT COUNT(*) AS total_mediciones FROM medicion;

-- Ver las últimas 10 mediciones
SELECT *
FROM medicion
ORDER BY Fecha_Hora DESC
LIMIT 10;

-- Conteo de mediciones por semáforo
SELECT ID_Semaforo, COUNT(*) AS mediciones
FROM medicion
GROUP BY ID_Semaforo;

-- Promedio de MQ_Pct por semáforo
SELECT ID_Semaforo, AVG(MQ_Pct) AS mq_promedio
FROM medicion
GROUP BY ID_Semaforo;
```

Puedes añadir más consultas, pero es recomendable que la terminal solo permita `SELECT` en este contexto escolar.

---

## 9. Notas para uso en clase

- El proyecto está pensado para **demostración** de un sistema IoT de monitoreo ambiental y tráfico.
- La estructura del código prioriza la claridad y la integración de componentes (MQTT, Flask, MySQL) sobre la optimización.
- Se puede extender con más sensores, más nodos de semáforo o nuevas gráficas, manteniendo la misma estructura de topics y tablas.

---

## 10. Autores

Proyecto desarrollado por estudiantes de **Ingeniería en Tecnologías Computacionales (ITESM)** como parte del curso de **Internet de las Cosas**.

