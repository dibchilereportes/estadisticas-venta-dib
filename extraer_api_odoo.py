# -*- coding: utf-8 -*-
"""
Extrae ventas desde la vista Odoo x_bi_sql_view.informe_ventas_cuadratura_v7_15
(agosto 2026 en adelante), las estandariza al mismo esquema de
ventas_bdd.parquet (historico 2023-jul.2026) y arma el archivo completo
2023-hoy + el cubo mensual para el dashboard.

Uso:
    python extraer_api_odoo.py
Requiere en la misma carpeta: ventas_bdd.parquet (historico hasta julio 2026,
generado por etl_ventas.py) y build_dash.py (para regenerar el dashboard
despues, por separado).
"""
import re
import unicodedata
import numpy as np
import pandas as pd
import xmlrpc.client

# ------------------------------------------------------------------
# Credenciales API de Odoo
# ------------------------------------------------------------------
import os
ODOO = (
    os.environ['ODOO_URL'],
    os.environ['ODOO_DB'],
    os.environ['ODOO_USER'],
    os.environ['ODOO_KEY'],
)

MODELO = 'x_bi_sql_view.informe_ventas_cuadratura_v7_15'
DESDE = '2026-08-01'          # a partir de aca reemplaza el historico por datos de la API
UNIDAD_FACTOR = 1000          # el historico esta en miles de pesos

HIST_PARQUET = 'datos/ventas_bdd.parquet'          # historico 2023-jul.2026 (etl_ventas.py)
SALIDA_COMPLETO = 'datos/ventas_bdd.parquet'       # se sobreescribe con el set completo 2023-hoy
SALIDA_CUBO = 'datos/cubo_mes.parquet'

# ---------------------------------------------------------------- utilidades
def upper_key(s: pd.Series) -> pd.Series:
    x = s.fillna("").astype(str).str.upper()
    x = x.map(lambda v: unicodedata.normalize("NFKD", v).encode("ascii", "ignore").decode())
    x = x.str.replace(r"[.,;]", " ", regex=True).str.replace(r"\s+", " ", regex=True).str.strip()
    x = x.str.replace(r"\b(S\s?A|SPA|LTDA|LIMITADA|EIRL|E I R L|CIA|Y CIA)\b", "", regex=True)
    return x.str.replace(r"\s+", " ", regex=True).str.strip()

TIPO_DOC = {
    "FAC": "FACTURA", "FACTURA": "FACTURA", "FACTURA ELECTRONICA": "FACTURA",
    "BOLETA": "BOLETA", "BOLETA ELECTRONICA": "BOLETA",
    "NOT": "NOTA_CREDITO", "NC": "NOTA_CREDITO", "NOTA DE CREDITO ELECTRONICA": "NOTA_CREDITO",
    "NOTA DE DEBITO ELECTRONICA": "NOTA_DEBITO",
    "LIQUIDACION FACTURA ELECTRONICA": "LIQUIDACION",
    "OPERACIONES VISUAL": "AJUSTE", "PARIS MARKETPLACE DIB": "BOLETA",
}

NO_UNITARIAS = {"DESCUENTOS", "BONIFICACION", "COMISION/CONSIGNACION", "FLETE LOCAL",
                "CAMBIO", "REFACTURACION", "PUB. CLIENTES", "BACK OFFICE",
                "FACTURACION MASIVA", "AJUSTE WEB DIB", "TOMA DE MEDIDAS",
                "SIN INVENTARIO", "VENTAS LIQUIDACION FACTURA", "DEVOLUCION MERCADERIA"}

