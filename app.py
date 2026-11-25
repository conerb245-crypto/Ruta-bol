import streamlit as st
import folium
from streamlit_folium import st_folium
import heapq
import math

st.set_page_config(page_title="RUTA-BOL | Transporte y hospitales", page_icon="🚌", layout="wide")

# DEMO: nodos y conexiones ilustrativas. Sustituir por recorridos verificados y georreferenciados.
NODES = {
    "CEJA": {"name": "La Ceja (El Alto)", "lat": -16.5040, "lon": -68.1630, "kind": "origen"},
    "BALL": {"name": "Cruce Ballivián (referencial)", "lat": -16.4980, "lon": -68.1580, "kind": "parada"},
    "LIMA": {"name": "Av. Lima (referencial)", "lat": -16.4930, "lon": -68.1510, "kind": "parada"},
    "CEM": {"name": "Cementerio General (referencial)", "lat": -16.5000, "lon": -68.1370, "kind": "parada"},
    "SANF": {"name": "San Francisco (referencial)", "lat": -16.4970, "lon": -68.1350, "kind": "parada"},
    "CLIN": {"name": "Hospital de Clínicas (destino)", "lat": -16.5100, "lon": -68.1280, "kind": "hospital"},
    "VILLA": {"name": "Villa Dolores (alternativa referencial)", "lat": -16.5150, "lon": -68.1580, "kind": "parada"},
    "SOPO": {"name": "Sopocachi (alternativa referencial)", "lat": -16.5110, "lon": -68.1260, "kind": "parada"},
}

# Cada conexión es demostrativa; tiempo en minutos y línea ilustrativa.
EDGES = [
    ("CEJA", "BALL", 6, "Línea demostrativa A"),
    ("BALL", "LIMA", 7, "Línea demostrativa A"),
    ("LIMA", "CEM", 8, "Línea demostrativa B"),
    ("CEM", "CLIN", 10, "Línea demostrativa B"),
    ("CEJA", "VILLA", 9, "Línea demostrativa C"),
    ("VILLA", "SANF", 11, "Línea demostrativa C"),
    ("SANF", "CLIN", 12, "Línea demostrativa D"),
    ("BALL", "SANF", 13, "Línea demostrativa E"),
    ("LIMA", "SOPO", 9, "Línea demostrativa F"),
    ("SOPO", "CLIN", 8, "Línea demostrativa F"),
]

def build_graph(blocked):
    graph = {n: [] for n in NODES}
    for a, b, minutes, line in EDGES:
        edge_key = tuple(sorted((a, b)))
        if edge_key in blocked:
            continue
        graph[a].append((b, minutes, line))
        graph[b].append((a, minutes, line))
    return graph

def dijkstra(start, goal, blocked=None):
    blocked = blocked or set()
    graph = build_graph(blocked)
    queue = [(0, start, [start], [])]
    best = {}
    while queue:
        cost, node, path, legs = heapq.heappop(queue)
        if node in best and best[node] <= cost:
            continue
        best[node] = cost
        if node == goal:
            return cost, path, legs
        for nxt, minutes, line in graph[node]:
            if nxt not in path:
                heapq.heappush(queue, (cost + minutes, nxt, path + [nxt], legs + [(node, nxt, minutes, line)]))
    return None

def alternatives(start, goal, blocked, limit=3):
    first = dijkstra(start, goal, blocked)
    if not first:
        return []
    candidates = []
    seen = set()
    for a, b, *_ in first[2]:
        result = dijkstra(start, goal, blocked | {tuple(sorted((a, b)))})
        if result and tuple(result[1]) not in seen:
            seen.add(tuple(result[1]))
            candidates.append(result)
    candidates.sort(key=lambda x: x[0])
    return [first] + candidates[:limit-1]

