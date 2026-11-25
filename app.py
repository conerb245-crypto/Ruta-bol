import os
import math
import heapq
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st
import folium
from streamlit_folium import st_folium

# ------------------------------------------------------------
# RUTA-BOL | Interfaz de navegación y motor inicial de rutas
# ------------------------------------------------------------
ROOT = Path(__file__).parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

st.set_page_config(
    page_title="RUTA-BOL | Tu ciudad, tus rutas",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
[data-testid="stAppViewContainer"] { background: #f5f7f6; }
[data-testid="stHeader"] { background: rgba(245,247,246,.92); }
.block-container { max-width: 1450px; padding-top: 1rem; padding-bottom: 2rem; }
.rb-brand { display:flex; align-items:center; gap:12px; margin:0 0 2px 0; }
.rb-mark { width:42px; height:42px; border-radius:14px; display:flex; align-items:center; justify-content:center; background:#126b4b; color:white; font-size:22px; }
.rb-name { font-size:25px; line-height:1.05; font-weight:800; color:#12352a; letter-spacing:-.8px; }
.rb-tag { color:#718078; font-size:12px; margin-top:4px; }
.rb-title { font-size:28px; font-weight:800; color:#16392e; letter-spacing:-.8px; margin:8px 0 0 0; }
.rb-subtitle { color:#728078; font-size:14px; margin-bottom:14px; }
.rb-section { font-size:13px; font-weight:700; color:#456156; text-transform:uppercase; letter-spacing:.7px; margin:8px 0 7px 0; }
.rb-result { background:white; border:1px solid #e3eae6; border-radius:16px; padding:14px 16px; margin:8px 0; }
.rb-route-name { font-weight:800; color:#173c30; font-size:16px; }
.rb-muted { color:#77847e; font-size:12px; }
.rb-metric { color:#183b30; font-size:20px; font-weight:800; }
.rb-pill { display:inline-block; background:#e9f4ee; color:#176b4c; border-radius:999px; padding:5px 10px; font-size:11px; font-weight:700; }
div.stButton > button[kind="primary"] { background:#126b4b; border:0; border-radius:13px; min-height:46px; font-weight:700; }
div.stButton > button[kind="secondary"] { border-radius:12px; }
div[data-testid="stTextInput"] input { border-radius:12px; }
div[data-testid="stSelectbox"] div[data-baseweb="select"] > div { border-radius:12px; }
div[data-testid="stRadio"] > div { gap:8px; }
div[data-testid="stRadio"] label { background:white; border:1px solid #e1e9e4; border-radius:12px; padding:8px 12px; }
#MainMenu, footer { visibility:hidden; }
</style>
""", unsafe_allow_html=True)

def read_csv(name, columns=None):
    p = DATA / name
    if p.exists():
        try:
            return pd.read_csv(p)
        except Exception:
            pass
    return pd.DataFrame(columns=columns or [])

ROUTE_COLUMNS = [
    "route_id","municipio","modalidad","operador","nombre_ruta",
    "orden_parada","parada","latitud","longitud","sentido",
    "minutos_desde_anterior","fuente","fecha_verificacion","estado"
]
PLACE_COLUMNS = [
    "place_id","tipo","nombre","municipio","direccion",
    "latitud","longitud","estado","fecha_registro"
]
route_df = read_csv("rutas_y_paradas.csv", ROUTE_COLUMNS)
places_df = read_csv("lugares.csv", PLACE_COLUMNS)
fares_df = read_csv("tarifas_referencia.csv")

def clean_text(v):
    return str(v).strip() if pd.notna(v) else ""

def valid_coord(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
        return -90 <= lat <= 90 and -180 <= lon <= 180
    except Exception:
        return False

def geocode(query):
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query + ", La Paz, Bolivia", "format": "jsonv2", "limit": 1},
            headers={"User-Agent": "RUTA-BOL/2.0 contact: app-user"},
            timeout=12,
        )
        r.raise_for_status()
        items = r.json()
        if items:
            return float(items[0]["lat"]), float(items[0]["lon"]), items[0].get("display_name","")
    except Exception:
        return None
    return None

def nearest_node(graph, lat, lon):
    best, best_d = None, float("inf")
    for node, info in graph["nodes"].items():
        d = haversine(lat, lon, info["lat"], info["lon"])
        if d < best_d:
            best, best_d = node, d
    return best, best_d

def haversine(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2-lat1)
    dl = math.radians(lon2-lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.asin(math.sqrt(a))

def build_graph(df):
    graph = {"nodes": {}, "adj": {}}
    if df.empty:
        return graph
    work = df.copy()
    required = {"parada","latitud","longitud","route_id","orden_parada"}
    if not required.issubset(work.columns):
        return graph
    work["latitud"] = pd.to_numeric(work["latitud"], errors="coerce")
    work["longitud"] = pd.to_numeric(work["longitud"], errors="coerce")
    work["orden_parada"] = pd.to_numeric(work["orden_parada"], errors="coerce")
    if "estado" in work.columns:
        work = work[work["estado"].astype(str).str.lower().isin(["verificada","verificado","aprobada","aprobado","activa","activo"])]
    work = work.dropna(subset=["latitud","longitud","orden_parada"])
    work = work[work.apply(lambda x: valid_coord(x.latitud, x.longitud), axis=1)]
    for _, row in work.iterrows():
        node = f'{round(float(row.latitud),6)}|{round(float(row.longitud),6)}'
        graph["nodes"][node] = {
            "name": clean_text(row.parada),
            "lat": float(row.latitud),
            "lon": float(row.longitud),
            "municipio": clean_text(row.get("municipio","")),
        }
        graph["adj"].setdefault(node, [])
    group_cols = ["route_id"]
    if "sentido" in work.columns:
        group_cols.append("sentido")
    for _, group in work.groupby(group_cols, dropna=False):
        group = group.sort_values("orden_parada")
        rows = list(group.iterrows())
        for i in range(1, len(rows)):
            prev, cur = rows[i-1][1], rows[i][1]
            a = f'{round(float(prev.latitud),6)}|{round(float(prev.longitud),6)}'
            b = f'{round(float(cur.latitud),6)}|{round(float(cur.longitud),6)}'
            if a == b:
                continue
            mins = pd.to_numeric(cur.get("minutos_desde_anterior", 8), errors="coerce")
            mins = float(mins) if pd.notna(mins) and float(mins) > 0 else 8.0
            route_name = clean_text(cur.get("nombre_ruta","")) or clean_text(cur.get("route_id",""))
            graph["adj"][a].append((b, mins, route_name))
            graph["adj"][b].append((a, mins, route_name))
    return graph

def dijkstra(graph, start, end, banned_edge=None):
    adj = graph["adj"]
    dist = {start: 0.0}
    prev = {}
    heap = [(0.0, start)]
    while heap:
        cost, node = heapq.heappop(heap)
        if cost != dist.get(node):
            continue
        if node == end:
            break
        for nxt, weight, route in adj.get(node, []):
            if banned_edge and ((node,nxt) == banned_edge or (nxt,node) == banned_edge):
                continue
            new = cost + weight
            if new < dist.get(nxt, float("inf")):
                dist[nxt] = new
                prev[nxt] = (node, route)
                heapq.heappush(heap, (new, nxt))
    if end not in dist:
        return None
    nodes, routes = [end], []
    cur = end
    while cur != start:
        parent, route = prev[cur]
        routes.append(route)
        nodes.append(parent)
        cur = parent
    nodes.reverse()
    routes.reverse()
    return {"nodes":nodes, "minutes":dist[end], "routes":routes}

def alternative_paths(graph, start, end, limit=3):
    first = dijkstra(graph, start, end)
    if not first:
        return []
    paths = [first]
    candidates = []
    seen = {tuple(first["nodes"])}
    for i in range(len(first["nodes"])-1):
        banned = (first["nodes"][i], first["nodes"][i+1])
        candidate = dijkstra(graph, start, end, banned_edge=banned)
        if candidate and tuple(candidate["nodes"]) not in seen:
            seen.add(tuple(candidate["nodes"]))
            candidates.append(candidate)
    candidates.sort(key=lambda x:x["minutes"])
    paths.extend(candidates[:limit-1])
    return paths

def estimate_fare():
    # Tarifa estimada solo si existe una columna reconocible en el CSV.
    if fares_df.empty:
        return None
    for col in ["tarifa_bs","monto_bs","precio_bs","monto","tarifa","precio"]:
        if col in fares_df.columns:
            vals = pd.to_numeric(fares_df[col].astype(str).str.replace("Bs","",regex=False).str.replace(",",".",regex=False), errors="coerce").dropna()
            if not vals.empty:
                return float(vals.median())
    return None

def save_contribution(record):
    # Supabase es el almacenamiento compartido y persistente recomendado.
    try:
        url = st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL")
        key = st.secrets.get("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_ANON_KEY")
        if url and key:
            table = "aportes"
            resp = requests.post(
                f"{url.rstrip('/')}/rest/v1/{table}",
                headers={"apikey":key, "Authorization":f"Bearer {key}", "Content-Type":"application/json", "Prefer":"return=minimal"},
                json=record, timeout=15
            )
            resp.raise_for_status()
            return True, "Aporte enviado."
    except Exception as e:
        return False, f"No se pudo guardar en la base compartida: {e}"
    # Respaldo local: útil para pruebas, no compartido entre despliegues.
    p = DATA / "aportes_pendientes.csv"
    try:
        old = pd.read_csv(p) if p.exists() else pd.DataFrame()
        pd.concat([old, pd.DataFrame([record])], ignore_index=True).to_csv(p, index=False)
        return True, "Aporte guardado en este despliegue."
    except Exception as e:
        return False, f"No se pudo guardar el aporte: {e}"

# Header
st.markdown("""
<div class="rb-brand">
  <div class="rb-mark">⌖</div>
  <div><div class="rb-name">RUTA-BOL</div><div class="rb-tag">TU CIUDAD, TUS RUTAS</div></div>
</div>
""", unsafe_allow_html=True)
st.markdown('<div class="rb-title">¿A dónde quieres llegar?</div>', unsafe_allow_html=True)
st.markdown('<div class="rb-subtitle">Encuentra tu camino por La Paz y El Alto.</div>', unsafe_allow_html=True)

# Search controls
c1, c2 = st.columns([1,1], gap="medium")
with c1:
    origin_text = st.text_input("PUNTO DE PARTIDA", placeholder="Mi ubicación, hospital, zona o lugar", key="origin")
with c2:
    destination_text = st.text_input("DESTINO", placeholder="¿A dónde quieres ir?", key="destination")

mode = st.radio(
    "TIPO DE RECORRIDO",
    ["Transporte público", "Automóvil", "A pie", "Bicicleta"],
    horizontal=True,
    label_visibility="visible",
)

col_search, col_gps, col_clear = st.columns([1.5,1,1])
with col_search:
    search_clicked = st.button("⌕  BUSCAR RUTAS", type="primary", use_container_width=True)
with col_gps:
    gps_clicked = st.button("◎  Usar mi ubicación", use_container_width=True)
with col_clear:
    clear_clicked = st.button("Limpiar", use_container_width=True)

if clear_clicked:
    st.session_state.pop("last_result", None)
    st.rerun()

if gps_clicked:
    st.info("Permite el acceso a tu ubicación en el navegador y vuelve a pulsar el botón. También puedes escribir tu punto de partida.")

graph = build_graph(route_df)
map_center = [ -16.5, -68.15 ]
if not places_df.empty and {"latitud","longitud"}.issubset(places_df.columns):
    coords = places_df.dropna(subset=["latitud","longitud"])
    if not coords.empty:
        map_center = [float(coords.iloc[0]["latitud"]), float(coords.iloc[0]["longitud"])]

result = st.session_state.get("last_result")
if search_clicked:
    if not origin_text.strip() or not destination_text.strip():
        st.warning("Escribe un punto de partida y un destino.")
    else:
        with st.spinner("Buscando recorridos disponibles..."):
            o = geocode(origin_text)
            d = geocode(destination_text)
            if not o or not d:
                st.warning("No encontramos uno de los lugares. Prueba con el nombre de una zona, hospital o referencia más específica.")
                result = None
            elif mode == "Transporte público":
                if not graph["nodes"]:
                    st.info("Todavía no hay recorridos verificados disponibles para esta búsqueda.")
                    result = {"origin":o,"destination":d,"paths":[],"mode":mode}
                else:
                    start, ds = nearest_node(graph, o[0], o[1])
                    end, de = nearest_node(graph, d[0], d[1])
                    if ds > 4 or de > 4:
                        st.info("Aún no hay paradas verificadas suficientemente cerca del origen o destino.")
                        result = {"origin":o,"destination":d,"paths":[],"mode":mode}
                    else:
                        paths = alternative_paths(graph, start, end, 3)
                        result = {"origin":o,"destination":d,"paths":paths,"mode":mode,"start":start,"end":end}
            else:
                # OSRM entrega estimaciones de carretera para automóvil, caminata y bicicleta
                profile = {"Automóvil":"driving","A pie":"foot","Bicicleta":"cycling"}[mode]
                try:
                    url = f"https://router.project-osrm.org/route/v1/{profile}/{o[1]},{o[0]};{d[1]},{d[0]}"
                    rr = requests.get(url, params={"overview":"full","geometries":"geojson","alternatives":"true"}, timeout=20)
                    rr.raise_for_status()
                    routes = rr.json().get("routes",[])
                    result = {"origin":o,"destination":d,"paths":routes[:3],"mode":mode,"profile":profile}
                except Exception:
                    st.warning("No se pudo calcular el recorrido en este momento. Inténtalo nuevamente.")
                    result = None
        st.session_state["last_result"] = result

result = st.session_state.get("last_result")
# Map
m = folium.Map(location=map_center, zoom_start=12, tiles="OpenStreetMap", control_scale=True)
# Registered places
if not places_df.empty and {"nombre","latitud","longitud"}.issubset(places_df.columns):
    for _, row in places_df.iterrows():
        if valid_coord(row.get("latitud"), row.get("longitud")):
            folium.Marker(
                [float(row["latitud"]),float(row["longitud"])],
                tooltip=clean_text(row.get("nombre","Lugar")),
                popup=clean_text(row.get("tipo","Lugar")),
                icon=folium.Icon(color="green" if "hospital" not in clean_text(row.get("tipo","")).lower() else "red", icon="info-sign")
            ).add_to(m)

if result and result.get("origin") and result.get("destination"):
    o, d = result["origin"], result["destination"]
    folium.Marker([o[0],o[1]], tooltip="Origen", icon=folium.Icon(color="green", icon="play")).add_to(m)
    folium.Marker([d[0],d[1]], tooltip="Destino", icon=folium.Icon(color="red", icon="flag")).add_to(m)
    if result["mode"] == "Transporte público":
        for i, path in enumerate(result.get("paths",[])):
            pts = [[graph["nodes"][n]["lat"],graph["nodes"][n]["lon"]] for n in path["nodes"]]
            folium.PolyLine(pts, color=["#126b4b","#e49b32","#4e79c7"][i%3], weight=6 if i==0 else 4, opacity=.9, tooltip=f"Alternativa {i+1}").add_to(m)
            for n in path["nodes"]:
                inf = graph["nodes"][n]
                folium.CircleMarker([inf["lat"],inf["lon"]], radius=4, color="#126b4b", fill=True, tooltip=inf["name"]).add_to(m)
    else:
        for i, path in enumerate(result.get("paths",[])):
            coords = path.get("geometry",{}).get("coordinates",[])
            if coords:
                pts = [[p[1],p[0]] for p in coords]
                folium.PolyLine(pts, color=["#126b4b","#e49b32","#4e79c7"][i%3], weight=6 if i==0 else 4, opacity=.9).add_to(m)

st.markdown('<div class="rb-section">Mapa de navegación</div>', unsafe_allow_html=True)
st_folium(m, height=470, width=None, returned_objects=[], use_container_width=True)

# Results
if result:
    st.markdown('<div class="rb-section">Rutas para tu viaje</div>', unsafe_allow_html=True)
    paths = result.get("paths",[])
    if not paths:
        st.caption("No hay alternativas disponibles para este recorrido todavía.")
    elif result["mode"] == "Transporte público":
        fare = estimate_fare()
        for i, path in enumerate(paths):
            names = [graph["nodes"][n]["name"] for n in path["nodes"]]
            distance = sum(haversine(graph["nodes"][a]["lat"],graph["nodes"][a]["lon"],graph["nodes"][b]["lat"],graph["nodes"][b]["lon"]) for a,b in zip(path["nodes"],path["nodes"][1:]))
            unique_routes = list(dict.fromkeys([r for r in path["routes"] if r]))
            st.markdown(f"""
            <div class="rb-result">
              <div style="display:flex;justify-content:space-between;align-items:center;">
                <div class="rb-route-name">Alternativa {i+1}</div>
                <span class="rb-pill">{'Recomendada' if i==0 else 'Otra opción'}</span>
              </div>
              <div style="display:flex;gap:26px;margin-top:12px;flex-wrap:wrap;">
                <div><div class="rb-metric">{round(path['minutes'])} min</div><div class="rb-muted">Tiempo estimado</div></div>
                <div><div class="rb-metric">{f'Bs {fare:.2f}' if fare is not None else 'Por confirmar'}</div><div class="rb-muted">Pasaje de referencia</div></div>
                <div><div class="rb-metric">{distance:.1f} km</div><div class="rb-muted">Distancia aproximada</div></div>
              </div>
              <div class="rb-muted" style="margin-top:12px;">Recorrido: {' → '.join(names)}</div>
              <div class="rb-muted" style="margin-top:4px;">Líneas registradas: {', '.join(unique_routes) if unique_routes else 'Sin identificar'}</div>
            </div>
            """, unsafe_allow_html=True)
    else:
        for i, path in enumerate(paths):
            mins = path.get("duration",0)/60
            km = path.get("distance",0)/1000
            st.markdown(f"""
            <div class="rb-result">
              <div class="rb-route-name">Alternativa {i+1}</div>
              <div style="display:flex;gap:26px;margin-top:12px;flex-wrap:wrap;">
                <div><div class="rb-metric">{round(mins)} min</div><div class="rb-muted">Tiempo estimado</div></div>
                <div><div class="rb-metric">{km:.1f} km</div><div class="rb-muted">Distancia</div></div>
              </div>
            </div>
            """, unsafe_allow_html=True)

# Contribution section
st.markdown("---")
st.markdown('<div class="rb-title" style="font-size:22px;">Ayúdanos a mejorar RUTA-BOL</div>', unsafe_allow_html=True)
st.markdown('<div class="rb-subtitle">Comparte una parada o un lugar importante para tu ciudad.</div>', unsafe_allow_html=True)
with st.expander("＋ Agregar parada u hospital"):
    with st.form("contribution_form", clear_on_submit=True):
        kind = st.selectbox("Tipo de lugar", ["Parada de transporte","Hospital","Centro de salud","Teleférico","Terminal","Otro"])
        name = st.text_input("Nombre del lugar")
        municipality = st.selectbox("Municipio", ["La Paz","El Alto","Otro"])
        address = st.text_input("Dirección o referencia")
        c1, c2 = st.columns(2)
        with c1:
            lat = st.text_input("Latitud")
        with c2:
            lon = st.text_input("Longitud")
        submitted = st.form_submit_button("Enviar aporte", type="primary", use_container_width=True)
        if submitted:
            if not name.strip() or not valid_coord(lat, lon):
                st.error("Escribe un nombre y coordenadas válidas.")
            else:
                record = {
                    "tipo":kind, "nombre":name.strip(), "municipio":municipality,
                    "direccion":address.strip(), "latitud":float(lat), "longitud":float(lon),
                    "estado":"pendiente", "fecha_registro":datetime.now(timezone.utc).isoformat()
                }
                ok, message = save_contribution(record)
                if ok:
                    st.success(message)
                else:
                    st.error(message)

st.caption("RUTA-BOL · Tu ciudad, tus rutas.")
