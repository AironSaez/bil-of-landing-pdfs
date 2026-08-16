# -*- coding: utf-8 -*-
"""
================================================================================
 GENERADOR DE BILLS OF LADING (B/L) SINTÉTICOS — Aduana de Chile
================================================================================

Genera 50 Bills of Lading sintéticos en PDF (via WeasyPrint) usando 5 plantillas
HTML distintas (Jinja2) y un diccionario de "ground truth" en JSON por cada
documento, alineado con el protocolo XML aduanero chileno.

Autor     : Desarrollador Python Senior
Dependencias:
    pip install faker jinja2 weasyprint
    (WeasyPrint requiere el runtime GTK3 en Windows:
     https://doc.courtbouillon.org/weasyprint/stable/first_steps.html)

Uso:
    python main.py                # genera 50 documentos
    python main.py --count 100    # genera 100 documentos
    python main.py --seed 42      # reproduce la misma secuencia aleatoria
================================================================================
"""

from __future__ import annotations

import argparse
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
# Configuración de rutas y logging
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

# WeasyPrint y fontTools loguean a nivel INFO con mucho detalle (subsetting de
# fuentes, layout, etc.); solo mostramos sus advertencias y errores.
logging.getLogger("weasyprint").setLevel(logging.WARNING)
logging.getLogger("weasyprint.progress").setLevel(logging.WARNING)
logging.getLogger("fontTools").setLevel(logging.WARNING)
logging.getLogger("fontTools.subset").setLevel(logging.WARNING)

# ------------------------------------------------------------------------------
# Constantes de dominio (protocolo aduanero chileno + estándares internacionales)
# ------------------------------------------------------------------------------

# Navieras ficticias (simulan diferentes empresas emisoras)
NAVIERAS = [
    "ANDES MAR SHIPPING",
    "PACIFICO SUR LINE",
    "MAGELLAN CARRIER CO.",
    "COSTA NAVIERA S.A.",
    "TRANSOCEAN CHILE",
    "AUKA LINE LTD.",
    "CORDILLERA EXPRESS",
    "GAUCHO FREIGHT LINES",
]

# Códigos de servicio / condiciones / sentido de operación (protocolo XML)
TIPOS_SERVICIO = ["FCL/FCL", "LCL/LCL", "BB"]
COND_TRANSPORTE = ["PP", "DOOR/DOOR"]
SENTIDO_OPERACION = ["I", "S", "TR", "TRB"]  # I=Importación, S=Exportación,
                                             # TR=Tránsito, TRB=Transbordo

# Plantillas disponibles: <archivo> -> (servicios permitidos, sentidos permitidos)
PLANTILLAS = {
    "ingreso_lcl.html":          (["LCL/LCL"], ["I"]),
    "salida_fcl.html":           (["FCL/FCL"], ["S"]),
    "transito_bolivia.html":     (["FCL/FCL", "LCL/LCL"], ["TR"]),
    "carga_peligrosa.html":      (["FCL/FCL", "LCL/LCL"], ["I", "S"]),
    "transbordo_multimodal.html": (["FCL/FCL"], ["TRB"]),
}

# Puertos por rol (nacionales = chilenos, extranjeros = internacionales)
PUERTOS_NACIONALES = [
    "San Antonio", "Valparaíso", "Iquique", "Antofagasta",
    "Arica", "San Vicente", "Coronel", "Puerto Montt",
]
PUERTOS_EXTRANJEROS = [
    "Shanghai", "Busan", "Rotterdam", "Hamburg", "Hong Kong",
    "Long Beach", "Callao", "Guayaquil", "Buenos Aires", "Santos",
    "Valencia", "Algeciras", "Manzanillo (MX)", "Kaohsiung",
]
PUERTOS_TRANSBORDO = [
    "Balboa (PA)", "Cartagena (CO)", "Buenaventura (CO)",
    "Callao (PE)", "Manzanillo (PA)", "Montevideo (UY)",
]
DESTINOS_BOLIVIA = ["La Paz", "Santa Cruz de la Sierra", "Oruro", "Cochabamba"]