# Canal_N1, Canal_N2, Canal_N3, Incluir  -- confirmado en PASO3_mapeo_canal_api.xlsx
CANAL_MAP = {
    'TRADICIONAL':                ('B2B', 'Venta x Mayor', 'Mayorista', True),
    'MODERNO':                    ('B2B', 'Venta x Mayor', 'Retail', True),
    'INTEREMPRESA':               ('INTEREMPRESAS', '', '', False),
    'ECCOMERCE MARCA PROPIA':     ('B2C', 'Web', '', True),
    'WEB BAZHARS':                ('B2C', 'Web', '', True),
    'MARKETPLACE':                ('B2C', 'Marketplace', '', True),
    'ECCOMERCE VENTA VERDE':      ('B2C', 'Web', '', True),
    'MARKETPLACE FALABELLA':      ('B2C', 'Marketplace', '', True),
    'RETAIL CENTRALIZADA':        ('B2B', 'Venta x Mayor', 'Retail', True),
    'WEB DECOEXPRESS':            ('B2C', 'Web', '', True),
    'MARKETPLACE KITCHENCENTER':  ('B2C', 'Marketplace', '', True),
    'MARKETPLACE WALLMART':       ('B2C', 'Marketplace', '', True),
    'MARKETPLACE RIPLEY':         ('B2C', 'Marketplace', '', True),
    'MARKETPLACE WALMART':        ('B2C', 'Marketplace', '', True),
    'HORECA':                     ('B2B', 'Venta x Mayor', 'Mayorista', True),
    'MARKETPLACE PARIS':          ('B2C', 'Marketplace', '', True),
    'EMPLEADOS':                  ('B2C', 'Empleados', '', True),
    'EMPELADOS':                  ('B2C', 'Empleados', '', True),
    'VEV SODIMAC':                ('B2B', 'Venta x Mayor', 'Retail', True),
    'OFICINA':                    ('EXCLUIR', '', '', False),
    'MERCADO LIBRE':              ('B2C', 'Marketplace', '', True),
    'MARKETPLACE HITES':          ('B2C', 'Marketplace', '', True),
    # 'PUNTO DE VENTA' se resuelve aparte, cruzando con x_branch (DIB vs Bazhars)
}


def conectar():
    url, db, user, key = ODOO
    common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
    uid = common.authenticate(db, user, key, {})
    if not uid:
        raise SystemExit('No se pudo autenticar en Odoo. Revisa usuario/API key/DB.')
    models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')
    return db, uid, key, models


def extraer():
    db, uid, key, models = conectar()

    def call(metodo, *args, **kwargs):
        return models.execute_kw(db, uid, key, MODELO, metodo, list(args), kwargs)

    campos = ['x_date', 'x_periodo_mes', 'x_branch', 'x_canal', 'x_cuenta_analytica',
              'x_analytic_code', 'x_codigo', 'x_producto', 'x_categoria', 'x_linea',
              'x_familia', 'x_subfamilia', 'x_medida_estandar', 'x_tipo_producto_reporte',
              'x_tipo_dte', 'x_numero_documento', 'x_folio', 'x_customer', 'x_rut',
              'x_vendedor', 'x_cantidad', 'x_precio', 'x_total_venta', 'x_costo',
              'x_margen', 'x_margen_contribucion', 'x_estado_documento']

    dom = [('x_date', '>=', DESDE)]   # validado sin filtro de estado (calza con el total oficial)
    n = call('search_count', dom)
    print(f'Registros a extraer desde {DESDE}: {n}')

    filas = []
    LOTE = 5000
    for offset in range(0, n, LOTE):
        filas.extend(call('search_read', dom, fields=campos, offset=offset, limit=LOTE))
        print(f'  ...{min(offset + LOTE, n)}/{n}')

    df = pd.DataFrame(filas)

    # Odoo devuelve False (booleano) en los campos de texto vacios en vez de None/NaN.
    # Si no se limpia, ensucia canal/categoria/etc. con el string "False" y rompe la
    # escritura a parquet (mezcla de tipos bool/str en la misma columna).
    TEXT_COLS = ['x_branch', 'x_canal', 'x_cuenta_analytica', 'x_analytic_code', 'x_codigo',
                 'x_producto', 'x_categoria', 'x_linea', 'x_familia', 'x_subfamilia',
                 'x_medida_estandar', 'x_tipo_producto_reporte', 'x_tipo_dte',
                 'x_numero_documento', 'x_customer', 'x_rut', 'x_vendedor', 'x_estado_documento']
    for c in TEXT_COLS:
        if c in df.columns:
            df[c] = df[c].map(lambda v: np.nan if v is False else v)

    print(f'Extraidas {len(df)} filas, {df["x_total_venta"].sum() / UNIDAD_FACTOR:,.0f} miles de venta bruta')
    return df


