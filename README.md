# 📄 Generador de Bills of Lading (B/L) Sintéticos — Aduana de Chile

Generador de **Bills of Lading hiper-realistas en PDF** para entrenamiento de modelos, basado en las normativas del **Servicio Nacional de Aduanas de Chile** (protocolo XML BL v1.8) y formatos internacionales (ISO 6346, IMO/IMDG, Hague-Visby).

Cada documento se genera con **WeasyPrint** a partir de plantillas **HTML/CSS** (Jinja2) y se acompaña de su **JSON "ground truth"** con los datos exactos inyectados, ideal para arquitecturas de microservicios o datasets de ML/OCR.

---

## ✨ Características

- 🖨️ **6 casuísticas** de B/L en un mismo estilo fotorrealista (cajas negras, CSS Grid, Courier New, títulos diminutos en mayúsculas).
- 🎲 **Variedad garantizada**: en un lote de 50, cada plantilla aparece al menos 8 veces, con mercancías, puertos, navieras, contenedores y RUT distintos.
- 🧮 **RUT chilenos válidos** (`XX.XXX.XXX-K`) con dígito verificador real (módulo 11).
- 🚢 **Contenedores ISO 6346 válidos** (`XXXU#######`) con dígito verificador real.
- 🗺️ **Direcciones coherentes**: la calle la genera Faker pero la Comuna/País sale de pares cerrados. Nunca se mezcla una ciudad chilena con un país extranjero.
- 📦 **Cargas emparejadas**: *Cobre Refinado* → peso alto, sin IMO; *Nitrato de Amonio* → IMO 5.1 / UN1942 obligatorios; cargas refrigeradas con temperatura, etc.
- 📝 **Observaciones reales**: `FREIGHT PREPAID`, `CLEAN ON BOARD`, `14 DAYS FREE TIME DEMURRAGE`, etc. (nunca Lorem Ipsum).
- ♻️ **Reproducible** con `--seed`.

---

## 📁 Estructura del proyecto

```
bil of landing/
├── main.py                    # Generador principal (6 casuísticas, 50 docs por defecto)
├── main_plantillas.py         # Generador anterior (5 plantillas) — preservado
├── requirements.txt           # Dependencias Python
├── README.md
├── templates/                 # Plantillas HTML (Jinja2 + CSS incrustado)
│   ├── master_exportacion.html    # Salida FCL (inglés)
│   ├── master_importacion.html    # Ingreso LCL (español, formato BL 28H/29)
│   ├── master_transito.html       # Tránsito a Bolivia
│   ├── master_peligrosa.html      # Carga peligrosa IMO
│   ├── master_transbordo.html     # Transbordo multimodal
│   ├── master_reefer.html         # Carga refrigerada
│   ├── template_master.html       # Plantilla base hiper-realista
│   ├── ingreso_lcl.html / salida_fcl.html / transito_bolivia.html
│   ├── carga_peligrosa.html / transbordo_multimodal.html   # (formato anterior)
│   └── *.pdf                      # Documentos de referencia (protocolo XML, BL 28H/29)
└── output/                    # Resultados generados
    ├── bl_document_1.pdf ... bl_document_50.pdf   # B/L en PDF (1 página c/u)
    └── bl_data_1.json ... bl_data_50.json         # Ground truth (datos inyectados)
```

---

## 🔧 Instalación

### 1. Python 3.10+

```powershell
python --version   # requiere 3.10 o superior
```

### 2. Entorno virtual y dependencias

```powershell
python -m venv .venv
.\.venv\Scripts\activate          # Windows PowerShell
pip install -r requirements.txt   # faker, jinja2, weasyprint
```

### 3. WeasyPrint en Windows (librerías GTK)

WeasyPrint necesita las librerías **Pango/GTK3**. Instala el **GTK3 Runtime** en:

```
C:\Program Files\GTK3-Runtime Win64\
```

(es la ruta exacta que WeasyPrint busca por defecto). En Linux/macOS las dependencias del sistema se instalan con `apt`/`brew` (ver [documentación de WeasyPrint](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html)).

> Verificación rápida:
> ```powershell
> .\.venv\Scripts\python.exe -c "from weasyprint import HTML; HTML(string='<h1>x</h1>').write_pdf('test.pdf')"
> ```

---

## 🚀 Uso

```powershell
.\.venv\Scripts\python.exe main.py              # genera 50 PDF + 50 JSON en output/
.\.venv\Scripts\python.exe main.py --count 10   # lote más pequeño
.\.venv\Scripts\python.exe main.py --seed 42    # reproducible
```

Argumentos:

| Argumento | Default | Descripción |
|-----------|---------|-------------|
| `--count` | `50`    | Número de documentos a generar |
| `--seed`  | `None`  | Semilla aleatoria (misma semilla → mismos documentos) |

Salida por cada documento `i`:

- `output/bl_document_{i}.pdf` — el B/L renderizado (una sola página A4).
- `output/bl_data_{i}.json` — el ground truth con todos los datos inyectados.

---

## 🗂️ Las 6 casuísticas (plantillas)

