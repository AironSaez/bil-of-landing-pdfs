# -*- coding: utf-8 -*-
"""
================================================================================
 GENERADOR DE BILLS OF LADING HIPER-REALISTAS (6 CASUÍSTICAS)
================================================================================

Genera 50 Bills of Lading sintéticos en PDF (WeasyPrint) a partir de 6 plantillas
master hiper-realistas (CSS Grid, cajas negras, Courier), cada una representando
una casuística distinta para entrenar modelos:

    master_exportacion.html   Salida FCL (inglés, internacional)
    master_importacion.html   Ingreso LCL (español, formato BL 28H/29)
    master_transito.html      Tránsito a Bolivia (glosa obligatoria)
    master_peligrosa.html     Carga peligrosa IMO (clase, UN, EMS, emergencia)
    master_transbordo.html    Transbordo multimodal (pre-carriage, varios cont.)
    master_reefer.html        Carga refrigerada (temperatura, ventilación)

Coherencia garantizada (sin datos "naive" de Faker):
  * Direcciones: calle de Faker + pares Comuna/País cerrados. Nunca se mezcla
    una ciudad chilena con un país extranjero.
  * Cargas emparejadas: Cobre Refinado -> peso alto, sin IMO.
    Nitrato de Amonio -> IMO 5.1 / UN1942 obligatorios.
  * Observaciones reales: FREIGHT PREPAID, CLEAN ON BOARD, 14 DAYS FREE TIME...
  * Variedad: cada una de las 6 plantillas aparece al menos 8 veces en el lote,
    con puertos, navieras, cargas, contenedores y RUT distintos.

Uso:
    python main.py                # genera 50 PDF + 50 JSON en output/
    python main.py --count 10     # lote más pequeño
    python main.py --seed 7       # reproducible
================================================================================
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

from faker import Faker
from faker.providers import BaseProvider
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

# ------------------------------------------------------------------------------
# Configuración
# ------------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
OUTPUT_DIR = BASE_DIR / "output"

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bl_generator")
logging.getLogger("weasyprint").setLevel(logging.WARNING)
logging.getLogger("weasyprint.progress").setLevel(logging.WARNING)
logging.getLogger("fontTools").setLevel(logging.WARNING)
logging.getLogger("fontTools.subset").setLevel(logging.WARNING)


# ------------------------------------------------------------------------------
# LISTAS CERRADAS (coherencia geográfica / logística)
# ------------------------------------------------------------------------------

CIUDADES_CHILENAS = [
    "San Antonio", "Valparaíso", "Santiago", "Iquique", "Antofagasta",
    "Arica", "Concepción", "Puerto Montt", "La Serena", "Viña del Mar",
]
CIUDADES_EXTRANJERAS = [
    ("Long Beach", "USA"), ("Los Angeles", "USA"), ("Miami", "USA"),
    ("Shanghai", "China"), ("Busan", "Corea del Sur"), ("Rotterdam", "Países Bajos"),
    ("Hamburg", "Alemania"), ("Valencia", "España"), ("Buenos Aires", "Argentina"),
    ("Callao", "Perú"), ("Santos", "Brasil"), ("Guayaquil", "Ecuador"),
    ("Kaohsiung", "Taiwán"), ("New York", "USA"), ("Hong Kong", "China"),
]
CIUDADES_BOLIVIA = ["La Paz", "Santa Cruz de la Sierra", "Oruro", "Cochabamba"]

NAVIERAS = [
    "PACIFIC STAR LINE", "ANDES CARRIER CO.", "TRANSOCEAN CHILE S.A.",
    "MAGELLAN MARITIME", "SOUTHERN CROSS SHIPPING", "ATACAMA OCEAN FREIGHT",
]

# Puertos con UN/LOCODE (códigos del protocolo aduanero)
PUERTOS_NACIONALES = [
    {"nombre": "San Antonio", "locode": "CLSAI"},
    {"nombre": "Valparaíso", "locode": "CLVAP"},
    {"nombre": "Iquique", "locode": "CLIQQ"},
    {"nombre": "Antofagasta", "locode": "CLANF"},
    {"nombre": "Arica", "locode": "CLARI"},
    {"nombre": "San Vicente", "locode": "CLSVE"},
]
PUERTOS_EXTRANJEROS = [
    {"nombre": "Long Beach, USA", "locode": "USLGB"},
    {"nombre": "Shanghai, China", "locode": "CNSHA"},
    {"nombre": "Rotterdam, Netherlands", "locode": "NLRTM"},
    {"nombre": "Buenos Aires, Argentina", "locode": "ARBUE"},
    {"nombre": "Callao, Perú", "locode": "PECLL"},
    {"nombre": "Santos, Brasil", "locode": "BRSSZ"},
    {"nombre": "Kaohsiung, Taiwan", "locode": "TWKHH"},
    {"nombre": "Miami, USA", "locode": "USMIA"},
    {"nombre": "Busan, Corea del Sur", "locode": "KRPUS"},
    {"nombre": "Hamburg, Alemania", "locode": "DEHAM"},
    {"nombre": "Valencia, España", "locode": "ESVLC"},
    {"nombre": "Guayaquil, Ecuador", "locode": "ECGYE"},
]
PUERTOS_TRANSBORDO = [
    {"nombre": "Manzanillo, Panamá", "locode": "PAMIT"},
    {"nombre": "Cartagena, Colombia", "locode": "COCTG"},
    {"nombre": "Buenaventura, Colombia", "locode": "COBUN"},
]

PRE_CARRIAGES = ["TRUCK - TRANS-CHILE", "RAIL - FEPASA", "TRUCK - SANTIAGO HUB", "NA"]
BANDERAS = ["CL", "PA", "BS", "LR", "HK", "SG", "GR"]
TIPOS_CONTENEDOR = ["45G0", "42G1", "22G1", "22T1", "45R1", "45P1", "22U1", "45U1"]
INCOTERMS = ["FOB", "CIF", "EXW", "FCA", "CPT", "DAP", "CFR"]

# Cargas emparejadas: tipo = ordinaria | peligrosa | reefer
CARGAS = [
    {"nombre": "Cobre Refinado", "tipo": "ordinaria",
     "descripcion": "Cátodos de cobre refinado grado A (LME)",
     "peso_min": 15_000.0, "peso_max": 22_000.0, "vol_min": 18.0, "vol_max": 26.0,
     "unidad": "PALLETS", "imo": None, "onu": None},
    {"nombre": "Vino Embotellado", "tipo": "ordinaria",
     "descripcion": "Vino tinto embotellado en cajas de cartón (12x750ml)",
     "peso_min": 10_000.0, "peso_max": 14_000.0, "vol_min": 20.0, "vol_max": 28.0,
     "unidad": "CAJAS", "imo": None, "onu": None},
    {"nombre": "Maquinaria Minera", "tipo": "ordinaria",
     "descripcion": "Maquinaria y componentes para minería (no peligroso)",
     "peso_min": 17_000.0, "peso_max": 26_000.0, "vol_min": 20.0, "vol_max": 30.0,
     "unidad": "PIEZAS", "imo": None, "onu": None},
    {"nombre": "Textiles", "tipo": "ordinaria",
     "descripcion": "Prendas de vestir y textiles en cajas (carga liviana)",
     "peso_min": 3_000.0, "peso_max": 6_000.0, "vol_min": 15.0, "vol_max": 22.0,
     "unidad": "CAJAS", "imo": None, "onu": None},
    {"nombre": "Aceite de Oliva", "tipo": "ordinaria",
     "descripcion": "Aceite de oliva extra virgen en tambores metálicos",
     "peso_min": 7_000.0, "peso_max": 11_000.0, "vol_min": 9.0, "vol_max": 14.0,
     "unidad": "TAMBORES", "imo": None, "onu": None},
    {"nombre": "Nitrato de Amonio", "tipo": "peligrosa",
     "descripcion": "Nitrato de amonio grado fertilizante (FGAN)",
     "peso_min": 9_000.0, "peso_max": 12_000.0, "vol_min": 14.0, "vol_max": 18.0,
     "unidad": "BULTOS", "imo": "5.1", "onu": "UN1942",
     "nombre_embarque": "AMMONIUM NITRATE, FERTILIZER", "grupo_embalaje": "III",
     "punto_inflamacion": "N/A", "ems": "F-A, S-Q", "contaminante_marino": "NO"},
    {"nombre": "Gasolina (IBC)", "tipo": "peligrosa",
     "descripcion": "Gasolina en contenedores IBC (líquido inflamable)",
     "peso_min": 6_000.0, "peso_max": 9_000.0, "vol_min": 8.0, "vol_max": 12.0,
     "unidad": "IBC", "imo": "3", "onu": "UN1203",
     "nombre_embarque": "GASOLINE", "grupo_embalaje": "II",
     "punto_inflamacion": "-40°C c.c.", "ems": "F-E, S-E", "contaminante_marino": "NO"},
    {"nombre": "Peróxido de Hidrógeno", "tipo": "peligrosa",
     "descripcion": "Peróxido de hidrógeno solución acuosa (oxidante)",
     "peso_min": 7_000.0, "peso_max": 10_000.0, "vol_min": 10.0, "vol_max": 14.0,
     "unidad": "TAMBORES", "imo": "5.1", "onu": "UN2014",
     "nombre_embarque": "HYDROGEN PEROXIDE, AQUEOUS SOLUTION", "grupo_embalaje": "II",
     "punto_inflamacion": "N/A (oxidante)", "ems": "F-A, S-Q", "contaminante_marino": "NO"},
    {"nombre": "Baterías de Litio", "tipo": "peligrosa",
     "descripcion": "Baterías de ion-litio embaladas (mercancía peligrosa clase 9)",
     "peso_min": 4_000.0, "peso_max": 7_000.0, "vol_min": 8.0, "vol_max": 12.0,
     "unidad": "CAJAS", "imo": "9", "onu": "UN3480",
     "nombre_embarque": "LITHIUM ION BATTERIES", "grupo_embalaje": "II",
     "punto_inflamacion": "N/A", "ems": "F-A, S-I", "contaminante_marino": "NO"},
    {"nombre": "Harina de Pescado", "tipo": "peligrosa",
     "descripcion": "Harina de pescado estabilizada (auto-calentamiento)",
     "peso_min": 8_000.0, "peso_max": 11_000.0, "vol_min": 13.0, "vol_max": 17.0,
     "unidad": "SACOS", "imo": "9", "onu": "UN2216",
     "nombre_embarque": "FISH MEAL (STABILIZED)", "grupo_embalaje": "III",
     "punto_inflamacion": "N/A", "ems": "F-A, S-I", "contaminante_marino": "NO"},
    {"nombre": "Cerezas Frescas", "tipo": "reefer",
     "descripcion": "Cerezas frescas refrigeradas (1°C) para exportación",
     "peso_min": 8_000.0, "peso_max": 11_000.0, "vol_min": 16.0, "vol_max": 22.0,
     "unidad": "PALLETS", "imo": None, "onu": None,
     "temperatura": "+1°C", "ventilacion": "25 CFM", "humedad": "85-90%"},
    {"nombre": "Salmón Atlántico Congelado", "tipo": "reefer",
     "descripcion": "Salmón atlántico congelado en cajas (bloque IQF)",
     "peso_min": 9_000.0, "peso_max": 12_500.0, "vol_min": 17.0, "vol_max": 23.0,
     "unidad": "CAJAS", "imo": None, "onu": None,
     "temperatura": "-20°C", "ventilacion": "CLOSED", "humedad": "—"},
    {"nombre": "Cítricos Frescos", "tipo": "reefer",
     "descripcion": "Cítricos frescos (naranjas/limones) con ventilación forzada",
     "peso_min": 9_000.0, "peso_max": 12_000.0, "vol_min": 18.0, "vol_max": 24.0,
     "unidad": "PALLETS", "imo": None, "onu": None,
     "temperatura": "+5°C", "ventilacion": "60 CFM", "humedad": "85%"},
]

# Observaciones logísticas reales (nunca "Lorem Ipsum")
OBSERVACIONES = [
    "FREIGHT PREPAID",
    "14 DAYS FREE TIME DEMURRAGE",
    "CLEAN ON BOARD",
    "SHIPPER'S LOAD, STOW AND COUNT",
    "CY/CY - FCL/FCL",
    "TEMP CONTROL: +1°C (REEFER)",
    "PORT OF LOADING CY - DOOR DELIVERY",
    "MERCHANT'S STOWAGE",
]

# Escenarios por plantilla
PLANTILLAS = {
    "master_exportacion.html": {
        "sentido": ["S"], "servicios": ["FCL/FCL"],
        "cargas": ["ordinaria", "reefer"], "min_por_lote": 8},
    "master_importacion.html": {
        "sentido": ["I"], "servicios": ["LCL/LCL"],
        "cargas": ["ordinaria"], "min_por_lote": 8},
    "master_transito.html": {
        "sentido": ["TR"], "servicios": ["FCL/FCL", "LCL/LCL"],
        "cargas": ["ordinaria"], "min_por_lote": 8},
    "master_peligrosa.html": {
        "sentido": ["I", "S"], "servicios": ["FCL/FCL"],
        "cargas": ["peligrosa"], "min_por_lote": 8},
    "master_transbordo.html": {
        "sentido": ["TRB"], "servicios": ["FCL/FCL"],
        "cargas": ["ordinaria", "reefer"], "min_por_lote": 8},
    "master_reefer.html": {
        "sentido": ["S", "I"], "servicios": ["FCL/FCL"],
        "cargas": ["reefer"], "min_por_lote": 8},
}

TERMS = (
    "RECEIVED by the Carrier from the Shipper in apparent good order and condition "
    "the total number or quantity of Containers or other packages stated in this "
    "Bill of Lading, subject to the terms and conditions of the Carrier's Tariff. "
    "Carrier's liability limited per the Hague-Visby Rules."
)


# ------------------------------------------------------------------------------
# 1) PROVEEDORES PERSONALIZADOS DE FAKER
# ------------------------------------------------------------------------------

def rut_digito_verificador(cuerpo: int) -> str:
    """Dígito verificador de un RUT chileno (módulo 11)."""
    total, factor = 0, 2
    for ch in reversed(str(cuerpo)):
        total += int(ch) * factor
        factor = 2 if factor == 7 else factor + 1
    dv = 11 - (total % 11)
    return "0" if dv == 11 else ("K" if dv == 10 else str(dv))


class RUTProvider(BaseProvider):
    """RUT chileno válido con formato XX.XXX.XXX-K."""

    def rut(self) -> str:
        cuerpo = self.generator.random.randint(1_000_000, 99_999_999)
        dv = rut_digito_verificador(cuerpo)
        return f"{cuerpo:,.0f}".replace(",", ".") + f"-{dv}"


def _valor_iso_letra(ch: str) -> int:
    v = ord(ch) - ord("A") + 10
    for mult in (11, 22, 33):
        if v >= mult:
            v += 1
    return v


def contenedor_digito_verificador(owner_serial: str) -> int:
    """Dígito verificador ISO 6346 de un contenedor (owner_serial = 4 letras + 6 dígitos)."""
    total = sum(
        (_valor_iso_letra(ch) if ch.isalpha() else int(ch)) * (2 ** i)
        for i, ch in enumerate(owner_serial)
    )
    dv = total % 11
    return 0 if dv == 10 else dv


class ContainerProvider(BaseProvider):
    """Número de contenedor marítimo ISO 6346 válido (XXXU#######)."""

    LETRAS = "ABCDEFGHJKLMNPQRSTUVWXYZ"

    def container_number(self) -> str:
        letras = "".join(self.generator.random.choices(self.LETRAS, k=3)) + "U"
        serial = f"{self.generator.random.randint(0, 999999):06d}"
        return f"{letras}{serial}{contenedor_digito_verificador(letras + serial)}"


# ------------------------------------------------------------------------------
# 2) GENERADORES CONTROLADOS
# ------------------------------------------------------------------------------

def _direccion(fake: Faker, chile: bool = False, extranjera: bool = False,
               bolivia: bool = False) -> dict:
    """Calle falsa de Faker + par Comuna/País coherente (jamás mezclado)."""
    if bolivia:
        ciudad = random.choice(CIUDADES_BOLIVIA)
        pais = "Bolivia"
    elif chile:
        ciudad = random.choice(CIUDADES_CHILENAS)
        pais = "Chile"
    elif extranjera:
        ciudad, pais = random.choice(CIUDADES_EXTRANJERAS)
    else:
        if random.random() < 0.5:
            ciudad = random.choice(CIUDADES_CHILENAS)
            pais = "Chile"
        else:
            ciudad, pais = random.choice(CIUDADES_EXTRANJERAS)
    return {"calle": fake.street_address(), "ciudad": ciudad, "pais": pais}


def _parte(fake: Faker, chile: bool = False, extranjera: bool = False,
           bolivia: bool = False, con_rut: bool = False) -> dict:
    """Empresa ficticia con dirección coherente y contactos."""
    data = {"nombre": fake.company(), **_direccion(fake, chile=chile,
                                                   extranjera=extranjera,
                                                   bolivia=bolivia)}
    if con_rut:
        data["rut"] = fake.rut()
    if random.random() < 0.6:
        data["fono"] = fake.phone_number()
    if random.random() < 0.4:
        data["correo"] = fake.email()
    return data


def _generar_carga(fake: Faker, tipos: list, items: int) -> dict:
    """
    Selecciona UNA carga emparejada dentro de los tipos permitidos y reparte su
    peso/volumen en `items` ítems. Devuelve dict con items + totales + metadatos.
    """
    pool = [c for c in CARGAS if c.get("tipo") in tipos]
    c = random.choice(pool)
    items_out, total_bultos, total_peso, total_volumen = [], 0, 0.0, 0.0
    for i in range(items):
        bultos = random.randint(6, 20)
        peso = round(random.uniform(c["peso_min"], c["peso_max"]) / items, 2)
        volumen = round(random.uniform(c["vol_min"], c["vol_max"]) / items, 2)
        items_out.append({
            "marcas": f"{fake.lexify('????-????')} / N° {i + 1:02d}",
            "bultos": bultos, "unidad": c["unidad"],
            "descripcion": c["descripcion"],
            "peso": peso, "volumen": volumen,
            "imo": c["imo"], "onu": c["onu"],
            "obs_item": random.choice(["STC", "N/M", "FCL", ""]),
        })
        total_bultos += bultos
        total_peso += peso
        total_volumen += volumen
    return {
        "items": items_out,
        "bultos_total": total_bultos,
        "peso_total": round(total_peso, 2),
        "volumen_total": round(total_volumen, 2),
        "carga": c,
    }


def _contenedor(fake: Faker, status: str, peso: float) -> dict:
    return {
        "numero": fake.container_number(),
        "tipo": random.choice(TIPOS_CONTENEDOR),
        "sello": fake.numerify("#######"),
        "status": status,
        "peso": round(peso, 1),
        "operador": random.choice(["SHIPPER OWNER", "CARRIER OWNED", "LEASED"]),
    }


def _contenedores(fake: Faker, cantidad: int, peso_total: float,
                  bultos_total: int, volumen_total: float, status: str) -> list:
    """Distribuye los totales en `cantidad` contenedores (sumas cuadradas)."""
    contenedores = []
    r_peso, r_bultos, r_vol = peso_total, bultos_total, volumen_total
    for i in range(cantidad):
        ultimo = i == cantidad - 1
        share = 1.0 / (cantidad - i) if not ultimo else 1.0
        peso = round(r_peso * share, 1) if not ultimo else round(r_peso, 1)
        bultos = int(round(r_bultos * share)) if not ultimo else r_bultos
        vol = round(r_vol * share, 2) if not ultimo else round(r_vol, 2)
        contenedores.append({
            **_contenedor(fake, status, peso),
            "bultos": bultos, "volumen": vol,
        })
        if not ultimo:
            r_peso -= peso
            r_bultos -= bultos
            r_vol -= vol
    return contenedores


def _observaciones() -> str:
    return " / ".join(random.sample(OBSERVACIONES, k=random.randint(1, 3)))


def _fecha(fake: Faker, dias_atras: int) -> str:
    d = datetime.now() - timedelta(days=fake.random_int(min=0, max=dias_atras))
    return d.strftime("%d-%b-%Y").upper()


# ------------------------------------------------------------------------------
# 3) CONSTRUCTOR DE DATOS POR ESCENARIO
# ------------------------------------------------------------------------------

def build_bl_data(fake: Faker, template_name: str, bl_id: int) -> dict:
    cfg = PLANTILLAS[template_name]
    sentido = random.choice(cfg["sentido"])
    tipo_servicio = random.choice(cfg["servicios"])
    cond_transporte = random.choice(["PP", "DOOR/DOOR", "CY/CY", "CFS/CFS"])

    # --- Carga (coherente con la casuística de la plantilla) ------------------
    carga_res = _generar_carga(fake, cfg["cargas"], items=random.randint(1, 2))
    carga, bultos_total = carga_res["items"], carga_res["bultos_total"]
    peso_total, volumen_total = carga_res["peso_total"], carga_res["volumen_total"]
    c = carga_res["carga"]
    es_peligrosa = bool(c.get("imo"))
    es_reefer = c.get("tipo") == "reefer"

    status_cont = tipo_servicio if random.random() < 0.85 else "EMPTY"
    contenedor = _contenedor(fake, status_cont, peso_total)

    # --- Rutas según sentido de operación --------------------------------------
    if sentido == "S":      # Exportación: carga en puerto nacional
        port_loading = random.choice(PUERTOS_NACIONALES)
        port_discharge = random.choice(PUERTOS_EXTRANJEROS)
        lugar_recepcion = random.choice(["SANTIAGO HUB INTERMODAL",
                                         port_loading["nombre"] + " CY"])
    else:                   # I / TR / TRB: descarga en puerto nacional
        port_loading = random.choice(PUERTOS_EXTRANJEROS)
        if template_name == "master_transito.html":
            port_discharge = random.choice(
                [p for p in PUERTOS_NACIONALES if p["locode"] in ("CLARI", "CLIQQ")])
        else:
            port_discharge = random.choice(PUERTOS_NACIONALES)
        lugar_recepcion = port_loading["nombre"] + " CY"

    puerto_transbordo = random.choice(PUERTOS_TRANSBORDO)
    destino_final = (
        random.choice(CIUDADES_BOLIVIA)
        if template_name == "master_transito.html"
        else random.choice(PUERTOS_EXTRANJEROS)["nombre"]
    )
    transbordos = (
        "—"
        if random.random() < 0.5
        else f"{puerto_transbordo['locode']} / {puerto_transbordo['nombre']}"
    )

    # --- Partes por escenario ----------------------------------------------------
    if template_name == "master_importacion.html":
        embarcador = _parte(fake, extranjera=True)
        consignatario = _parte(fake, chile=True, con_rut=True)
        almacenista = _parte(fake, chile=True, con_rut=True)
        almacenista["adu"] = "A-" + fake.numerify("##")
        representante = _parte(fake, chile=True, con_rut=True)
        notify = _parte(fake, chile=True)
        shipper = embarcador
        consignee = consignatario
        forwarding_agent = _parte(fake, chile=True)
    elif template_name == "master_transito.html":
        embarcador = _parte(fake, extranjera=True)
        consignatario = _parte(fake, bolivia=True)
        consignatario["nit"] = fake.numerify("#########")
        almacenista = _parte(fake, chile=True, con_rut=True)
        almacenista["adu"] = "A-" + fake.numerify("##")
        notify = _parte(fake, bolivia=True)
        shipper = embarcador
        consignee = consignatario
        forwarding_agent = _parte(fake, chile=True)
        representante = _parte(fake, chile=True, con_rut=True)
    else:  # exportacion / peligrosa / transbordo / reefer
        shipper = _parte(fake, chile=True, con_rut=True)
        consignee = _parte(fake, extranjera=True)
        notify = _parte(fake, extranjera=True)
        forwarding_agent = _parte(fake, chile=True)
        embarcador = shipper
        consignatario = consignee
        almacenista = _parte(fake, chile=True, con_rut=True)
        almacenista["adu"] = "A-" + fake.numerify("##")
        representante = _parte(fake, chile=True, con_rut=True)

    # --- Metadatos IMO / Reefer ---------------------------------------------------
    numero_certificado = "DGC-" + fake.numerify("####")
    if template_name == "master_peligrosa.html":
        imo_data = {
            "nombre_embarque": c["nombre_embarque"],
            "clase_imo": c["imo"],
            "numero_onu": c["onu"],
            "grupo_embalaje": c["grupo_embalaje"],
            "punto_inflamacion": c["punto_inflamacion"],
            "ems": c["ems"],
            "contaminante_marino": c["contaminante_marino"],
            "contacto_emergencia": "CHEMTREC 24H",
            "telefono_emergencia": "+1-800-424-9300",
            "estiba": random.choice(["AWAY FROM HEAT SOURCES", "ON DECK ONLY",
                                     "SEPARATED FROM FOODSTUFFS"]),
        }
    else:
        imo_data = {}
    if es_reefer or template_name == "master_reefer.html":
        reefer_data = {
            "temperatura": c.get("temperatura", "+1°C"),
            "ventilacion": c.get("ventilacion", "25 CFM"),
            "humedad": c.get("humedad", "85%"),
            "suministro_potencia": "440V / 60Hz / 3PH",
            "pre_trip": "PTI OK - " + fake.date_this_month().strftime("%d/%m"),
            "encargado_reefer": fake.name(),
        }
    else:
        reefer_data = {}

    # --- Datos compartidos ---------------------------------------------------------
    bl_number = f"{fake.bothify('??')}-{fake.year()}-{fake.numerify('#####')}"
    data = {
        "id": bl_id,
        "template": template_name,
        "naviera": random.choice(NAVIERAS),
        "bl_number": bl_number,
        "export_ref": f"PO-{fake.numerify('####')} / INV-{fake.numerify('#####')}",
        "fecha_emision": _fecha(fake, 15),
        "fecha_embarque": _fecha(fake, 10),
        "fecha_generacion": datetime.now().strftime("%d-%m-%Y %H:%M"),
        "lugar_emision": random.choice(["SAN ANTONIO, CHILE", "VALPARAÍSO, CHILE",
                                        "SANTIAGO, CHILE"]),
        # Partes
        "shipper": shipper, "consignee": consignee, "notify": notify,
        "forwarding_agent": forwarding_agent,
        "embarcador": embarcador, "consignatario": consignatario,
        "consignatario_rut": consignatario.get("rut", ""),
        "nit_bolivia": consignatario.get("nit", ""),
        "almacenista": almacenista, "representante": representante,
        # Servicio / condiciones
        "tipo_servicio": tipo_servicio,
        "cond_transporte": cond_transporte,
        "sentido_operacion": sentido,
        "incoterm": random.choice(INCOTERMS),
        "servicio_naviero": "LINER",
        # Ruta
        "pre_carriage": random.choice(PRE_CARRIAGES),
        "vessel": fake.bothify("MV ???-????"),
        "voyage": fake.bothify("####N"),
        "nave": fake.bothify("MV ???-????"),
        "viaje": fake.bothify("####N"),
        "bandera": random.choice(BANDERAS),
        "port_loading": port_loading,
        "port_discharge": port_discharge,
        "puerto_transbordo": puerto_transbordo,
        "final_destination": random.choice(PUERTOS_EXTRANJEROS)["nombre"],
        "destino_final": destino_final,
        "transbordos": transbordos,
        "lugar_recepcion": lugar_recepcion,
        "aduana_destino": "ADUANA " + random.choice(["ARICA", "IQUIQUE", "LA PAZ"]),
        # Contenedor
        "contenedor": contenedor,
        # Carga
        "carga": carga, "bultos_total": bultos_total,
        "peso_total": peso_total, "volumen_total": volumen_total,
        "mercancia": c["nombre"], "es_peligrosa": es_peligrosa, "es_reefer": es_reefer,
        "bultos_detalle": [{
            "marcas": i["marcas"], "cantidad": i["bultos"],
            "descripcion": i["descripcion"], "peso": i["peso"],
            "volumen": i["volumen"], "imo": i["imo"], "onu": i["onu"],
        } for i in carga],
        # Comercial
        "flete_ocean": random.choice(["PREPAID", "COLLECT"]),
        "thc_origen": random.choice(["PREPAID", "COLLECT"]),
        "thc_destino": random.choice(["PREPAID", "COLLECT"]),
        "numero_originales": f"{random.randint(3, 5)} / THREE-{random.choice(['FIVE', 'THREE', 'FOUR'])}",
        "glosa": "TRANSITO A BOLIVIA" if template_name == "master_transito.html" else "",
        "observaciones": _observaciones(),
        "terms": TERMS,
    }

    # --- Datos específicos por plantilla --------------------------------------------
    if template_name == "master_importacion.html":
        data.update({
            "mfto_nro": "MFTO-" + fake.numerify("######"),
            "bl_madre": "SUDU" + fake.bothify("#########"),
            "bl_madre_aceptacion": fake.bothify("?????").upper() + fake.numerify("#######"),
            "folio": bl_number,
            "codigo_verificacion": hashlib.md5(
                f"{bl_number}{random.random()}".encode()).hexdigest()[:32],
        })
    elif template_name == "master_peligrosa.html":
        data.update(imo_data)
        data["numero_certificado"] = numero_certificado
    elif template_name == "master_transbordo.html":
        data["contenedores"] = _contenedores(
            fake, random.randint(2, 4), peso_total, bultos_total,
            volumen_total, status_cont)
        data["bl_madre"] = "SUDU" + fake.bothify("#########")
        if es_reefer:
            data.update(reefer_data)   # contenedores reefer en transbordo
    elif template_name == "master_reefer.html":
        data.update(reefer_data)
    elif es_reefer:  # exportación con contenedor reefer
        data.update(reefer_data)
    else:
        data["contenedores"] = [dict(contenedor, bultos=bultos_total,
                                     volumen=volumen_total)]

    return data


# ------------------------------------------------------------------------------
# 4) GENERADOR PRINCIPAL
# ------------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Generador B/L por casuística")
    parser.add_argument("--count", type=int, default=50,
                        help="Número de documentos (default: 50)")
    parser.add_argument("--seed", type=int, default=None, help="Semilla aleatoria")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)
        Faker.seed(args.seed)

    fake = Faker(["es_CL"])
    fake.add_provider(RUTProvider)
    fake.add_provider(ContainerProvider)

    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
    env.filters["miles"] = lambda n: f"{n:,.2f}"

    # Selección balanceada: cada plantilla aparece al menos `min_por_lote` veces
    # para garantizar mucha variedad en el lote completo.
    seleccion = []
    for tpl, cfg in PLANTILLAS.items():
        seleccion.extend([tpl] * cfg["min_por_lote"])
    extra = args.count - sum(c["min_por_lote"] for c in PLANTILLAS.values())
    if extra > 0:
        seleccion.extend(random.choices(list(PLANTILLAS.keys()), k=extra))
    random.shuffle(seleccion)
    seleccion = seleccion[:args.count]

    OUTPUT_DIR.mkdir(exist_ok=True)
    log.info("Generando %d B/L (6 casuísticas, variedad balanceada)", args.count)

    for i, template_name in enumerate(seleccion, start=1):
        data = build_bl_data(fake, template_name, bl_id=i)
        pdf_path = OUTPUT_DIR / f"bl_document_{i}.pdf"
        json_path = OUTPUT_DIR / f"bl_data_{i}.json"

        html = env.get_template(template_name).render(**data)
        HTML(string=html).write_pdf(str(pdf_path))

        with json_path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)

        tipo = "PELIGROSA" if data["es_peligrosa"] else ("REEFER" if data["es_reefer"] else "ordinaria")
        log.info("  [%3d/%d] %-26s -> %s (%s · %s · %s)",
                 i, args.count, template_name, pdf_path.name,
                 data["bl_number"], data["mercancia"], tipo)

    log.info("Proceso finalizado: %d PDF + %d JSON", args.count, args.count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