# Tipos ISO de contenedor (código de tamaño/tipo, ej. 45G0)
TIPOS_CONTENEDOR = [
    "45G0",  # 40' HC Dry
    "42G1",  # 40' Dry
    "45R1",  # 40' HC Reefer
    "22G1",  # 20' Dry
    "22T1",  # 20' Tank
    "45P1",  # 40' HC Platform
    "22U1",  # 20' Open Top
    "45U1",  # 40' HC Open Top
]
# Status del contenedor: valores del protocolo XML BL de la Aduana de Chile
# (contenedor/status): EMPTY, FCL/FCL, LCL/LCL, BB, FCL/LCL, ... DOOR/DOOR, RoRo
STATUS_CONTENEDOR = ["EMPTY", "FCL/FCL", "LCL/LCL", "BB", "FCL/LCL", "CY/CY", "DOOR/DOOR"]

# Bandera de la nave y tipo de servicio naviero (referencia BL 28H/29)
BANDERAS = ["CL", "LR", "PA", "BS", "HK", "SG", "GR", "PY"]
SERVICIO_NAVIERO = "LINER"

# Clases IMO y números ONU para carga peligrosa
CLASES_IMO = ["1", "2.1", "3", "4.1", "5.1", "6.1", "8", "9"]
NUMEROS_ONU = {
    "1": "UN0333", "2.1": "UN1966", "3": "UN1203", "4.1": "UN3175",
    "5.1": "UN1942", "6.1": "UN1541", "8": "UN2794", "9": "UN3082",
}

# Mercancías y unidades típicas
MERCANCIAS = [
    "Cajas de cartón con vinos envasados",
    "Pallets con productos agrícolas congelados",
    "Bultos con textiles y prendas de vestir",
    "Tambores metálicos con aceites lubricantes",
    "Sacos de polipropileno con harina de pescado",
    "Contenedores refrigerados con fruta fresca",
    "Rollos de papel kraft para embalaje",
    "Bidones con químicos para minería",
    "Cajas con componentes electrónicos",
    "Pallets con bebidas y cervezas artesanales",
]
UNIDADES = ["BULTOS", "CAJAS", "PALLETS", "ROLLOS", "SACOS", "TAMBORES", "BIDONES"]


# ------------------------------------------------------------------------------
# 1) ALGORITMOS DE VALIDACIÓN (dígitos verificadores)
# ------------------------------------------------------------------------------

def rut_digito_verificador(cuerpo: int) -> str:
    """Calcula el dígito verificador de un RUT chileno (módulo 11).

    El algoritmo multiplica cada dígito (de derecha a izquierda) por la serie
    de factores 2,3,4,5,6,7,2,3,... ; suma; calcula el módulo 11 y resta de 11.
    """
    total = 0
    factor = 2
    for ch in reversed(str(cuerpo)):
        total += int(ch) * factor
        factor = 2 if factor == 7 else factor + 1
    resto = total % 11
    dv = 11 - resto
    if dv == 11:
        return "0"
    if dv == 10:
        return "K"
    return str(dv)


def _valor_iso_letra(ch: str) -> int:
    """Mapeo ISO 6346 de letras (A=10 ... Z=38, omitiendo múltiplos de 11)."""
    v = ord(ch) - ord("A") + 10
    if v >= 11:
        v += 1  # salta el 11
    if v >= 22:
        v += 1  # salta el 22
    if v >= 33:
        v += 1  # salta el 33
    return v


def contenedor_digito_verificador(owner_serial: str) -> int:
    """
    Calcula el dígito verificador ISO 6346 de un contenedor.
    `owner_serial` = 4 letras + 6 dígitos (sin el dígito verificador).
    """
    total = 0
    for i, ch in enumerate(owner_serial):
        valor = _valor_iso_letra(ch) if ch.isalpha() else int(ch)
        total += valor * (2 ** i)
    dv = total % 11
    return 0 if dv == 10 else dv


# ------------------------------------------------------------------------------
# 2) PROVEEDORES PERSONALIZADOS DE FAKER
# ------------------------------------------------------------------------------

