import math
import requests
import streamlit as st
import folium
from streamlit_folium import st_folium

# ------------------------------------------------------------
# RUTA-BOL | Aplicación de búsqueda de lugares y recorridos
# Servicios externos:
# - OpenStreetMap / Overpass: búsqueda de hospitales.
# - Google Routes API: tiempo de conducción con tráfico.
#
# Configurar la clave en .streamlit/secrets.toml:
# GOOGLE_MAPS_API_KEY = "TU_CLAVE"
#
# Nota funcional:
# El tiempo de Google Routes representa tráfico vial para automóvil.
# No representa la posición en vivo de minibuses. Para eso se requiere
# GPS de vehículos o una fuente GTFS-Realtime del operador.
# ------------------------------------------------------------

st.set_page_config(
    page_title="RUTA-BOL",
    page_icon="🚌",
    layout="wide",
    initial_sidebar_state="collapsed",
)

CENTER = (-16.503, -68.145)
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
GOOGLE_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

st.markdown(""" <style> :root { --rb-blue:#087ea4; --rb-dark:#102638; --rb-cyan:#19b8c8; } .stApp { background: #f4f7fb; } .block-container { max-width: 1440px; padding-top: 1.1rem; padding-bottom: 2rem; } .rb-header { background: linear-gradient(115deg,#102638 0%,#123e58 58%,#087ea4 100%); padding: 1.35rem 1.5rem; border-radius: 22px; color: white; margin-bottom: 1rem; box-shadow: 0 12px 32px rgba(16,38,56,.15); } .rb-brand { font-size: 1.75rem; font-weight: 800; letter-spacing: .04em; margin:0; } .rb-subtitle { color:#d8edf5; margin:.25rem 0 0 0; font-size:.95rem; } .rb-panel { background:white; border:1px solid #e7edf3; border-radius:18px; padding:1rem 1.1rem; box-shadow:0 5px 20px rgba(16,38,56,.045); } .rb-muted { color:#647789; font-size:.88rem; } div[data-testid="stMetric"] { background:#f6f9fc; border:1px solid #e6edf3; padding:12px 14px; border-radius:14px; } .stButton>button[kind="primary"] { background:linear-gradient(100deg,#087ea4,#19a9b8); border:0; border-radius:12px; font-weight:700; min-height:2.8rem; } div[data-testid="stTextInput"] input { border-radius:11px; } footer { visibility:hidden; } </style> """, unsafe_allow_html=True)


def get_google_key():
    try:
        return st.secrets.get("GOOGLE_MAPS_API_KEY", "")
    except Exception:
        return ""


def geocode_place(query):
    """Busca una dirección o lugar usando Nominatim."""
    params = {
        "q": f"{query}, La Paz, Bolivia",
        "format": "jsonv2",
        "limit": 1,
        "countrycodes": "bo",
    }
    headers = {"User-Agent": "RUTA-BOL/2.0 (route-search app)"}
    response = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=20)
    response.raise_for_status()
    results = response.json()
    if not results:
        return None
    item = results[0]
    return {
        "name": item.get("display_name", query),
        "lat": float(item["lat"]),
        "lon": float(item["lon"]),
    }


@st.cache_data(ttl=1800, show_spinner=False)
def load_hospitals():
    """Obtiene hospitales y clínicas etiquetados en OpenStreetMap alrededor de La Paz."""
    query = f""" [out:json][timeout:35]; ( node["amenity"~"^(hospital|clinic)$"](around:18000,{CENTER[0]},{CENTER[1]}); way["amenity"~"^(hospital|clinic)$"](around:18000,{CENTER[0]},{CENTER[1]}); relation["amenity"~"^(hospital|clinic)$"](around:18000,{CENTER[0]},{CENTER[1]}); ); out center tags; """
    response = requests.post(OVERPASS_URL, data=query.encode("utf-8"), timeout=45)
    response.raise_for_status()
    elements = response.json().get("elements", [])
    places = []
    seen = set()
    for element in elements:
        tags = element.get("tags", {})
        name = tags.get("name") or tags.get("name:es")
        if not name:
            continue
        lat = element.get("lat", element.get("center", {}).get("lat"))
        lon = element.get("lon", element.get("center", {}).get("lon"))
        if lat is None or lon is None:
            continue
        key = (name.strip().lower(), round(float(lat), 5), round(float(lon), 5))
        if key in seen:
            continue
        seen.add(key)
        places.append({
            "name": name.strip(),
            "lat": float(lat),
            "lon": float(lon),
            "kind": tags.get("amenity", "health"),
            "address": ", ".join(
                x for x in [
                    tags.get("addr:street"),
                    tags.get("addr:housenumber"),
                    tags.get("addr:suburb"),
                ] if x
            ),
        })
    return sorted(places, key=lambda x: x["name"].lower())


