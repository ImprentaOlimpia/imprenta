import os
import sys
import json
import re
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo

# ==========================================
# 1. CONFIGURACIÓN Y CALENDARIO DE CEUTA
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
MODO_PRUEBA = os.environ.get("MODO_PRUEBA", "false").lower() == "true"
HISTORIAL_FILE = "licitaciones_vistas.json"

ZONA_HORARIA = ZoneInfo("Europe/Madrid")
ahora = datetime.now(ZONA_HORARIA)

# Festivos Nacionales + Festivos Oficiales de la Ciudad Autónoma de Ceuta (2026 - 2027)
FESTIVOS_CEUTA = {
    # 2026
    "2026-01-01", "2026-01-06", "2026-03-20", "2026-04-02", "2026-04-03",
    "2026-05-01", "2026-05-27", "2026-06-13", "2026-08-05", "2026-08-15",
    "2026-09-02", "2026-10-12", "2026-11-02", "2026-12-06", "2026-12-08",
    "2026-12-25",
    # 2027
    "2027-01-01", "2027-01-06", "2027-03-10", "2027-03-25", "2027-03-26",
    "2027-05-01", "2027-05-17", "2027-06-13", "2027-08-05", "2027-09-02",
    "2027-10-12", "2027-11-01", "2027-12-06", "2027-12-08", "2027-12-25"
}

def es_horario_laboral_ceuta():
    """Verifica que sea Lunes-Viernes, entre 08:00 y 22:00, y no sea festivo en Ceuta."""
    if MODO_PRUEBA:
        print(f"[{ahora}] Ejecutando en MODO PRUEBA (ignorando restricción horaria/festivos).")
        return True

    fecha_hoy = ahora.strftime("%Y-%m-%d")
    dia_semana = ahora.weekday()  # 0=Lunes ... 4=Viernes, 5=Sábado, 6=Domingo
    hora_actual = ahora.hour

    if dia_semana >= 5:
        print(f"[{ahora}] Fin de semana. Ejecución omitida.")
        return False
    if fecha_hoy in FESTIVOS_CEUTA:
        print(f"[{ahora}] Día festivo en Ceuta ({fecha_hoy}). Ejecución omitida.")
        return False
    if not (8 <= hora_actual <= 22):
        print(f"[{ahora}] Fuera de horario (08:00-22:00). Ejecución omitida.")
        return False
    return True

# ==========================================
# 2. FILTROS DE UBICACIÓN Y SECTOR
# ==========================================
PALABRAS_CLAVE = [
    "imprenta", "impresión", "impresion", "impresos", "offset",
    "reprografía", "reprografia", "fotocopia", "fotocopias", "copistería", "copisteria",
    "encuadernación", "encuadernacion", "encuadernado",
    "papelería", "papeleria", "material de oficina", "artículos de oficina", "articulos de oficina",
    "artes gráficas", "artes graficas", "serigrafía", "serigrafia",
    "cartelería", "carteleria", "vinilo", "gran formato", "plotter",
    "folletos", "dípticos", "dipticos", "trípticos", "tripticos", "carteles",
    "talonarios", "sobres", "carpetas", "papel", "tóner", "toner", "consumibles informáticos",
    "sellos", "libros", "edición", "edicion", "publicaciones"
]

PREFIJOS_CPV = (
    "22",    # Impresos y productos relacionados
    "3019",  # Equipo y artículos de oficina diversos
    "3012",  # Fotocopiadoras, máquinas offset e impresoras
    "798",   # Servicios de impresión y servicios conexos
    "7952"   # Servicios de reprografía
)

FEEDS_PLACSP = [
    ("Licitación", "https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_643/licitacionesPerfilesContratanteCompleto3.atom"),
    ("Contrato Menor", "https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_1143/contratosMenoresPerfilesContratantes.atom")
]