class RUTProvider(BaseProvider):
    """Genera RUTs chilenos válidos con formato XX.XXX.XXX-K."""

    def rut(self) -> str:
        cuerpo = self.generator.random.randint(1_000_000, 99_999_999)
        dv = rut_digito_verificador(cuerpo)
        cuerpo_formateado = f"{cuerpo:,.0f}".replace(",", ".")
        return f"{cuerpo_formateado}-{dv}"


class ContainerProvider(BaseProvider):
    """Genera números de contenedor marítimos ISO 6346 válidos (TCLU1234567)."""

    # Se excluyen I y O para respetar la recomendación ISO 6346
    LETRAS = "ABCDEFGHJKLMNPQRSTUVWXYZ"

    def container_number(self) -> str:
        letras = "".join(self.generator.random.choices(self.LETRAS, k=3)) + "U"
        serial = f"{self.generator.random.randint(0, 999999):06d}"
        dv = contenedor_digito_verificador(letras + serial)
        return f"{letras}{serial}{dv}"


# ------------------------------------------------------------------------------
# 3) FUNCIONES AUXILIARES DE GENERACIÓN DE DATOS
# ------------------------------------------------------------------------------

def _empresa(fake: Faker, con_rut: bool = False) -> dict:
    """Genera un diccionario de parte (empresa) reutilizable por las plantillas."""
    data = {
        "company": fake.company(),
        "address": fake.street_address(),
        "city": fake.city(),
        "country": fake.country(),
    }
    if con_rut:
        data["rut"] = fake.rut()
    return data


def _generar_detalle_bultos(fake: Faker, cantidad_items: int) -> tuple:
    """
    Genera una lista de bultos con marcas, cantidades, descripción, peso (KGM)
    y volumen (MTQ). Retorna (items, total_bultos, peso_total, volumen_total).
    """
    items = []
    total_bultos = 0
    peso_total = 0.0
    volumen_total = 0.0
    for i in range(cantidad_items):
        cantidad = fake.random_int(min=2, max=120)
        peso = round(fake.random.uniform(500.0, 8_000.0), 2)
        volumen = round(fake.random.uniform(2.0, 25.0), 2)
        items.append({
            "marcas": f"{fake.lexify('????-????')} / {i + 1:02d}",
            "cantidad": cantidad,
            "descripcion": fake.random_element(MERCANCIAS),
            "peso": peso,
            "volumen": volumen,
        })
        total_bultos += cantidad
        peso_total += peso
        volumen_total += volumen
    return items, total_bultos, round(peso_total, 2), round(volumen_total, 2)


def _generar_contenedores(fake: Faker, cantidad: int, peso_total: float,
                          bultos_total: int, volumen_total: float,
                          status: str) -> list:
    """
    Distribuye los totales de la carga en `cantidad` contenedores de forma
    proporcional para que los totales del documento siempre cuadren.
    `status` sigue los valores del protocolo XML (EMPTY, FCL/FCL, LCL/LCL...).
    """
    contenedores = []
    resto_peso, resto_bultos, resto_vol = peso_total, bultos_total, volumen_total
    for i in range(cantidad):
        ultimo = i == cantidad - 1
        share = 1.0 / (cantidad - i) if not ultimo else 1.0
        peso = round(resto_peso * share, 1) if not ultimo else round(resto_peso, 1)
        bultos = int(round(resto_bultos * share)) if not ultimo else resto_bultos
        vol = round(resto_vol * share, 2) if not ultimo else round(resto_vol, 2)
        contenedores.append({
            "numero": fake.container_number(),
            "tipo": fake.random_element(TIPOS_CONTENEDOR),
            "sello": fake.numerify("#######"),
            "status": status,
            "peso": peso,
            "bultos": bultos,
            "volumen": vol,
        })
        if not ultimo:
            resto_peso -= peso
            resto_bultos -= bultos
            resto_vol -= vol
    return contenedores


def _fecha(fake: Faker, dias_atras: int) -> str:
    """Fecha aleatoria dentro de una ventana reciente, formato ISO."""
    d = datetime.now() - timedelta(days=fake.random_int(min=0, max=dias_atras))
    return d.strftime("%Y-%m-%d")


