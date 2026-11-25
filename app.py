import math
import requests
import streamlit as st
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="RUTA-BOL", page_icon="🚌", layout="wide")

# RUTA-BOL usa servicios abiertos: OpenStreetMap, Nominatim, Overpass y OSRM.
# No requiere GOOGLE_MAPS_API_KEY. Los tiempos son estimaciones de conducción,
# no tráfico en vivo ni horarios/posiciones reales de minibuses.

HEADERS = {"User-Agent": "RUTA-BOL/2.0 (educational route finder)"}
CENTER = [-16.5000, -68.1500]

@st.cache_data(ttl=3600, show_spinner=False)
def geocode(place):
    url = "https://nominatim.openstreetmap.org/search"
    r = requests.get(url, params={"q": place + ", La Paz, Bolivia", "format": "json", "limit": 1}, headers=HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    if not data:
        return None
    return float(data[0]["lat"]), float(data[0]["lon"]), data[0]["display_name"]

@st.cache_data(ttl=1800, show_spinner=False)
def get_hospitals():
    query = """ [out:json][timeout:25]; area["name"="La Paz"]["boundary"="administrative"]->.a; ( node["amenity"="hospital"](area.a); way["amenity"="hospital"](area.a); relation["amenity"="hospital"](area.a); node["healthcare"="hospital"](area.a); way["healthcare"="hospital"](area.a); ); out center tags; """
    endpoints = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter"
    ]
    for endpoint in endpoints:
        try:
            r = requests.post(endpoint, data={"data": query}, headers=HEADERS, timeout=40)
            r.raise_for_status()
            elements = r.json().get("elements", [])
            hospitals = []
            seen = set()
            for el in elements:
                tags = el.get("tags", {})
                name = tags.get("name", "Hospital sin nombre")
                lat = el.get("lat", el.get("center", {}).get("lat"))
                lon = el.get("lon", el.get("center", {}).get("lon"))
                if lat is None or lon is None:
                    continue
                key = (name, round(float(lat), 5), round(float(lon), 5))
                if key not in seen:
                    seen.add(key)
                    hospitals.append({"name": name, "lat": float(lat), "lon": float(lon)})
            return hospitals
        except Exception:
            continue
    return []

def route_osrm(origin, destination):
    coords = f"{origin[1]},{origin[0]};{destination[1]},{destination[0]}"
    url = f"https://router.project-osrm.org/route/v1/driving/{coords}"
    r = requests.get(url, params={"overview": "full", "geometries": "geojson", "steps": "false"}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        raise ValueError("No se encontró una ruta para esos puntos.")
    item = data["routes"][0]
    points = [(lat, lon) for lon, lat in item["geometry"]["coordinates"]]
    return points, item["distance"] / 1000, item["duration"] / 60

st.markdown(""" <style> .block-container {padding-top: 1.4rem; max-width: 1200px;} .hero {padding: 1.4rem 1.5rem; border-radius: 18px; background: linear-gradient(115deg,#101827,#173b58); color:white; margin-bottom:1rem;} .hero h1 {margin:0; font-size:2.2rem;} .hero p {margin:.35rem 0 0; color:#d8e7f2;} .small-note {color:#64748b; font-size:.88rem;} </style> """, unsafe_allow_html=True)

st.markdown('<div class="hero"><h1>🚌 RUTA-BOL</h1><p>Explora hospitales y calcula recorridos en La Paz y El Alto</p></div>', unsafe_allow_html=True)

tab_route, tab_hosp = st.tabs(["🧭 Buscar recorrido", "🏥 Hospitales"])

with tab_route:
    c1, c2 = st.columns(2)
    with c1:
        origin_text = st.text_input("Punto de partida", placeholder="Ej. La Ceja de El Alto")
    with c2:
        destination_text = st.text_input("Destino", placeholder="Ej. Hospital de Clínicas")
    if st.button("Buscar recorrido", type="primary", use_container_width=True):
        if not origin_text.strip() or not destination_text.strip():
            st.warning("Escribe el punto de partida y el destino.")
        else:
            try:
                with st.spinner("Localizando los lugares y calculando el recorrido..."):
                    a = geocode(origin_text.strip())
                    b = geocode(destination_text.strip())
                    if not a or not b:
                        st.error("No se pudo localizar uno de los lugares. Prueba con un nombre más completo.")
                    else:
                        points, km, minutes = route_osrm((a[0], a[1]), (b[0], b[1]))
                        st.session_state["route_result"] = {
                            "a": a, "b": b, "points": points, "km": km, "minutes": minutes
                        }
            except Exception as e:
                st.error(f"No se pudo calcular el recorrido en este momento: {e}")

    result = st.session_state.get("route_result")
    if result:
        m1, m2 = st.columns(2)
        m1.metric("Distancia estimada", f'{result["km"]:.1f} km')
        m2.metric("Tiempo estimado", f'{round(result["minutes"])} min')
        fmap = folium.Map(location=[result["a"][0], result["a"][1]], zoom_start=13, control_scale=True)
        folium.Marker([result["a"][0], result["a"][1]], tooltip="Partida", popup=result["a"][2], icon=folium.Icon(color="green")).add_to(fmap)
        folium.Marker([result["b"][0], result["b"][1]], tooltip="Destino", popup=result["b"][2], icon=folium.Icon(color="red")).add_to(fmap)
        folium.PolyLine(result["points"], color="#1677ff", weight=6, opacity=.9).add_to(fmap)
        st_folium(fmap, use_container_width=True, height=470)
        st.caption("Estimación para desplazamiento por carretera mediante OSRM. No representa tráfico en vivo ni rutas verificadas de minibuses.")

with tab_hosp:
    st.write("Hospitales identificados en OpenStreetMap dentro del área consultada.")
    if st.button("Cargar hospitales", type="primary"):
        with st.spinner("Consultando el mapa abierto..."):
            st.session_state["hospitals"] = get_hospitals()
    hospitals = st.session_state.get("hospitals")
    if hospitals is not None:
        if hospitals:
            st.success(f"Se encontraron {len(hospitals)} registros de hospitales.")
            fmap = folium.Map(location=CENTER, zoom_start=12, control_scale=True)
            for h in hospitals:
                folium.Marker([h["lat"], h["lon"]], tooltip=h["name"], popup=h["name"], icon=folium.Icon(color="red", icon="plus-sign")).add_to(fmap)
            st_folium(fmap, use_container_width=True, height=500)
            st.dataframe([{"Hospital": h["name"], "Latitud": h["lat"], "Longitud": h["lon"]} for h in hospitals], use_container_width=True, hide_index=True)
        else:
            st.warning("No se pudieron recuperar hospitales. Intenta nuevamente más tarde.")

st.divider()
st.caption("RUTA-BOL utiliza datos abiertos de OpenStreetMap. La cobertura depende de los datos disponibles y puede contener omisiones. Los recorridos son estimaciones de carretera; no se muestran ubicaciones GPS de minibuses ni tráfico en tiempo real.")
