from flask import Flask, jsonify, render_template_string, request, send_from_directory
import locale, os, time, threading, queue, json, socket
from collections import deque
import paho.mqtt.client as mqtt
import mysql.connector as mysql

app = Flask(__name__)

# ---------- Locale opcional ----------
for loc in ('es_ES.UTF-8', 'es_MX.UTF-8'):
    try:
        locale.setlocale(locale.LC_TIME, loc); break
    except:
        pass
    
# ---------- MySQL ----------
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "",
    "database": "ampelintelligence"
}

def get_db():
    return mysql.connect(**DB_CONFIG)

def get_semaforo_id(node_id):
    try:
        con = get_db()
        cur = con.cursor()
        cur.execute("SELECT ID_Semaforo FROM semaforo WHERE Node_ID = %s", (node_id,))
        row = cur.fetchone()
        cur.close()
        con.close()
        return row[0] if row else None
    except Exception as e:
        print(f"[DB ERROR] get_semaforo_id: {e}")
        return None

def guardar_medicion(node_id, mq_raw, mq_pct, dist_cm, veh_count):
    try:
        id_semaforo = get_semaforo_id(node_id)
        if id_semaforo is None:
            print(f"[DB WARNING] Semáforo '{node_id}' no encontrado en BD")
            return False
        
        con = get_db()
        cur = con.cursor()
        cur.execute("""
            INSERT INTO medicion (ID_Semaforo, MQ_Raw, MQ_Pct, Dist_CM, Veh_Count)
            VALUES (%s, %s, %s, %s, %s)
        """, (id_semaforo, mq_raw, mq_pct, dist_cm, veh_count))
        con.commit()
        cur.close()
        con.close()
        print(f"[DB OK] Guardado: {node_id} → MQ:{mq_pct}% Dist:{dist_cm}cm Veh:{veh_count}")
        return True
    except Exception as e:
        print(f"[DB ERROR] guardar_medicion: {e}")
        return False    

# ---------- MQTT ----------
BROKER_HOST = "broker.mqtt.cool"
BROKER_PORT = 1883

# Tópicos ESP32
TOPIC_SEM1  = "city/sem/sem-001/telemetry"
TOPIC_SEM2  = "city/sem/sem-002/telemetry"

# ---------- Buffers ----------
HIST_MAX = 300
mensajes = deque(maxlen=HIST_MAX)
ultimo_por_topic = {t: None for t in [TOPIC_SEM1, TOPIC_SEM2]}

SERIES_MAX = 120
def clip_0_100(x):
    try:
        return max(0, min(100, int(float(x))))
    except:
        return None

# Estructura para calcular tasa de vehículos
vehicle_state = {
    "sem-001": {
        "last_count": None,
        "last_ts": None,
        "rate_buffer": deque(maxlen=12),
    },
    "sem-002": {
        "last_count": None,
        "last_ts": None,
        "rate_buffer": deque(maxlen=12),
    },
}

series = {
    "sem-001": {"labels": deque(maxlen=SERIES_MAX),
                "mq_pct": deque(maxlen=SERIES_MAX),
                "veh":    deque(maxlen=SERIES_MAX)},
    "sem-002": {"labels": deque(maxlen=SERIES_MAX),
                "mq_pct": deque(maxlen=SERIES_MAX),
                "veh":    deque(maxlen=SERIES_MAX)},
}

# ---------- Cola / MQTT ----------
in_q = queue.Queue(maxsize=1000)

def on_connect(client, userdata, flags, rc, properties=None):
    client.subscribe([(TOPIC_SEM1, 0), (TOPIC_SEM2, 0)])
    print("[MQTT] Conectado y suscrito a semáforos")

def on_message(client, userdata, msg):
    payload = msg.payload.decode(errors="ignore")
    t = time.time()
    try:
        in_q.put_nowait((msg.topic, payload, t))
    except queue.Full:
        try: in_q.get_nowait()
        except: pass
        in_q.put_nowait((msg.topic, payload, t))

def _ipv4(host, port):
    try:
        for fam,_,_,_,sa in socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM):
            return sa[0]
    except Exception:
        pass
    return host

def mqtt_loop():
    cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    cli.on_connect = on_connect
    cli.on_message = on_message
    cli.reconnect_delay_set(min_delay=1, max_delay=30)
    while True:
        try:
            host_v4 = _ipv4(BROKER_HOST, BROKER_PORT)
            cli.connect(host_v4, BROKER_PORT, 60)
            cli.loop_forever()
        except Exception:
            time.sleep(5)