# ------------------------------------------------------------------------------
# 4) CONSTRUCTOR DEL DICCIONARIO DE DATOS (GROUND TRUTH)
# ------------------------------------------------------------------------------

def build_bl_data(fake: Faker, template_name: str, bl_id: int) -> dict:
    """
    Construye el diccionario completo de datos que se inyectará en la plantilla.
    Este mismo diccionario se serializa como JSON (ground truth) para permitir
    la ingesta en arquitecturas de microservicios.
    """
    servicios, sentidos = PLANTILLAS[template_name]

    # --- Partes del documento ------------------------------------------------
    emisor = _empresa(fake)
    embarcador = _empresa(fake)
    consignatario = _empresa(fake, con_rut=True)   # RUT chileno (requisito)
    notify = _empresa(fake)
    almacenista = _empresa(fake, con_rut=True)     # RUT chileno (requisito)
    forwarding_agent = _empresa(fake)

    # --- Parámetros de servicio ----------------------------------------------
    tipo_servicio = fake.random_element(servicios)
    cond_transporte = fake.random_element(COND_TRANSPORTE)
    sentido_operacion = fake.random_element(sentidos)

    # --- Rutas según sentido de operación -------------------------------------
    if sentido_operacion == "S":            # Exportación: carga en puerto nacional
        puerto_embarque = fake.random_element(PUERTOS_NACIONALES)
        puerto_desembarque = fake.random_element(PUERTOS_EXTRANJEROS)
        port_loading = puerto_embarque
        final_destination = puerto_desembarque
        destino_final = final_destination
    else:                                   # Importación / tránsito / transbordo
        puerto_embarque = fake.random_element(PUERTOS_EXTRANJEROS)
        puerto_desembarque = fake.random_element(PUERTOS_NACIONALES)
        port_loading = puerto_embarque
        final_destination = puerto_desembarque
        destino_final = puerto_desembarque

    if template_name == "transito_bolivia.html":
        destino_final = fake.random_element(DESTINOS_BOLIVIA)

    # --- Carga: bultos, peso y volumen ----------------------------------------
    items, bultos_total, peso_bruto, volumen_total = _generar_detalle_bultos(
        fake, fake.random_int(min=3, max=6)
    )
    bultos = bultos_total
    volumen = volumen_total
    # Status del contenedor: igual al tipo de servicio (fiel al BL 28H/29,
    # que muestra p.ej. "Status: LCL/LCL"); a veces EMPTY (contenedor vacío).
    status_contenedor = (
        "EMPTY" if fake.random_int(1, 10) == 10 else tipo_servicio
    )
    contenedor_unico = {
        "numero": fake.container_number(),
        "tipo": fake.random_element(TIPOS_CONTENEDOR),
        "sello": fake.numerify("#######"),
        "status": status_contenedor,
        "peso": round(peso_bruto, 1),
    }

    # --- Datos específicos por plantilla ---------------------------------------
    if template_name == "transbordo_multimodal.html":
        contenedores = _generar_contenedores(
            fake, fake.random_int(min=2, max=4), peso_bruto,
            bultos_total, volumen_total, status_contenedor,
        )
    else:
        contenedores = [dict(contenedor_unico, bultos=bultos_total, volumen=volumen_total)]

    clase_imo = None
    numero_onu = None
    if template_name == "carga_peligrosa.html":
        clase_imo = fake.random_element(CLASES_IMO)
        numero_onu = NUMEROS_ONU[clase_imo]

    glosa = "TRANSITO A BOLIVIA" if template_name == "transito_bolivia.html" else ""

    # --- Diccionario completo (ground truth) ----------------------------------
    return {
        # Identificación
        "id": bl_id,
        "template": template_name,
        "naviera": fake.random_element(NAVIERAS),
        "bl_number": fake.bothify("BL-########"),
        "fecha_emision": _fecha(fake, 30),
        "fecha_embarque": _fecha(fake, 15),

        # Partes (claves bilingües para ambas plantillas es/es-en)
        "emisor": emisor,
        "embarcador": embarcador,
        "consignatario": consignatario,
        "notify": notify,
        "almacenista": almacenista,
        "shipper": embarcador,
        "consignee": consignatario,
        "forwarding_agent": forwarding_agent,
        "consignatario_rut": consignatario["rut"],

        # Servicio / condiciones (protocolo aduanero chileno)
        "tipo_servicio": tipo_servicio,
        "cond_transporte": cond_transporte,
        "sentido_operacion": sentido_operacion,

        # Ruta
        "puerto_embarque": puerto_embarque,
        "puerto_desembarque": puerto_desembarque,
        "port_loading": port_loading,
        "final_destination": final_destination,
        "destino_final": destino_final,
        "puerto_transbordo": fake.random_element(PUERTOS_TRANSBORDO),
        "pre_carriage": f"Tren {fake.bothify('##-####')} · Truck {fake.bothify('??-###')}",
        "ocean_vessel": fake.bothify("MV ???-????"),

        # Nave / viaje
        "nave": fake.bothify("MV ???-????"),
        "viaje": fake.bothify("V####"),
        "vessel": fake.bothify("MV ???-????"),
        "voyage": fake.bothify("V####"),
        "bandera": fake.random_element(BANDERAS),
        "servicio_naviero": SERVICIO_NAVIERO,

        # Contenedor
        "contenedor": contenedor_unico,
        "contenedores": contenedores,

        # Carga
        "bultos": bultos,
        "bultos_total": bultos_total,
        "unidades": fake.random_element(UNIDADES),
        "peso_bruto": peso_bruto,
        "volumen": volumen,
        "volumen_total": volumen_total,
        "marcas": fake.lexify("????-????"),
        "mercancia": fake.random_element(MERCANCIAS),
        "bultos_detalle": items,

        # Carga peligrosa (IMO)
        "clase_imo": clase_imo,
        "numero_onu": numero_onu,

        # Comercial / pie
        "flete_pagadero_en": "PREPAID" if cond_transporte == "PP" else "DESTINO",
        "lugar_emision": fake.random_element(["Santiago de Chile", "Valparaíso",
                                             "Buenos Aires", "Shanghai"]),
        "observaciones": fake.sentence(nb_words=12),
        "glosa": glosa,
    }


