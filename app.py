import json
import os
import re
import urllib.parse
import requests
from bs4 import BeautifulSoup
import streamlit as st
from playwright.sync_api import sync_playwright

# -----------------------------------------------------------------------------
# CONFIGURACIÓN DE PÁGINA Y ESTILOS
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Portal Ejecutivo de Empleos • Chile",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    
""", unsafe_allow_html=True)

DATA_FILE = "postulaciones.json"

REGIONES_CHILE = [
    "Todas", "Arica y Parinacota", "Tarapacá", "Antofagasta", "Atacama",
    "Coquimbo", "Valparaíso", "Región Metropolitana", "O'Higgins", "Maule",
    "Ñuble", "Biobío", "La Araucanía", "Los Ríos", "Los Lagos", "Aysén", "Magallanes"
]

PALABRAS_CLAVE_CV = [
    "coordinador", "coordinacion", "logistica", "operaciones", "supply chain",
    "inventarios", "bodega", "kpis", "sap", "power bi", "despacho", "stock", "flujo",
    "analista", "supervisión", "distribución", "prevencion", "riesgos"
]

# -----------------------------------------------------------------------------
# FUNCIONES DE PERSISTENCIA Y UTILIDADES
# -----------------------------------------------------------------------------
def cargar_datos():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def guardar_datos(datos):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=4)

def calcular_match_perfil(texto):
    texto_l = texto.lower()
    coincidencias = sum(1 for kw in PALABRAS_CLAVE_CV if kw in texto_l)
    porcentaje = int((coincidencias / len(PALABRAS_CLAVE_CV)) * 100)
    return min(100, max(45, porcentaje + 40))

def normalizar_region(texto_completo):
    t = texto_completo.lower()
    if "arica" in t: return "Arica y Parinacota"
    if "tarapacá" in t or "tarapaca" in t or "iquique" in t: return "Tarapacá"
    if "antofagasta" in t or "calama" in t: return "Antofagasta"
    if "atacama" in t or "copiapó" in t or "copiapo" in t: return "Atacama"
    if "coquimbo" in t or "la serena" in t: return "Coquimbo"
    if "valparaíso" in t or "valparaiso" in t or "viña" in t or "san antonio" in t: return "Valparaíso"
    if "ohiggins" in t or "o'higgins" in t or "rancagua" in t or "san fernando" in t: return "O'Higgins"
    if "maule" in t or "talca" in t or "curicó" in t or "curico" in t or "linares" in t: return "Maule"
    if "ñuble" in t or "nuble" in t or "chillán" in t or "chillan" in t: return "Ñuble"
    if "biobío" in t or "biobio" in t or "concepción" in t or "concepcion" in t or "talcahuano" in t or "los ángeles" in t: return "Biobío"
    if "araucanía" in t or "araucania" in t or "temuco" in t: return "La Araucanía"
    if "los ríos" in t or "los rios" in t or "valdivia" in t: return "Los Ríos"
    if "los lagos" in t or "puerto montt" in t or "osorno" in t: return "Los Lagos"
    if "aysén" in t or "aysen" in t or "coyhaique" in t: return "Aysén"
    if "magallanes" in t or "punta arenas" in t: return "Magallanes"
    return "Región Metropolitana"

# -----------------------------------------------------------------------------
# MOTORES DE EXTRACCIÓN ROBUSTOS
# -----------------------------------------------------------------------------
def buscar_chiletrabajos_directo(termino, max_paginas, status_container):
    ofertas = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept-Language": "es-ES,es;q=0.9"
    }
    
    clean_term = termino.strip().lower().replace(" ", "-")
    
    for p in range(1, max_paginas + 1):
        if p == 1:
            urls_probables = [
                f"https://www.chiletrabajos.cl/trabajos/{clean_term}",
                f"https://www.chiletrabajos.cl/encuentra-un-empleo/?2={urllib.parse.quote_plus(termino)}&filterSearch=Buscar"
            ]
        else:
            urls_probables = [
                f"https://www.chiletrabajos.cl/trabajos/{clean_term}/{p}",
                f"https://www.chiletrabajos.cl/encuentra-un-empleo/?2={urllib.parse.quote_plus(termino)}&p={p}"
            ]
            
        status_container.info(f"🔎 Escaneando **Chiletrabajos.cl** (Página {p} de {max_paginas})...")
        
        pagina_exitosa = False
        for url in urls_probables:
            try:
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, 'html.parser')
                
                # Búsqueda por enlaces específicos de oferta /trabajo/
                enlaces_oferta = soup.find_all('a', href=re.compile(r'/trabajo/'))
                if not enlaces_oferta:
                    continue

                encontradas = 0
                for a in enlaces_oferta:
                    link = a.get('href', '')
                    titulo = a.get_text(strip=True)

                    if not link or len(titulo) < 4 or "Ver más" in titulo:
                        continue

                    if not link.startswith("http"):
                        link = "https://www.chiletrabajos.cl" + link

                    padre = a.find_parent('div') or a.find_parent('tr') or a.parent
                    texto_padre = padre.get_text() if padre else titulo

                    reg = normalizar_region(texto_padre)
                    
                    sueldo = "No especificado"
                    match_s = re.search(r"\$\s?([\d\.]+)", texto_padre)
                    if match_s:
                        sueldo = match_s.group(0)

                    if not any(o["url"] == link for o in ofertas):
                        ofertas.append({
                            "cargo": titulo.split("\n")[0].strip(),
                            "portal": "Chiletrabajos",
                            "region": reg,
                            "fecha": "Reciente",
                            "sueldo": sueldo,
                            "match": calcular_match_perfil(f"{titulo} {texto_padre}"),
                            "url": link,
                            "estado": "Pendiente"
                        })
                        encontradas += 1

                if encontradas > 0:
                    pagina_exitosa = True
                    break

            except Exception:
                continue

        if not pagina_exitosa and p > 1:
            break

    return ofertas

def buscar_trabajando_playwright(termino, max_paginas, status_container):
    ofertas = []
    termino_enc = urllib.parse.quote(termino)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768}
        )
        page = context.new_page()
        page.route("**/*.{png,jpg,jpeg,svg,gif,woff,woff2}", lambda route: route.abort())

        for p_num in range(1, max_paginas + 1):
            url = f"https://www.trabajando.cl/ofertas-trabajo/{termino_enc}?pagina={p_num}"
            status_container.info(f"🔎 Escaneando **Trabajando.cl** (Página {p_num} de {max_paginas})...")

            try:
                page.goto(url, timeout=20000, wait_until="domcontentloaded")
                page.wait_for_timeout(1500)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2);")

                elementos = page.query_selector_all("a[href*='/oferta/'], a[href*='/ofertas-trabajo/']")
                if not elementos:
                    break

                encontradas = 0
                for el in elementos:
                    try:
                        link = el.get_attribute("href")
                        titulo = el.inner_text().strip()

                        if link and len(titulo) > 3:
                            if not link.startswith("http"):
                                link = "https://www.trabajando.cl" + link

                            if link.rstrip("/") in ["https://www.trabajando.cl/ofertas-trabajo", "https://www.trabajando.cl"]:
                                continue

                            padre = el.evaluate_handle("node => node.closest('article') || node.closest('div') || node.parentElement")
                            texto_padre = padre.inner_text() if padre else titulo
                            reg = normalizar_region(texto_padre)

                            sueldo = "No especificado"
                            match_s = re.search(r"\$\s?([\d\.]+)", texto_padre)
                            if match_s:
                                sueldo = match_s.group(0)

                            if not any(o["url"] == link for o in ofertas):
                                ofertas.append({
                                    "cargo": titulo.split("\n")[0].strip(),
                                    "portal": "Trabajando.cl",
                                    "region": reg,
                                    "fecha": "Reciente",
                                    "sueldo": sueldo,
                                    "match": calcular_match_perfil(f"{titulo} {texto_padre}"),
                                    "url": link,
                                    "estado": "Pendiente"
                                })
                                encontradas += 1
                    except Exception:
                        continue

                if encontradas == 0 and p_num > 1:
                    break
            except Exception:
                break

        browser.close()

    return ofertas

def realizar_busqueda_exhaustiva(puesto_busqueda, max_paginas=6):
    termino = puesto_busqueda.strip()
    if not termino:
        termino = "logistica"

    status_container = st.empty()

    # Extracción de Chiletrabajos
    ofertas_chile = buscar_chiletrabajos_directo(termino, max_paginas, status_container)
    
    # Extracción de Trabajando
    ofertas_trabajando = buscar_trabajando_playwright(termino, max_paginas, status_container)

    status_container.empty()
    
    # Consolidar y remover duplicados por URL
    resultado_final = []
    urls_vistas = set()
    
    for item in ofertas_chile + ofertas_trabajando:
        if item["url"] not in urls_vistas:
            urls_vistas.add(item["url"])
            resultado_final.append(item)

    return resultado_final

def abrir_oferta_en_navegador(url_oferta):
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page = browser.new_page()
            page.goto(url_oferta, timeout=30000)
            page.wait_for_timeout(4000)
            browser.close()
            return True
    except Exception as e:
        st.error(f"No se pudo abrir la oferta: {str(e)}")
        return False

# -----------------------------------------------------------------------------
# INTERFAZ PRINCIPAL DE USUARIO
# -----------------------------------------------------------------------------
st.title("💼 Portal Ejecutivo de Empleos • Chile")
st.markdown("Buscador unificado multicanal en tiempo real para **Chiletrabajos.cl** y **Trabajando.cl**.")

ofertas = cargar_datos()

# BARRA LATERAL
with st.sidebar:
    st.header("🎯 Nueva Búsqueda")
    puesto_input = st.text_input("📌 Cargo o área de trabajo:", value="Coordinador Logistico")
    max_pags = st.slider("📄 Páginas a escanear por portal:", min_value=1, max_value=10, value=5)
    
    col_b1, col_b2 = st.columns([3, 1])
    with col_b1:
        btn_buscar = st.button("🚀 Buscar Ofertas", use_container_width=True)
    with col_b2:
        if st.button("🔄", help="Limpiar búsquedas guardadas"):
            guardar_datos([])
            st.rerun()

    if btn_buscar:
        with st.spinner("Ejecutando motores de extracción en vivo..."):
            nuevas = realizar_busqueda_exhaustiva(puesto_input, max_paginas=max_pags)
            guardar_datos(nuevas)
            st.success(f"¡Escaneo finalizado! Se encontraron {len(nuevas)} ofertas únicas.")
            st.rerun()

    st.divider()
    st.subheader("⚙ Filtros y Búsqueda Rápida")
    filtro_texto = st.text_input("🔍 Filtrar en resultados por palabra:")
    filtro_portal = st.selectbox("🌐 Portal de Origen:", ["Todos los Portales", "Chiletrabajos", "Trabajando.cl"])
    filtro_region = st.selectbox("📍 Región:", REGIONES_CHILE)
    filtro_estado = st.selectbox("📌 Estado:", ["Todas", "Pendientes", "Revisadas"])
    filtro_match = st.slider("📊 Compatibilidad Mínima (%):", min_value=0, max_value=100, value=30, step=5)

# APLICACIÓN DE FILTROS EN RESULTADOS
ofertas_filtradas = ofertas

if filtro_texto:
    txt_l = filtro_texto.lower()
    ofertas_filtradas = [o for o in ofertas_filtradas if txt_l in o.get("cargo", "").lower() or txt_l in o.get("region", "").lower()]

if filtro_portal != "Todos los Portales":
    ofertas_filtradas = [o for o in ofertas_filtradas if o.get("portal") == filtro_portal]

if filtro_region != "Todas":
    ofertas_filtradas = [o for o in ofertas_filtradas if o.get("region") == filtro_region]

if filtro_estado == "Pendientes":
    ofertas_filtradas = [o for o in ofertas_filtradas if o.get("estado", "Pendiente") == "Pendiente"]
elif filtro_estado == "Revisadas":
    ofertas_filtradas = [o for o in ofertas_filtradas if o.get("estado") == "Revisado"]

ofertas_filtradas = [o for o in ofertas_filtradas if o.get("match", 50) >= filtro_match]
ofertas_filtradas.sort(key=lambda x: x.get("match", 0), reverse=True)

# METRICAS PRINCIPALES
m1, m2, m3, m4 = st.columns(4)
m1.metric("Ofertas Encontradas", len(ofertas_filtradas))
m2.metric("Chiletrabajos", sum(1 for o in ofertas_filtradas if o.get("portal") == "Chiletrabajos"))
m3.metric("Trabajando.cl", sum(1 for o in ofertas_filtradas if o.get("portal") == "Trabajando.cl"))

match_promedio = int(sum(o.get("match", 0) for o in ofertas_filtradas) / len(ofertas_filtradas)) if ofertas_filtradas else 0
m4.metric("Match Promedio", f"{match_promedio}%")

st.divider()

# RESULTADOS PAGINADOS
st.subheader(f"📋 Ofertas Laborales Disponibles ({len(ofertas_filtradas)})")

if not ofertas_filtradas:
    st.info("💡 Ingresa el término de búsqueda en la barra lateral y presiona **🚀 Buscar Ofertas**.")
else:
    OFERTAS_POR_PAGINA = 10
    total_paginas = max(1, (len(ofertas_filtradas) + OFERTAS_POR_PAGINA - 1) // OFERTAS_POR_PAGINA)
    
    c_pag1, c_pag2 = st.columns([2, 8])
    with c_pag1:
        pagina_actual = st.number_input("Página:", min_value=1, max_value=total_paginas, value=1, step=1)
    with c_pag2:
        st.write(f"Mostrando página {pagina_actual} de {total_paginas}")

    inicio = (pagina_actual - 1) * OFERTAS_POR_PAGINA
    fin = inicio + OFERTAS_POR_PAGINA
    ofertas_pagina = ofertas_filtradas[inicio:fin]

    for idx, oferta in enumerate(ofertas_pagina):
        idx_global = inicio + idx
        match_val = oferta.get("match", 50)
        portal_nombre = oferta.get("portal", "Web")
        badge_class = "badge-portal-chiletrabajos" if portal_nombre == "Chiletrabajos" else "badge-portal-trabajando"

        with st.container():
            c1, c2, c3, c4 = st.columns([5, 2, 2, 2])

            with c1:
                st.markdown(f"### {oferta.get('cargo', 'Oferta Laboral')}")
                reg_txt = oferta.get('region', 'R. Metropolitana')
                st.markdown(f"{portal_nombre}    📍 **Región:** {reg_txt}", unsafe_allow_html=True)
                
                if oferta.get('sueldo') != "No especificado":
                    sueldo_txt = oferta.get('sueldo')
                    st.markdown(f"💰 **Sueldo informado:** {sueldo_txt}", unsafe_allow_html=True)

            with c2:
                st.markdown(f"**Compatibilidad:** **{match_val}%**")
                st.progress(match_val / 100)

            with c3:
                est = oferta.get("estado", "Pendiente")
                if est == "Revisado":
                    st.info("✅ Revisado")
                else:
                    st.warning("⏳ Pendiente")

            with c4:
                if st.button("🚀 Ver Oferta", key=f"btn_abrir_{idx_global}", use_container_width=True):
                    abrir_oferta_en_navegador(oferta.get("url"))
                    for o in ofertas:
                        if o.get("url") == oferta.get("url"):
                            o["estado"] = "Revisado"
                    guardar_datos(ofertas)
                    st.rerun()

        st.divider()