def estandarizar(df):
    out = pd.DataFrame(index=df.index)

    out['Fecha'] = pd.to_datetime(df['x_date'])
    out['Año'] = out['Fecha'].dt.year.astype('int16')
    out['Mes'] = out['Fecha'].dt.month.astype('int8')
    out['Periodo'] = out['Año'].astype(str) + '-' + out['Mes'].astype(str).str.zfill(2)

    out['Codigo'] = df['x_codigo'].where(df['x_codigo'].astype(bool), np.nan)
    out['Descripcion'] = df['x_producto']
    out['RazonSocial'] = df['x_customer']
    out['SucursalCli'] = df['x_customer']
    out['Vendedor'] = df['x_vendedor'].where(df['x_vendedor'].astype(bool), np.nan)

    k = upper_key(df['x_tipo_dte'])
    out['TipoDoc'] = k.map(TIPO_DOC).fillna('OTRO')
    out['EsNotaCredito'] = out['TipoDoc'].eq('NOTA_CREDITO')
    out['Tipo'] = df['x_tipo_dte']

    out['Factura'] = pd.to_numeric(df['x_folio'], errors='coerce')

    out['Cantidad'] = df['x_cantidad'].astype('float32')
    out['Precio'] = (df['x_precio'] / UNIDAD_FACTOR).astype('float32')
    out['Venta'] = (df['x_total_venta'] / UNIDAD_FACTOR).astype('float32')
    out['Costo'] = (df['x_costo'] / UNIDAD_FACTOR).astype('float32')
    out['Contribucion'] = (df['x_margen_contribucion'] / UNIDAD_FACTOR).astype('float32')
    out['Margen'] = pd.to_numeric(df['x_margen'], errors='coerce').astype('float32')

    out['LINEA_STD'] = df['x_linea'].where(df['x_linea'].astype(bool), 'SIN LINEA')
    out['FAMILIA_STD'] = df['x_familia']
    out['SUBFAMILIA_STD'] = df['x_subfamilia']
    cat = df['x_categoria'].astype(str).str.upper().str.strip()
    out['CATEGORIA_STD'] = cat.replace('NAN', np.nan)
    out['Descontinuado'] = cat.str.contains('DESCONTIN', na=False)
    out['Medida'] = df['x_medida_estandar']
    out['Marca'] = np.nan
    out['PrecioLista'] = np.nan
    out['CostoStd'] = np.nan
    out['StockActual'] = np.nan

    out['UnidadValida'] = ~(out['LINEA_STD'].astype(str).eq('SERVICIOS')
                             | (df['x_tipo_producto_reporte'].astype(str).str.upper() == 'SERVICIO')
                             | out['CATEGORIA_STD'].astype(str).str.upper().isin(NO_UNITARIAS))

    out['OrigenClasif'] = 'API_ODOO'
    out['ClienteKey'] = upper_key(df['x_customer'])
    out['ClienteNombre'] = df['x_customer']

    # local: para Punto de Venta usa la sucursal fisica; para el resto, la cuenta analitica
    es_pdv = df['x_canal'].astype(str).str.upper().str.strip().eq('PUNTO DE VENTA')
    out['local'] = np.where(es_pdv & df['x_branch'].astype(bool), df['x_branch'],
                    np.where(df['x_cuenta_analytica'].astype(bool), df['x_cuenta_analytica'],
                             df['x_canal']))

    # Canal: Punto de Venta se resuelve por marca de la sucursal (Bazhars vs DIB); el resto
    # sale del mapeo confirmado en PASO3_mapeo_canal_api.xlsx
    canal_up = df['x_canal'].astype(str).str.upper().str.strip().replace('NAN', np.nan)
    es_bazhars = df['x_branch'].astype(str).str.upper().str.startswith('BAZHARS', na=False)

    n1 = pd.Series(np.nan, index=df.index, dtype=object)
    n2 = pd.Series(np.nan, index=df.index, dtype=object)
    n3 = pd.Series(np.nan, index=df.index, dtype=object)

    n1 = np.where(es_pdv, 'B2C', n1)
    n2 = np.where(es_pdv & es_bazhars, 'Locales Bazhars', np.where(es_pdv, 'Locales DIB', n2))

    sin_mapa = set()
    for canal, (c1, c2, c3, incluir) in CANAL_MAP.items():
        m = canal_up.eq(canal)
        n1 = np.where(m, c1, n1)
        n2 = np.where(m, c2, n2)
        n3 = np.where(m, c3, n3)

    resueltos = set(CANAL_MAP) | {'PUNTO DE VENTA'}
    n_sin_canal = int(canal_up.isna().sum())
    if n_sin_canal:
        print(f'AVISO: {n_sin_canal} filas sin x_canal (vacio en Odoo) -> Canal_N1/N2/N3 quedan en blanco, revisar a mano')
    for c in sorted(set(canal_up.dropna().unique()) - resueltos):
        sin_mapa.add(c)
    if sin_mapa:
        print(f'AVISO: valores de x_canal sin mapeo (revisar CANAL_MAP): {sin_mapa}')

    out['Canal_N1'] = n1
    out['Canal_N2'] = n2
    out['Canal_N3'] = n3
    out['DesgloseEntrega'] = 'No aplica (API)'
    out['Empresa'] = np.where(
        df['x_cuenta_analytica'].astype(str).str.contains('DEXP', na=False) |
        df['x_branch'].astype(str).str.contains('DECOEXPRESS', case=False, na=False) |
        canal_up.str.contains('DECOEXPRESS', na=False),
        'DECOEXPRESS', 'EDUARDO DIB')

    # columnas legado que ya no se pueblan (se mantienen para compatibilidad de esquema)
    for c in ['CodFami', 'CodCate', 'CodSubFami', 'Sucursal',
              'CodFami_std', 'CodFami_imputado', 'CodCate_std', 'Cat_std', 'CodSubFami_std']:
        out[c] = np.nan

    return out