def decode_polyline(encoded):
    """Decodifica una polyline codificada de Google."""
    points = []
    index = 0
    lat = 0
    lng = 0
    while index < len(encoded):
        result = 1
        shift = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result += (b & 0x1f) << shift
            shift += 5
            if b < 0x20:
                break
        dlat = ~(result >> 1) if result & 1 else (result >> 1)
        lat += dlat

        result = 1
        shift = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result += (b & 0x1f) << shift
            shift += 5
            if b < 0x20:
                break
        dlng = ~(result >> 1) if result & 1 else (result >> 1)
        lng += dlng
        points.append((lat / 1e5, lng / 1e5))
    return points


def get_traffic_route(origin, destination, api_key):
    """Consulta Google Routes con tráfico vial actual para conducción."""
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "routes.duration,routes.staticDuration,routes.distanceMeters,"
            "routes.polyline.encodedPolyline,routes.description"
        ),
    }
    payload = {
        "origin": {
            "location": {
                "latLng": {"latitude": origin["lat"], "longitude": origin["lon"]}
            }
        },
        "destination": {
            "location": {
                "latLng": {"latitude": destination["lat"], "longitude": destination["lon"]}
            }
        },
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE_OPTIMAL",
        "computeAlternativeRoutes": True,
        "languageCode": "es",
        "units": "METRIC",
    }
    response = requests.post(
        GOOGLE_ROUTES_URL, headers=headers, json=payload, timeout=35
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Google Routes respondió {response.status_code}: {response.text[:500]}"
        )
    routes = response.json().get("routes", [])
    parsed = []
    for route in routes:
        duration = route.get("duration", "0s")
        static_duration = route.get("staticDuration", "0s")
        seconds = int(duration.rstrip("s"))
        static_seconds = int(static_duration.rstrip("s"))
        polyline = route.get("polyline", {}).get("encodedPolyline", "")
        parsed.append({
            "seconds": seconds,
            "static_seconds": static_seconds,
            "distance_m": int(route.get("distanceMeters", 0)),
            "points": decode_polyline(polyline) if polyline else [],
            "description": route.get("description", "Recorrido"),
        })
    return parsed


def format_duration(seconds):
    minutes = max(1, round(seconds / 60))
    hours, mins = divmod(minutes, 60)
    return f"{hours} h {mins} min" if hours else f"{mins} min"


def format_distance(meters):
    if meters >= 1000:
        return f"{meters / 1000:.1f} km".replace(".", ",")
    return f"{meters} m"