def make_map(routes, blocked, selected_idx=0):
    m = folium.Map(location=[-16.503, -68.145], zoom_start=13, control_scale=True, tiles="OpenStreetMap")
    for key, node in NODES.items():
        if node["kind"] == "hospital":
            color, icon = "red", "plus-sign"
        elif node["kind"] == "origen":
            color, icon = "green", "play"
        else:
            color, icon = "blue", "info-sign"
        folium.Marker(
            [node["lat"], node["lon"]],
            popup=node["name"],
            tooltip=node["name"],
            icon=folium.Icon(color=color, icon=icon)
        ).add_to(m)

    palette = ["#1769ff", "#e58b00", "#7b4bd1"]
    for idx, route in enumerate(routes):
        if not route:
            continue
        coords = [[NODES[n]["lat"], NODES[n]["lon"]] for n in route[1]]
        folium.PolyLine(
            coords, color=palette[idx % len(palette)],
            weight=7 if idx == selected_idx else 4,
            opacity=0.95 if idx == selected_idx else 0.55,
            tooltip=f"Alternativa {idx+1}"
        ).add_to(m)

    for a, b, *_ in EDGES:
        if tuple(sorted((a, b))) in blocked:
            p1, p2 = NODES[a], NODES[b]
            folium.PolyLine(
                [[p1["lat"], p1["lon"]], [p2["lat"], p2["lon"]]],
                color="red", weight=5, dash_array="8, 8",
                tooltip="Tramo marcado como bloqueado (dato ingresado)"
            ).add_to(m)
    return m

st.markdown("""
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 1rem;}
h1 {letter-spacing: -1px;}
</style>
""", unsafe_allow_html=True)

st.title("🚌 RUTA-BOL")
st.caption("Buscador demostrativo de transporte público hacia hospitales · La Paz y El Alto")
st.warning("PROTOTIPO DEMOSTRATIVO: los puntos, líneas, tiempos y conexiones del ejemplo no son rutas verificadas en tiempo real.")

with st.sidebar:
    st.header("Buscar recorrido")
    start = st.selectbox("Punto de partida", list(NODES), format_func=lambda x: NODES[x]["name"], index=0)
    goal = st.selectbox("Hospital de destino", ["CLIN"], format_func=lambda x: NODES[x]["name"])
    st.divider()
    st.subheader("Incidencias viales")
    st.caption("Activa los tramos que quieras simular como bloqueados. No son reportes reales.")
    incident_options = {
        "La Ceja ↔ Cruce Ballivián": ("CEJA", "BALL"),
        "Cruce Ballivián ↔ Av. Lima": ("BALL", "LIMA"),
        "Av. Lima ↔ Cementerio": ("LIMA", "CEM"),
        "Cementerio ↔ Hospital": ("CEM", "CLIN"),
        "Villa Dolores ↔ San Francisco": ("VILLA", "SANF"),
    }
    chosen = []
    for label, edge in incident_options.items():
        if st.checkbox(label, key="block_" + label):
            chosen.append(tuple(sorted(edge)))
    st.caption("En una versión pública, estas incidencias deberán proceder de reportes verificados y fechados.")
    calculate = st.button("🔎 CALCULAR RUTAS", type="primary", use_container_width=True)

if "routes" not in st.session_state:
    st.session_state.routes = alternatives(start, goal, set(chosen))
if calculate or st.session_state.get("last_query") != (start, goal, tuple(sorted(chosen))):
    st.session_state.routes = alternatives(start, goal, set(chosen))
    st.session_state.last_query = (start, goal, tuple(sorted(chosen)))

routes = st.session_state.routes
left, right = st.columns([1.65, 1], gap="large")
with left:
    st.subheader("Mapa de recorridos")
    if routes:
        fmap = make_map(routes, set(chosen))
        st_folium(fmap, height=570, use_container_width=True, returned_objects=[])
        st.caption("Azul: ruta principal · Naranja y violeta: alternativas · Rojo discontinuo: tramo marcado como bloqueado")
    else:
        st.error("No se encontró un recorrido con las incidencias seleccionadas.")
with right:
    st.subheader("Opciones encontradas")
    if routes:
        for idx, (minutes, path, legs) in enumerate(routes):
            title = "Ruta recomendada" if idx == 0 else f"Ruta alternativa {idx}"
            with st.container(border=True):
                st.markdown(f"**{title}**")
                st.metric("Tiempo estimado demostrativo", f"{minutes} min")
                st.write(" → ".join(NODES[n]["name"] for n in path))
                lines = list(dict.fromkeys(leg[3] for leg in legs))
                st.caption("Transporte: " + ", ".join(lines))
                if idx == 0:
                    st.success("Menor tiempo estimado según los datos de ejemplo.")
    else:
        st.info("Prueba desactivando algún tramo bloqueado.")

st.divider()
st.subheader("Cómo se gestionan los bloqueos")
st.write(
    "El algoritmo vuelve a calcular el camino excluyendo los tramos marcados. "
    "Para detectar bloqueos reales automáticamente se necesita integrar una fuente de incidencias "
    "con fecha, ubicación, estado y verificación; esta versión solo permite simular o registrar incidencias."
)
st.caption("RUTA-BOL · Proyecto académico · Datos de demostración, no usar para navegación real.")
