import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import requests, math, heapq, os

st.set_page_config(page_title="RUTA-BOL", page_icon="🚌", layout="wide")
st.title("🚌 RUTA-BOL")
st.caption("Planificador de transporte público · La Paz y El Alto")

BASE = os.path.join(os.path.dirname(__file__), "data")
ROUTES_FILE = os.path.join(BASE, "rutas_y_paradas.csv")
FARES_FILE = os.path.join(BASE, "tarifas_referencia.csv")
CATALOG_FILE = os.path.join(BASE, "catalogo_rutas_historico.csv")

st.warning(
    "La base incluida contiene estadísticas históricas y tarifas de referencia. "
    "Aún no incluye trazados ni paradas individuales verificadas; por eso la búsqueda "
    "de minibuses reales se habilitará cuando se incorporen esos datos."
)

@st.cache_data(ttl=3600)
def read_csv(path):
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()

catalog = read_csv(CATALOG_FILE)
fares = read_csv(FARES_FILE)
routes = read_csv(ROUTES_FILE)

t1, t2, t3, t4 = st.tabs(["Buscar recorrido", "Mapa", "Tarifas", "Base de datos"])

with t1:
    st.subheader("Planifica tu viaje")
    c1,c2 = st.columns(2)
    with c1:
        origin = st.text_input("¿Desde dónde sales?", placeholder="Ej. La Ceja de El Alto")
    with c2:
        dest = st.text_input("¿A dónde quieres llegar?", placeholder="Ej. Hospital de Clínicas")
    if st.button("Buscar transporte público", type="primary", use_container_width=True):
        if not origin.strip() or not dest.strip():
            st.error("Escribe origen y destino.")
        elif routes.empty or not {"route_id","parada","latitud","longitud","orden_parada"}.issubset(routes.columns):
            st.info("La búsqueda todavía no puede ofrecer líneas ni transbordos reales: falta cargar recorridos y paradas georreferenciadas verificadas.")
        else:
            st.info("La base de rutas está cargada. Esta versión requiere datos de origen/destino geocodificados y sentidos confirmados para calcular combinaciones con fiabilidad.")
    st.markdown("**Funciones previstas al completar la base:** líneas que puedes tomar, parada de subida, parada de bajada, transbordos, alternativas y costo estimado.")

with t2:
    st.subheader("Mapa de transporte")
    m = folium.Map(location=[-16.50,-68.15], zoom_start=12, control_scale=True)
    if not routes.empty and {"latitud","longitud","parada"}.issubset(routes.columns):
        valid = routes.dropna(subset=["latitud","longitud"])
        for _,r in valid.iterrows():
            folium.CircleMarker([r["latitud"],r["longitud"]], radius=4, tooltip=str(r["parada"])).add_to(m)
    else:
        st.caption("El mapa base está disponible. Los recorridos de transporte aparecerán cuando se carguen coordenadas verificadas.")
    st_folium(m, use_container_width=True, height=500)

with t3:
    st.subheader("Tarifas de referencia")
    st.caption("Importes en bolivianos. Son referencias documentales, no una garantía de que sigan vigentes hoy.")
    if not fares.empty:
        st.dataframe(fares, use_container_width=True, hide_index=True)
    st.markdown("**Fuentes:** normativa municipal de El Alto (RM 100/2025) y publicación municipal de La Paz sobre tarifas desde el 24/12/2025.")
    st.warning("Antes de mostrar un precio como definitivo, verificar la norma vigente con cada municipio.")

with t4:
    st.subheader("Datos incluidos")
    st.markdown("**Conteo histórico de rutas de La Paz (2021)**")
    if not catalog.empty:
        st.dataframe(catalog, use_container_width=True, hide_index=True)
        st.metric("Rutas reportadas en 2021", int(catalog["cantidad_rutas_reportadas"].sum()))
    st.markdown("**Archivo de recorridos**")
    st.write(f"Registros de paradas cargados: {len(routes)}")
    st.caption("El CSV rutas_y_paradas.csv está preparado para incorporar líneas y paradas reales. No rellenar con datos supuestos.")
    st.download_button("Descargar plantilla de rutas y paradas", routes.to_csv(index=False).encode("utf-8-sig"),
                       "rutas_y_paradas_plantilla.csv", "text/csv")

st.divider()
st.caption("RUTA-BOL · Datos abiertos y municipales con fecha y estado de verificación visibles.")