def calculate_vehicle_rate(node_id, current_count, current_ts):
    state = vehicle_state.get(node_id)
    if not state:
        return None
    
    if state["last_count"] is None or state["last_ts"] is None:
        state["last_count"] = current_count
        state["last_ts"] = current_ts
        return None
    
    count_diff = current_count - state["last_count"]
    time_diff = current_ts - state["last_ts"]
    
    if time_diff <= 0 or count_diff < 0:
        state["last_count"] = current_count
        state["last_ts"] = current_ts
        return None
    
    rate_per_min = (count_diff / time_diff) * 60.0
    state["rate_buffer"].append(rate_per_min)
    state["last_count"] = current_count
    state["last_ts"] = current_ts
    
    if len(state["rate_buffer"]) > 0:
        avg_rate = sum(state["rate_buffer"]) / len(state["rate_buffer"])
        return round(avg_rate, 1)
    
    return None

def bridge_worker():
    while True:
        topic, payload, t_epoch = in_q.get()
        marca = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t_epoch))

        # histórico textual
        mensajes.appendleft({"ts": marca, "topic": topic, "msg": payload})
        if topic in ultimo_por_topic:
            ultimo_por_topic[topic] = {"ts": marca, "msg": payload, "topic": topic}

        # Procesar datos de semáforos
        if topic in (TOPIC_SEM1, TOPIC_SEM2):
            try:
                data = json.loads(payload)
                node = data.get("node_id")

                mq_raw = data.get("mq_raw")
                mq_pct = data.get("mq_pct")
                dist_cm = data.get("dist_cm")
                veh_count = data.get("veh_count")
                
                # GUARDAR EN BASE DE DATOS
                guardar_medicion(node, mq_raw, mq_pct, dist_cm, veh_count)

                if node in series:
                    veh_rate = calculate_vehicle_rate(node, veh_count, t_epoch)
                    
                    series[node]["labels"].append(marca)
                    series[node]["mq_pct"].append(clip_0_100(mq_pct))
                    
                    if veh_rate is not None:
                        series[node]["veh"].append(max(0, round(veh_rate)))
                    else:
                        series[node]["veh"].append(None)
                        
            except Exception as e:
                print(f"[ERROR] Procesando mensaje: {e}")

# ---------- Hilos ----------
threading.Thread(target=mqtt_loop,     daemon=True).start()
threading.Thread(target=bridge_worker, daemon=True).start()

# ---------- Static ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

@app.route("/styles.css")
def styles():
    return send_from_directory(BASE_DIR, "styles.css")

@app.route("/imagen.png")
def imagen():
    return send_from_directory(BASE_DIR, "imagen.png")

@app.route("/logotipo.png")
def logotipo():
    return send_from_directory(BASE_DIR, "logotipo.png")

@app.route("/logotipo_mini.png")
def logotipo_mini():
    return send_from_directory(BASE_DIR, "logotipo_mini.png")

