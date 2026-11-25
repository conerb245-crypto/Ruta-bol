import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import st_folium
from math import radians, sin, cos, sqrt, atan2
import heapq
from io import StringIO

st.set_page_config(page_title="RUTA-BOL | Transporte público", page_icon="🚌", layout="wide")

st.title("🚌 RUTA-BOL")
st.caption("Planificador de transporte público para La Paz y El Alto")

st.info(
    "Esta versión no necesita Google Maps API. Para recomendar minibuses reales, "
    "necesita una base de datos de rutas y paradas verificadas. No se inventan recorridos ni tarifas."
)

REQUIRED = ["ruta", "parada", "orden", "latitud", "longitud", "pasaje_bs", "minutos_hasta_siguiente"]

TEMPLATE = pd.DataFrame(columns=REQUIRED)

def haversine(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = radians(lat1), radians(lat2)
    dp = radians(lat2 - lat1)
    dl = radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * r * atan2(sqrt(a), sqrt(1 - a))

@st.cache_data(ttl=3600, show_spinner=False)
def geocode(place):
    url = "https://nominatim.openstreetmap.org/search"
    headers = {"User-Agent": "RUTA-BOL/2.0 (public transport route planner)"}
    params = {"q": place + ", La Paz, Bolivia", "format": "jsonv2", "limit": 1}
    try:
        res = requests.get(url, params=params, headers=headers, timeout=20)
        res.raise_for_status()
        data = res.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"]), data[0].get("display_name", place)
    except Exception:
        return None
    return None

def validate_routes(df):
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        return False, "Faltan columnas: " + ", ".join(missing)
    data = df.copy()
    try:
        for c in ["orden", "latitud", "longitud", "pasaje_bs", "minutos_hasta_siguiente"]:
            data[c] = pd.to_numeric(data[c], errors="raise")
    except Exception:
        return False, "Las columnas numéricas contienen valores no válidos."
    if data.empty:
        return False, "El archivo no contiene paradas. Agrega datos reales y verificados."
    if data[["ruta", "parada"]].isna().any().any():
        return False, "Hay nombres de ruta o paradas vacíos."
    if not data["latitud"].between(-17.0, -15.5).all() or not data["longitud"].between(-69.0, -67.0).all():
        return False, "Hay coordenadas fuera del área esperada de La Paz y El Alto."
    if (data["pasaje_bs"] < 0).any() or (data["minutos_hasta_siguiente"] < 0).any():
        return False, "Pasajes y tiempos no pueden ser negativos."
    return True, data

def build_edges(df):
    graph = {}
    stop_coords = {}
    stop_names = {}
    for route, group in df.groupby("ruta"):
        group = group.sort_values("orden")
        rows = list(group.to_dict("records"))
        for row in rows:
            stop_coords[row["parada"]] = (float(row["latitud"]), float(row["longitud"]))
            stop_names[row["parada"]] = row["parada"]
        for a, b in zip(rows, rows[1:]):
            graph.setdefault(a["parada"], []).append({
                "to": b["parada"], "route": str(route),
                "fare": float(a["pasaje_bs"]),
                "minutes": float(a["minutos_hasta_siguiente"])
            })
            # Se permite recorrer el mismo tramo en sentido contrario como estimación;
            # confirmar el sentido real antes de publicar la ruta.
            graph.setdefault(b["parada"], []).append({
                "to": a["parada"], "route": str(route),
                "fare": float(a["pasaje_bs"]),
                "minutes": float(a["minutos_hasta_siguiente"])
            })
    return graph, stop_coords, stop_names

def nearest_stops(coords, stop_coords, limit=4):
    lat, lon = coords
    ranked = sorted(
        ((haversine(lat, lon, xy[0], xy[1]), name) for name, xy in stop_coords.items()),
        key=lambda x: x[0]
    )
    return ranked[:limit]

def find_paths(graph, starts, goals, max_paths=3):
    # Busca opciones por tiempo aproximado; el pasaje se cobra una vez por cada ruta abordada.
    queue = []
    counter = 0
    for dist, name in starts:
        heapq.heappush(queue, (dist * 12, counter, name, None, (name,), (), 0.0, 0.0))
        counter += 1
    results = []
    best_state = {}
    while queue and len(results) < max_paths:
        cost, _, node, last_route, path, route_steps, fare, minutes = heapq.heappop(queue)
        if node in [g[1] for g in goals]:
            results.append({
                "path": list(path),
                "route_steps": list(route_steps),
                "fare": fare,
                "minutes": minutes,
                "walk_km": cost / 12.0 - minutes / 60.0 if cost > 0 else 0
            })
            continue
        state = (node, last_route, len(path))
        if best_state.get(state, float("inf")) <= cost:
            continue
        best_state[state] = cost
        if len(path) > 18:
            continue
        for edge in graph.get(node, []):
            new_route = edge["route"]
            changed = new_route != last_route
            new_fare = fare + (edge["fare"] if changed else 0)
            new_minutes = minutes + edge["minutes"]
            new_steps = route_steps + ((new_route,) if changed else ())
            new_cost = cost + edge["minutes"] + (8 if changed and last_route is not None else 0)
            heapq.heappush(queue, (new_cost, counter, edge["to"], new_route,
                                   path + (edge["to"],), new_steps, new_fare, new_minutes))
            counter += 1
    # Eliminar resultados repetidos.
    unique, seen = [], set()
    for r in results:
        key = (tuple(r["path"]), tuple(r["route_steps"]))
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique

with st.sidebar:
    st.header("Datos de transporte")
    uploaded = st.file_uploader("Sube la base de rutas verificadas (.csv)", type=["csv"])
    st.download_button(
        "Descargar plantilla CSV",
        data=TEMPLATE.to_csv(index=False).encode("utf-8"),
        file_name="plantilla_rutas_ruta_bol.csv",
        mime="text/csv"
    )
    st.caption("Completa la plantilla con rutas, paradas, coordenadas, pasajes y tiempos confirmados.")

routes_df = None
if uploaded is not None:
    try:
        raw = pd.read_csv(uploaded)
        ok, checked = validate_routes(raw)
        if ok:
            routes_df = checked
            st.sidebar.success(f"Base cargada: {routes_df['ruta'].nunique()} rutas y {len(routes_df)} registros de paradas.")
        else:
            st.sidebar.error(checked)
    except Exception as exc:
        st.sidebar.error(f"No se pudo leer el CSV: {exc}")

tab1, tab2, tab3 = st.tabs(["🔎 Buscar recorrido", "🗺️ Mapa", "ℹ️ Cómo completar los datos"])

with tab1:
    st.subheader("¿De dónde sales y a dónde quieres llegar?")
    c1, c2 = st.columns(2)
    with c1:
        origin = st.text_input("Punto de partida", placeholder="Ej. La Ceja de El Alto")
    with c2:
        destination = st.text_input("Destino", placeholder="Ej. Hospital de Clínicas")
    search = st.button("Buscar rutas", type="primary", use_container_width=True)

    if search:
        if not origin.strip() or not destination.strip():
            st.warning("Escribe el punto de partida y el destino.")
        elif routes_df is None:
            st.warning("Todavía no hay una base de rutas cargada. Descarga la plantilla CSV, complétala con información verificada y súbela en el menú lateral. Por ahora no podemos recomendar minibuses ni pasajes reales.")
        else:
            with st.spinner("Buscando los lugares y conectando las paradas..."):
                start_geo = geocode(origin.strip())
                end_geo = geocode(destination.strip())
                if not start_geo or not end_geo:
                    st.error("No se pudo localizar uno de los lugares. Prueba con un nombre más específico.")
                else:
                    graph, stop_coords, _ = build_edges(routes_df)
                    starts = nearest_stops((start_geo[0], start_geo[1]), stop_coords)
                    goals = nearest_stops((end_geo[0], end_geo[1]), stop_coords)
                    paths = find_paths(graph, starts, goals)
                    if not paths:
                        st.warning("La base cargada no contiene una conexión entre esos lugares. No se inventarán rutas.")
                    else:
                        st.session_state["last_search"] = {
                            "start": start_geo, "end": end_geo, "paths": paths,
                            "stop_coords": stop_coords
                        }
                        st.success(f"Se encontraron {len(paths)} alternativa(s) dentro de la base cargada.")

    result = st.session_state.get("last_search")
    if result:
        st.caption("Resultados calculados únicamente con la base de datos que cargaste.")
        for i, route in enumerate(result["paths"], 1):
            with st.container(border=True):
                st.markdown(f"**Alternativa {i}**")
                st.write("Minibuses / líneas: " + (" → ".join(route["route_steps"]) if route["route_steps"] else "Sin línea identificada"))
                st.write("Paradas: " + " → ".join(route["path"]))
                transfers = max(0, len(route["route_steps"]) - 1)
                a, b, c = st.columns(3)
                a.metric("Pasaje estimado", f"Bs {route['fare']:.2f}")
                b.metric("Transbordos", transfers)
                c.metric("Tiempo en vehículo", f"{route['minutes']:.0f} min")
                st.caption("El costo y tiempo son estimaciones de los datos cargados; verifica tarifas, sentidos y horarios con el operador.")

with tab2:
    st.subheader("Mapa de origen, destino y paradas")
    result = st.session_state.get("last_search")
    if result:
        m = folium.Map(location=[result["start"][0], result["start"][1]], zoom_start=13, control_scale=True)
        folium.Marker([result["start"][0], result["start"][1]], tooltip="Origen", icon=folium.Icon(color="green")).add_to(m)
        folium.Marker([result["end"][0], result["end"][1]], tooltip="Destino", icon=folium.Icon(color="red")).add_to(m)
        palette = ["blue", "purple", "orange"]
        for idx, route in enumerate(result["paths"]):
            coords = [result["stop_coords"][p] for p in route["path"] if p in result["stop_coords"]]
            if coords:
                folium.PolyLine(coords, color=palette[idx % len(palette)], weight=5,
                                tooltip=f"Alternativa {idx+1}").add_to(m)
                for j, p in enumerate(route["path"]):
                    if p in result["stop_coords"]:
                        folium.CircleMarker(result["stop_coords"][p], radius=4,
                                            tooltip=p, fill=True).add_to(m)
        st_folium(m, use_container_width=True, height=520)
    else:
        st.info("Cuando realices una búsqueda con una base de rutas cargada, aquí aparecerán las alternativas.")

with tab3:
    st.subheader("Cómo preparar la base de rutas")
    st.markdown("""
    Cada fila representa una parada de una ruta. Las paradas deben estar ordenadas según el recorrido.

    - **ruta:** nombre o código de la línea/minibús.
    - **parada:** nombre único y reconocible de la parada.
    - **orden:** posición de la parada dentro de esa ruta (1, 2, 3...).
    - **latitud / longitud:** coordenadas de la parada.
    - **pasaje_bs:** tarifa en bolivianos para abordar esa ruta.
    - **minutos_hasta_siguiente:** tiempo aproximado hasta la siguiente parada.

    **Importante:** el sistema genera conexiones entre paradas consecutivas en ambos sentidos como una ayuda inicial.
    Antes de usarlo públicamente hay que confirmar los sentidos de circulación, los puntos de parada, los pasajes y los tiempos.
    La plantilla descargable contiene solo datos ficticios de ejemplo y no representa una ruta real.
    """)
    st.code(",".join(REQUIRED), language="text")
    st.warning("La ubicación del teléfono no se activa automáticamente en esta versión. Puedes escribir el origen; para usar GPS se necesita permiso del navegador y una implementación adicional.")
    st.caption("Geocodificación: OpenStreetMap / Nominatim. El mapa usa OpenStreetMap. Se requiere conexión a internet.")