def build_map(origin=None, destination=None, hospitals=None, routes=None):
    m = folium.Map(
        location=CENTER,
        zoom_start=12,
        tiles="CartoDB positron",
        control_scale=True,
    )
    if hospitals:
        for hospital in hospitals:
            folium.Marker(
                [hospital["lat"], hospital["lon"]],
                tooltip=hospital["name"],
                popup=folium.Popup(
                    f"<b>{hospital['name']}</b><br>{hospital.get('address') or 'La Paz / El Alto'}",
                    max_width=280,
                ),
                icon=folium.Icon(color="red", icon="plus-sign"),
            ).add_to(m)

    if origin:
        folium.Marker(
            [origin["lat"], origin["lon"]],
            tooltip="Punto de partida",
            popup=origin["name"],
            icon=folium.Icon(color="green", icon="play"),
        ).add_to(m)
    if destination:
        folium.Marker(
            [destination["lat"], destination["lon"]],
            tooltip="Destino",
            popup=destination["name"],
            icon=folium.Icon(color="blue", icon="flag"),
        ).add_to(m)

    if routes:
        colors = ["#087ea4", "#e58b00", "#7754c8"]
        for index, route in enumerate(routes):
            if route["points"]:
                folium.PolyLine(
                    route["points"],
                    color=colors[index % len(colors)],
                    weight=7 if index == 0 else 5,
                    opacity=0.95 if index == 0 else 0.65,
                    tooltip=f"Alternativa {index + 1}",
                ).add_to(m)
        all_points = [p for route in routes for p in route["points"]]
        if all_points:
            m.fit_bounds(all_points)
    elif origin and destination:
        m.fit_bounds([
            [origin["lat"], origin["lon"]],
            [destination["lat"], destination["lon"]],
        ])
    return m


# Encabezado de marca: no expone detalles internos ni estados de desarrollo.
st.markdown(""" <div class="rb-header"> <p class="rb-brand">🚌 RUTA-BOL</p> <p class="rb-subtitle">Muévete mejor por La Paz y El Alto</p> </div> """, unsafe_allow_html=True)

search_col, map_col = st.columns([0.88, 1.55], gap="large")

