# AmpelIntelligence

Monitor IoT de **tráfico urbano** y **calidad del aire** en tiempo real. Una ESP32 con sensores publica mediciones por MQTT, y un visor web en Flask las muestra en vivo, las guarda en MySQL y ofrece un panel de administración.

Proyecto académico del curso de Internet de las Cosas, Ingeniería en Tecnologías Computacionales, Tecnológico de Monterrey.

## Arquitectura

```text
ESP32 + sensores ──MQTT──▶ Broker MQTT ──▶ Flask (app.py) ──▶ MySQL / MariaDB
                                                │
                                                └──▶ Visor web (tiempo real e histórico)
```

- **ESP32:** lee los sensores (calidad del aire con un sensor MQ, distancia por ultrasonido y conteo de vehículos) y publica un mensaje JSON por semáforo. Su firmware no está en este repositorio.
- **Broker MQTT:** `broker.mqtt.cool` por defecto, o un broker local.
- **Flask (`app.py`):** se suscribe a los tópicos, guarda las mediciones en la base de datos y sirve el visor web.
- **MySQL / MariaDB:** base `ampelintelligence` con las tablas `administrador`, `telefono_administrador`, `ubicacion`, `semaforo`, `sensor`, `actuador` y `medicion`.

## Funcionalidades

**Dashboard**
- Monitoreo de dos semáforos (`sem-001` y `sem-002`).
- Gráficas en tiempo real de calidad del aire y flujo de vehículos, con una línea de predicción.
- Registro histórico de los mensajes recibidos, que se puede pausar y reanudar.
- Cada medición (calidad del aire, distancia y conteo de vehículos) se guarda en la tabla `medicion`.

**Panel de administración**
- Inicio de sesión con correo y contraseña validados contra la tabla `administrador`.
- Resumen de semáforos, sensores, actuadores y mediciones guardadas.
- Terminal SQL que solo acepta consultas `SELECT`, `SHOW` y `DESCRIBE`.
- Acceso directo a phpMyAdmin, si está instalado.

## Tecnologías

Python 3 · Flask · paho-mqtt · MySQL / MariaDB · Gunicorn · HTML, CSS y JavaScript con gráficas en `<canvas>`

## Estructura

```text
app.py              Servidor Flask, cliente MQTT, acceso a la base de datos y HTML del visor
styles.css          Estilos del visor
imagen.png          Ilustración del dashboard
logotipo*.png       Logotipos
requirements.txt    Dependencias de Python
Procfile, render.yaml, nixpacks.toml   Configuración de despliegue con Gunicorn
```

## Puesta en marcha

### 1. Instalar dependencias

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Preparar la base de datos

```sql
CREATE DATABASE ampelintelligence CHARACTER SET utf8mb4;
```

Crea las tablas según el modelo de datos e inserta al menos un administrador:

```sql
INSERT INTO administrador (Nombre, Email, Password)
VALUES ('Administrador', 'admin@ejemplo.com', 'cambia-esta-contraseña');
```

### 3. Configurar la conexión

En `app.py`, ajusta `DB_CONFIG` con los datos de tu servidor MySQL y, si usas otro broker, `BROKER_HOST`, `BROKER_PORT` y los tópicos:

```python
TOPIC_SEM1 = "city/sem/sem-001/telemetry"
TOPIC_SEM2 = "city/sem/sem-002/telemetry"
```

La clave de sesión de Flask se lee de la variable de entorno `FLASK_SECRET_KEY`.

### 4. Ejecutar

```bash
python app.py
```

El visor queda en http://localhost:5000. Desde otro dispositivo de la misma red, usa `http://<IP_DE_LA_RASPBERRY>:5000`.

En producción se ejecuta con Gunicorn:

```bash
gunicorn app:app --bind 0.0.0.0:$PORT
```

## API

| Ruta | Descripción |
| --- | --- |
| `GET /api/mqtt` | Últimos mensajes MQTT recibidos |
| `GET /api/peek?topic=<tópico>` | Último mensaje de un tópico |
| `GET /api/series` | Series de datos de ambos semáforos para las gráficas |

## Consultas de ejemplo para la terminal SQL

```sql
-- Últimas 10 mediciones
SELECT * FROM medicion ORDER BY Fecha_Hora DESC LIMIT 10;

-- Promedio de calidad del aire por semáforo
SELECT ID_Semaforo, AVG(MQ_Pct) AS mq_promedio
FROM medicion
GROUP BY ID_Semaforo;
```

## Equipo

Proyecto en equipo de estudiantes de Ingeniería en Tecnologías Computacionales del Tecnológico de Monterrey. Repositorio mantenido por [Diego Delgado](https://github.com/diegodelgadog6).