| Plantilla | Casuística | Información destacada |
|-----------|-----------|----------------------|
| `master_exportacion.html` | Salida FCL (inglés, internacional) | Shipper/Consignee/Notify/Forwarding, Pre-Carriage, Vessel/Voyage, Port of Loading/Discharge con **UN/LOCODE**, Place of Receipt, **Flete/THC/Incoterm**, N° de originales |
| `master_importacion.html` | Ingreso LCL (español, formato BL 28H/29) | **EMB/CONS/NOTI/ALM/REP** con RUT y **ADU**, Nave/Bandera/Viaje/Servicio, transbordos, **MFTO**, **BL Madre**, **FOLIO** y **Código de Verificación** |
| `master_transito.html` | Tránsito a Bolivia | Glosa obligatoria **"TRANSITO A BOLIVIA"**, **NIT** boliviano, destino final y aduana de tránsito |
| `master_peligrosa.html` | Carga peligrosa IMO | **Proper Shipping Name**, Clase IMO, **UN N°**, Packing Group, **Flash Point**, **EMS**, Marine Pollutant, contacto de emergencia 24h, certificado DG |
| `master_transbordo.html` | Transbordo multimodal | **Pre-Carriage / Ocean Vessel / Puerto de Transbordo**, múltiples contenedores y detalle de bultos con totales |
| `master_reefer.html` | Carga refrigerada | **Set Temperature**, ventilación (CFM), humedad, potencia 440V, pre-trip inspection (PTI) |

---

## 🧪 Reglas de coherencia de datos

Estas reglas evitan los errores típicos de la generación "naive" con Faker:

1. **Direcciones** — la calle la genera Faker, pero la ciudad/país proviene de pares cerrados (`CIUDADES_CHILENAS`, `CIUDADES_EXTRANJERAS`, `CIUDADES_BOLIVIA`). Un consignatario chileno nunca tendrá "Andorra" ni una ciudad extranjera "Chile".
2. **Cargas emparejadas** (`CARGAS`) — cada mercancía define su rango de peso/volumen y si es peligrosa o refrigerada:
   - `Cobre Refinado` → peso alto (15–22 t), **sin código IMO**.
   - `Nitrato de Amonio` → **IMO 5.1 / UN1942** obligatorios.
   - `Gasolina (IBC)` → IMO 3 / UN1203 · `Peróxido de H₂O₂` → IMO 5.1 / UN2014 · `Baterías de Litio` → IMO 9 / UN3480 · `Harina de Pescado` → IMO 9 / UN2216.
   - `Cerezas`, `Salmón`, `Cítricos` → carga refrigerada con temperatura/ventilación.
3. **Observaciones** — frases logísticas reales (`FREIGHT PREPAID`, `CLEAN ON BOARD`, `14 DAYS FREE TIME DEMURRAGE`, `SHIPPER'S LOAD, STOW AND COUNT`…).
4. **Números válidos** — RUT con dígito verificador módulo 11 y contenedores con dígito verificador **ISO 6346**.
5. **Puertos con UN/LOCODE** — p. ej. San Antonio `CLSAI`, Valparaíso `CLVAP`, Long Beach `USLGB`, Manzanillo `PAMIT`.

---

## 🧾 Formato del JSON (ground truth)

Ejemplo resumido de `output/bl_data_1.json`:

```json
{
  "id": 1,
  "template": "master_transito.html",
  "naviera": "PACIFIC STAR LINE",
  "bl_number": "ya-1977-61055",
  "sentido_operacion": "TR",
  "tipo_servicio": "FCL/FCL",
  "cond_transporte": "CY/CY",
  "port_loading": { "nombre": "Shanghai, China", "locode": "CNSHA" },
  "port_discharge": { "nombre": "Arica", "locode": "CLARI" },
  "destino_final": "La Paz",
  "glosa": "TRANSITO A BOLIVIA",
  "contenedor": { "numero": "TCLU1234567", "tipo": "45G0", "sello": "1234567", "status": "FCL/FCL" },
  "carga": [ { "marcas": "...", "bultos": 12, "descripcion": "...", "peso": 4500.0, "volumen": 8.5, "imo": null, "onu": null } ],
  "peso_total": 4500.0,
  "volumen_total": 8.5,
  "observaciones": "FREIGHT PREPAID / CLEAN ON BOARD"
}
```

---

## ✅ Verificación

La salida se valida automáticamente (RUT, ISO 6346, coherencia geográfica, reglas IMO, campos por plantilla, totales). Un lote de 50 con `--seed 2026` produce:

- 50 PDF de **una página** (sin desbordes) + 50 JSON.
- Distribución balanceada: cada una de las 6 plantillas aparece **8–9 veces**.
- 12 mercancías distintas (ordinarias, peligrosas y refrigeradas).

---

## 📌 Notas

- Las plantillas anteriores (`ingreso_lcl`, `salida_fcl`, `transito_bolivia`, `carga_peligrosa`, `transbordo_multimodal`) y el generador `main_plantillas.py` se conservan como referencia del formato previo.
- El proyecto es **solo para simulación/entrenamiento**: los documentos generados no tienen validez legal.