# ==========================================
# 3. FUNCIONES DE RASTREO Y NOTIFICACIÓN
# ==========================================
def cargar_historial():
    if os.path.exists(HISTORIAL_FILE):
        with open(HISTORIAL_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def guardar_historial(vistas):
    lista = list(vistas)[-3000:]
    with open(HISTORIAL_FILE, "w", encoding="utf-8") as f:
        json.dump(lista, f, indent=2)

def enviar_telegram(mensaje):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: Faltan credenciales TELEGRAM_TOKEN o TELEGRAM_CHAT_ID en GitHub Secrets.")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"Error enviando Telegram: {e}")
        return False

def es_de_ceuta(texto_completo, xml_entry_str):
    if "ES630" in xml_entry_str or "51001" in xml_entry_str or "51002" in xml_entry_str:
        return True
    if re.search(r'\bceuta\b', texto_completo, re.IGNORECASE):
        return True
    return False

def coincide_sector(texto_completo, xml_entry_str):
    cpvs_encontrados = re.findall(r'>(\d{8})<', xml_entry_str)
    for cpv in cpvs_encontrados:
        if cpv.startswith(PREFIJOS_CPV):
            return True, f"CPV {cpv}"

    texto_lower = texto_completo.lower()
    for palabra in PALABRAS_CLAVE:
        if re.search(r'\b' + re.escape(palabra) + r'\b', texto_lower):
            return True, f"Palabra clave: '{palabra}'"

    return False, ""

def procesar_feeds():
    if MODO_PRUEBA:
        enviar_telegram(
            "✅ <b>¡Conexión exitosa!</b>\n\n"
            "Tu monitor de licitaciones para <b>Imprenta, Reprografía y Papelería en Ceuta</b> está activo y funcionando correctamente.\n"
            "⏰ Horario automático: Lunes a Viernes de 08:00 a 22:00 (cada 4h), excluyendo festivos de Ceuta."
        )

    if not es_horario_laboral_ceuta():
        return

    vistas = cargar_historial()
    nuevas_encontradas = 0

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; MonitorLicitacionesCeuta/1.0)"
    }

    for tipo_contrato, url_feed in FEEDS_PLACSP:
        print(f"Consultando feed: {tipo_contrato}...")
        try:
            resp = requests.get(url_feed, headers=headers, timeout=45)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
        except Exception as e:
            print(f"Error descargando {tipo_contrato}: {e}")
            continue

        for entry in root.findall("{http://www.w3.org/2005/Atom}entry"):
            entry_id_el = entry.find("{http://www.w3.org/2005/Atom}id")
            if entry_id_el is None or not entry_id_el.text:
                continue
            entry_id = entry_id_el.text.strip()

            if entry_id in vistas:
                continue

            title_el = entry.find("{http://www.w3.org/2005/Atom}title")
            summary_el = entry.find("{http://www.w3.org/2005/Atom}summary")
            link_el = entry.find("{http://www.w3.org/2005/Atom}link")

            titulo = title_el.text.strip() if (title_el is not None and title_el.text) else "Sin título"
            resumen = summary_el.text.strip() if (summary_el is not None and summary_el.text) else ""
            enlace = link_el.attrib.get("href", "") if link_el is not None else ""

            xml_str = ET.tostring(entry, encoding="unicode")
            texto_busqueda = f"{titulo} {resumen}"

            if es_de_ceuta(texto_busqueda, xml_str):
                es_valido, motivo = coincide_sector(texto_busqueda, xml_str)
                if es_valido:
                    importe_match = re.search(r'TaxExclusiveAmount[^>]*>([\d\.]+)<', xml_str)
                    importe_txt = f"{float(importe_match.group(1)):,.2f} € (sin IVA)" if importe_match else "Ver pliego"

                    mensaje = (
                        f"🖨️ <b>NUEVA LICITACIÓN EN CEUTA ({tipo_contrato.upper()})</b>\n\n"
                        f"📌 <b>Objeto:</b> {titulo}\n"
                        f"💰 <b>Presupuesto:</b> {importe_txt}\n"
                        f"🏷️ <b>Filtro:</b> {motivo}\n"
                        f"📝 <b>Detalle:</b> {resumen[:250]}...\n\n"
                        f"🔗 <a href='{enlace}'>Ver expediente oficial en PLACSP</a>"
                    )
                    if enviar_telegram(mensaje):
                        vistas.add(entry_id)
                        nuevas_encontradas += 1

    guardar_historial(vistas)

    if nuevas_encontradas == 0:
        hora_str = ahora.strftime("%H:%M")
        enviar_telegram(f"ℹ️ <b>Revisión ({hora_str}):</b> No hay ninguna licitación de tu interés.")

    print(f"Finalizado. Nuevas licitaciones notificadas: {nuevas_encontradas}")

if __name__ == "__main__":
    procesar_feeds()