# ------------------------------------------------------------------------------
# 5) GENERADOR PRINCIPAL
# ------------------------------------------------------------------------------

def render_bl(env: Environment, template_name: str, data: dict, pdf_path: Path) -> None:
    """Renderiza una plantilla Jinja2 con los datos y escribe el PDF."""
    html = env.get_template(template_name).render(**data)
    HTML(string=html).write_pdf(str(pdf_path))


def guardar_json(data: dict, json_path: Path) -> None:
    """Serializa el ground truth a JSON (ordenado y con indentación)."""
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generador de B/L sintéticos")
    parser.add_argument("--count", type=int, default=50,
                        help="Número de documentos a generar (default: 50)")
    parser.add_argument("--seed", type=int, default=None,
                        help="Semilla para reproducibilidad de la generación")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)
        Faker.seed(args.seed)

    fake = Faker(["es_CL"])
    fake.add_provider(RUTProvider)
    fake.add_provider(ContainerProvider)

    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
    template_names = sorted(PLANTILLAS.keys())

    OUTPUT_DIR.mkdir(exist_ok=True)
    log.info("Generando %d Bills of Lading en: %s", args.count, OUTPUT_DIR)

    for i in range(1, args.count + 1):
        template_name = random.choice(template_names)
        data = build_bl_data(fake, template_name, bl_id=i)

        pdf_path = OUTPUT_DIR / f"bl_document_{i}.pdf"
        json_path = OUTPUT_DIR / f"bl_data_{i}.json"

        render_bl(env, template_name, data, pdf_path)
        guardar_json(data, json_path)

        log.info("  [%3d/%d] %-26s -> %s (B/L %s, %s)",
                 i, args.count, template_name,
                 pdf_path.name, data["bl_number"], data["tipo_servicio"])

    log.info("Proceso finalizado: %d PDF + %d JSON", args.count, args.count)


if __name__ == "__main__":
    sys.exit(main())