def main():
    df_api = extraer()
    if df_api.empty:
        print('No hay filas nuevas, no se genera nada.')
        return
    nuevo = estandarizar(df_api)

    hist = pd.read_parquet(HIST_PARQUET)
    hist = hist[hist['Fecha'] < pd.Timestamp(DESDE)]

    columnas = [c for c in hist.columns if c in nuevo.columns] + \
               [c for c in nuevo.columns if c not in hist.columns]
    for c in columnas:
        if c not in hist.columns:
            hist[c] = np.nan
        if c not in nuevo.columns:
            nuevo[c] = np.nan

    completo = pd.concat([hist[columnas], nuevo[columnas]], ignore_index=True)
    completo.to_parquet(SALIDA_COMPLETO, index=False)
    print(f'\n{SALIDA_COMPLETO}: {len(completo)} filas '
          f'({len(hist)} historico + {len(nuevo)} API), '
          f'venta total {completo["Venta"].sum():,.0f} miles')

    # cubo mensual (mismo criterio de build_dash.py, para verificacion rapida)
    cubo = (completo.groupby(['Año', 'Mes', 'Canal_N1', 'Canal_N2'], observed=True, dropna=False)
                     ['Venta'].sum().reset_index())
    cubo.to_parquet(SALIDA_CUBO, index=False)
    print(f'{SALIDA_CUBO}: {len(cubo)} filas')


if __name__ == '__main__':
    main()