with search_col:
    st.markdown('<div class="rb-panel">', unsafe_allow_html=True)
    st.subheader("¿A dónde quieres ir?")
    origin_text = st.text_input(
        "Punto de partida",
        placeholder="Ej. La Ceja de El Alto",
        key="origin_text",
    )
    destination_mode = st.radio(
        "Destino",
        ["Buscar lugar", "Hospital"],
        horizontal=True,
        label_visibility="collapsed",
    )

    hospitals = []
    selected_hospital = None
    if destination_mode == "Hospital":
        hospital_query = st.text_input(
            "Buscar hospital o clínica",
            placeholder="Ej. Hospital de Clínicas",
        )
        try:
            with st.spinner("Buscando centros de salud..."):
                hospitals = load_hospitals()
            filtered = [
                h for h in hospitals
                if not hospital_query.strip()
                or hospital_query.lower() in h["name"].lower()
            ]
            if filtered:
                selected_name = st.selectbox(
                    "Centros de salud encontrados",
                    [h["name"] for h in filtered],
                )
                selected_hospital = next(
                    h for h in filtered if h["name"] == selected_name
                )
            else:
                st.info("No se encontraron coincidencias. Prueba con otro nombre.")
        except Exception:
            st.warning("No se pudo consultar el directorio de centros de salud. Intenta nuevamente.")
    else:
        destination_text = st.text_input(
            "Destino",
            placeholder="Ej. Plaza Murillo",
            key="destination_text",
        )

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    search_clicked = st.button(
        "Buscar recorrido",
        type="primary",
        use_container_width=True,
    )
    st.markdown(
        '<p class="rb-muted">Los resultados dependen de la cobertura y actualización de los servicios cartográficos.</p>',
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="rb-panel">', unsafe_allow_html=True)
    st.subheader("Centros de salud cercanos")
    if not hospitals:
        try:
            hospitals = load_hospitals()
        except Exception:
            hospitals = []
    if hospitals:
        for item in hospitals[:6]:
            st.markdown(f"**{item['name']}**")
            if item.get("address"):
                st.caption(item["address"])
    else:
        st.caption("El directorio se cargará cuando el servicio cartográfico esté disponible.")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="rb-panel">', unsafe_allow_html=True)
    st.subheader("Tu perfil")
    st.caption("Consulta tus recorridos desde una experiencia sencilla y clara.")
    st.markdown("</div>", unsafe_allow_html=True)

with map_col:
    st.markdown('<div class="rb-panel">', unsafe_allow_html=True)
    st.subheader("Mapa de La Paz y El Alto")
    route_results = st.session_state.get("route_results", [])
    map_origin = st.session_state.get("map_origin")
    map_destination = st.session_state.get("map_destination")
    try:
        current_hospitals = hospitals if hospitals else load_hospitals()
    except Exception:
        current_hospitals = []
    fmap = build_map(
        map_origin,
        map_destination,
        current_hospitals,
        route_results,
    )
    st_folium(
        fmap,
        height=590,
        use_container_width=True,
        returned_objects=[],
        key="ruta_bol_map",
    )
    st.markdown("</div>", unsafe_allow_html=True)

# La consulta se ejecuta después de dibujar los controles para mantener la interfaz estable.
if search_clicked:
    st.session_state.route_results = []
    st.session_state.map_origin = None
    st.session_state.map_destination = None

    destination_value = (
        selected_hospital["name"]
        if destination_mode == "Hospital" and selected_hospital
        else st.session_state.get("destination_text", "")
    )

    if not origin_text.strip():
        st.error("Escribe un punto de partida.")
    elif not destination_value:
        st.error("Selecciona o escribe un destino.")
    else:
        try:
            with st.spinner("Localizando los puntos del recorrido..."):
                origin_data = geocode_place(origin_text)
                destination_data = (
                    {
                        "name": selected_hospital["name"],
                        "lat": selected_hospital["lat"],
                        "lon": selected_hospital["lon"],
                    }
                    if destination_mode == "Hospital" and selected_hospital
                    else geocode_place(destination_value)
                )

            if not origin_data:
                st.error("No se pudo localizar el punto de partida. Prueba con un nombre más específico.")
            elif not destination_data:
                st.error("No se pudo localizar el destino. Prueba con otro nombre.")
            else:
                st.session_state.map_origin = origin_data
                st.session_state.map_destination = destination_data
                api_key = get_google_key()

                if not api_key:
                    st.warning(
                        "La búsqueda de lugares está disponible, pero el cálculo de tráfico vial "
                        "requiere configurar una clave de Google Routes API."
                    )
                else:
                    with st.spinner("Calculando el recorrido con información de tráfico..."):
                        results = get_traffic_route(
                            origin_data, destination_data, api_key
                        )
                    if results:
                        st.session_state.route_results = results
                        st.success("Recorrido calculado.")
                    else:
                        st.info("No se encontraron recorridos para estos puntos.")
        except requests.RequestException:
            st.error("No fue posible conectar con el servicio cartográfico. Comprueba tu conexión e inténtalo nuevamente.")
        except RuntimeError as exc:
            st.error(f"No se pudo calcular el recorrido: {exc}")
        except Exception:
            st.error("Ocurrió un problema al procesar la búsqueda. Inténtalo nuevamente.")
    st.rerun()

# Resultados debajo del mapa, presentados sin exponer detalles técnicos.
results = st.session_state.get("route_results", [])
if results:
    st.markdown("### Opciones de recorrido")
    result_cols = st.columns(min(len(results), 3))
    for index, route in enumerate(results[:3]):
        with result_cols[index]:
            st.markdown('<div class="rb-panel">', unsafe_allow_html=True)
            st.markdown("**Recomendado**" if index == 0 else f"**Alternativa {index}**")
            st.metric("Tiempo con tráfico", format_duration(route["seconds"]))
            st.metric("Distancia", format_distance(route["distance_m"]))
            if route["static_seconds"] > 0:
                difference = route["seconds"] - route["static_seconds"]
                if difference > 60:
                    st.caption(f"El tráfico añade aproximadamente {format_duration(difference)}.")
                else:
                    st.caption("Tráfico fluido según la estimación disponible.")
            st.markdown("</div>", unsafe_allow_html=True)

st.markdown(""" <hr> <div style="text-align:center;color:#718395;font-size:.82rem;"> RUTA-BOL · Información cartográfica sujeta a disponibilidad y actualización de sus proveedores. </div> """, unsafe_allow_html=True)