# ---------- UI ----------
@app.route("/")
def index():
    html = """<!doctype html>
<html lang="es"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>AmpelIntelligence</title>
<link rel="icon" type="image/png" href="/logotipo_mini.png">
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Rajdhani:wght@300;400;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/styles.css">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1"></script>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="logo-section"><img src="/logotipo.png" class="logo-header" alt="AmpelIntelligence"></div>
    <div class="status"><div class="dot"></div><div class="status-text">Sistema Activo</div></div>
  </div>

  <div class="panel">
    <div class="panel-title">Semáforo 1</div>
    <div class="mini-values">
      <span>Calidad del aire: <b id="s1_mq_val">—</b>%</span>
      <span>Tráfico: <b id="s1_veh_val">—</b> autos/min</span>
    </div>
    <div class="chart-placeholder"><canvas id="chart-sem1-mq"></canvas></div>
    <div class="chart-placeholder"><canvas id="chart-sem1-veh"></canvas></div>
  </div>

  <div class="panel">
    <div class="panel-title">Semáforo 2</div>
    <div class="mini-values">
      <span>Calidad del aire: <b id="s2_mq_val">—</b>%</span>
      <span>Tráfico: <b id="s2_veh_val">—</b> autos/min</span>
    </div>
    <div class="chart-placeholder"><canvas id="chart-sem2-mq"></canvas></div>
    <div class="chart-placeholder"><canvas id="chart-sem2-veh"></canvas></div>
  </div>

  <div class="display">
    <div class="display-header">
      <div class="display-title">Monitoreo en tiempo real</div>
      <div class="msg-count" id="count">0 mensajes</div>
    </div>
    <div class="btn-group">
      <button onclick="toggleUpdate()">⏯ Histórico (iniciar / detener)</button>
      <button class="btn-esp32" onclick="leerUnaVez('{{t1}}')">🟠 Leer Semáforo 1</button>
      <button class="btn-esp32" onclick="leerUnaVez('{{t2}}')">🟠 Leer Semáforo 2</button>
    </div>
    <div id="resultado">⚠️ No se han recibido datos aún. Enciende sensores o usa los botones de lectura puntual.</div>
  </div>
</div>

<script>
let intervaloTexto=null;

const noData={id:'noData',afterDraw(chart){
  const d1=chart.data?.datasets?.[0]?.data||[];
  const d2=chart.data?.datasets?.[1]?.data||[];
  if((d1.filter(v=>v!=null).length + d2.filter(v=>v!=null).length)===0){
    const {ctx,chartArea:{left,top,right,bottom}}=chart;
    ctx.save();ctx.textAlign='center';ctx.textBaseline='middle';
    ctx.fillStyle='rgba(229,231,235,0.7)';ctx.font='14px Rajdhani';
    ctx.fillText('Sin datos',(left+right)/2,(top+bottom)/2);ctx.restore();
  }
}};

function last(arr){return (arr&&arr.length)?arr[arr.length-1]:null;}

function forecastLinear(vals, horizon=6, K=10, cap100=false){
  const y=[];
  for(let i=vals.length-1;i>=0 && y.length<K;i--){
    const v=vals[i]; if(Number.isFinite(v)) y.unshift(v);
  }
  if(y.length<3) return [];
  const n=y.length; let sx=0,sy=0,sxy=0,sx2=0;
  for(let i=0;i<n;i++){ sx+=i; sy+=y[i]; sxy+=i*y[i]; sx2+=i*i; }
  const den = n*sx2 - sx*sx;
  const m = den!==0 ? (n*sxy - sx*sy)/den : 0;
  const b = (sy - m*sx)/n;
  const preds=[];
  for(let k=1;k<=horizon;k++){
    let yhat = m*(n-1+k)+b;
    if (cap100) yhat = Math.max(0, Math.min(100, yhat)); else yhat = Math.max(0, yhat);
    preds.push(Math.round(yhat));
  }
  return preds;
}

function buildForecastSeries(labels, y, cap100){
  const preds = forecastLinear(y, 6, 10, cap100);
  const labelsExt = labels.concat(preds.map((_,i)=>`t+${i+1}`));
  const yActualExt = y.concat(Array(preds.length).fill(null));
  const yPred = new Array(Math.max(labels.length-1,0)).fill(null)
               .concat(y.length? [y[y.length-1]]: [])
               .concat(preds);
  return {labelsExt, yActualExt, yPred};
}

function mkLine(ctx, titleText){
  return new Chart(ctx,{
    type:'line',
    data:{labels:[],datasets:[
      {
        label:titleText,
        data:[],
        tension:.25,
        borderWidth:3,
        borderColor:'#7EF9FF',
        pointRadius:2,
        pointHoverRadius:3,
        pointBackgroundColor:'#7EF9FF',
        spanGaps:true
      },
      {
        label:'Predicción',
        data:[],
        tension:.25,
        borderWidth:3,
        borderDash:[6,6],
        pointRadius:0,
        borderColor:'#FFD24D',
        spanGaps:true
      }
    ]},
    options:{
      responsive:true,maintainAspectRatio:false,
      plugins:{title:{display:true,text:titleText},legend:{display:false}},
      scales:{ y:{beginAtZero:true} }
    },
    plugins:[noData]
  });
}

const c1_mq=mkLine(document.getElementById('chart-sem1-mq').getContext('2d'),'Calidad del aire (%)');
const c1_veh=mkLine(document.getElementById('chart-sem1-veh').getContext('2d'),'Tráfico (autos/min)');
const c2_mq=mkLine(document.getElementById('chart-sem2-mq').getContext('2d'),'Calidad del aire (%)');
const c2_veh=mkLine(document.getElementById('chart-sem2-veh').getContext('2d'),'Tráfico (autos/min)');

function setYRange(chart){
  const a = chart.data.datasets[0].data.filter(v=>Number.isFinite(v));
  const p = chart.data.datasets[1].data.filter(v=>Number.isFinite(v));
  if(!(a.length||p.length)) return;
  const m = Math.max(...a.concat(p));
  chart.options.scales.y.max = Math.ceil(m * 1.15);
}

async function actualizarGraficas(){
  const r=await fetch('/api/series'); const s=await r.json();

  if(s['sem-001']){
    const L=s['sem-001'].labels||[];
    let draft=buildForecastSeries(L, s['sem-001'].mq_pct||[], true);
    c1_mq.data.labels=draft.labelsExt;
    c1_mq.data.datasets[0].data=draft.yActualExt;
    c1_mq.data.datasets[1].data=draft.yPred;
    setYRange(c1_mq); c1_mq.update('none');

    draft=buildForecastSeries(L, s['sem-001'].veh||[], false);
    c1_veh.data.labels=draft.labelsExt;
    c1_veh.data.datasets[0].data=draft.yActualExt;
    c1_veh.data.datasets[1].data=draft.yPred;
    setYRange(c1_veh); c1_veh.update('none');

    const v1_mq=last(s['sem-001'].mq_pct||[]), v1_veh=last(s['sem-001'].veh||[]);
    document.getElementById('s1_mq_val').innerText  = Number.isFinite(v1_mq)? v1_mq : '—';
    document.getElementById('s1_veh_val').innerText = Number.isFinite(v1_veh)? v1_veh : '—';
  }
  if(s['sem-002']){
    const L=s['sem-002'].labels||[];
    let draft=buildForecastSeries(L, s['sem-002'].mq_pct||[], true);
    c2_mq.data.labels=draft.labelsExt;
    c2_mq.data.datasets[0].data=draft.yActualExt;
    c2_mq.data.datasets[1].data=draft.yPred;
    setYRange(c2_mq); c2_mq.update('none');

    draft=buildForecastSeries(L, s['sem-002'].veh||[], false);
    c2_veh.data.labels=draft.labelsExt;
    c2_veh.data.datasets[0].data=draft.yActualExt;
    c2_veh.data.datasets[1].data=draft.yPred;
    setYRange(c2_veh); c2_veh.update('none');

    const v2_mq=last(s['sem-002'].mq_pct||[]), v2_veh=last(s['sem-002'].veh||[]);
    document.getElementById('s2_mq_val').innerText  = Number.isFinite(v2_mq)? v2_mq : '—';
    document.getElementById('s2_veh_val').innerText = Number.isFinite(v2_veh)? v2_veh : '—';
  }
}
actualizarGraficas(); setInterval(actualizarGraficas,3000);

async function obtenerMensajes(){
  const r=await fetch('/api/mqtt'); const d=await r.json();
  const lines=(d.mensajes||[]).map(m=>`<span class="timestamp">${m.ts}</span> — <span class="topic">${m.topic}</span>: ${m.msg}`);
  document.getElementById('count').innerText=`${lines.length} mensajes`;
  document.getElementById('resultado').innerHTML= lines.length ? lines.map(l=>`<div class="msg-line">${l}</div>`).join("") : "⚠️ No se han recibido datos aún. Enciende sensores o usa los botones de lectura puntual.";
}

function toggleUpdate(){
  if(intervaloTexto){ clearInterval(intervaloTexto); intervaloTexto=null;
    document.getElementById('resultado').innerHTML += "<div class='msg-line'>ℹ Histórico detenido</div>";
  } else {
    obtenerMensajes(); intervaloTexto=setInterval(obtenerMensajes,3000);
  }
}

async function leerUnaVez(topic){
  const r=await fetch('/api/peek?topic='+encodeURIComponent(topic)); const d=await r.json();
  if(!d || Object.keys(d).length===0){
    document.getElementById('resultado').innerHTML = "⚠️ No hay lecturas recientes para ese tópico.";
    document.getElementById('count').innerText = '0 mensajes'; return;
  }
  document.getElementById('resultado').innerHTML = `<div class="msg-line"><span class="timestamp">${d.ts||''}</span> — <span class="topic">${d.topic||topic}</span>: ${d.msg}</div>`;
  document.getElementById('count').innerText = '1 mensaje';
}

toggleUpdate();
</script>
</body></html>"""
    return render_template_string(
        html,
        t1=TOPIC_SEM1, t2=TOPIC_SEM2
    )

# ---------- APIs ----------
@app.route("/api/mqtt")
def api_mqtt():
    return jsonify({"mensajes": list(mensajes)})

@app.route("/api/peek")
def api_peek():
    t = request.args.get("topic")
    if t:
        it = ultimo_por_topic.get(t)
        return jsonify(it or {})
    return jsonify({})

@app.route("/api/series")
def api_series():
    return jsonify({
        "sem-001": {k: list(v) for k, v in series["sem-001"].items()},
        "sem-002": {k: list(v) for k, v in series["sem-002"].items()},
    })

# ---------- Main ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)