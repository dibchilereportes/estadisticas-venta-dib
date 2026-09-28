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
    'ECCOMERCE MARCA PROPIA':     ('B2C', 'Web', 'Web DIB', True),
    'WEB BAZHARS':                ('B2C', 'Web', 'Web Bazhars', True),
    'MARKETPLACE':                ('B2C', 'Marketplace', 'Marketplace', True),
    'ECCOMERCE VENTA VERDE':      ('B2C', 'Web', 'Venta Verde', True),
    'MARKETPLACE FALABELLA':      ('B2C', 'Marketplace', 'Falabella', True),
    'RETAIL CENTRALIZADA':        ('B2B', 'Venta x Mayor', 'Retail', True),
    'WEB DECOEXPRESS':            ('B2C', 'Web', 'Web Decoexpress', True),
    'MARKETPLACE KITCHENCENTER':  ('B2C', 'Marketplace', 'Kitchencenter', True),
    'MARKETPLACE WALLMART':       ('B2C', 'Marketplace', 'Walmart', True),
    'MARKETPLACE RIPLEY':         ('B2C', 'Marketplace', 'Ripley', True),
    'MARKETPLACE WALMART':        ('B2C', 'Marketplace', 'Walmart', True),
    'HORECA':                     ('B2B', 'Venta x Mayor', 'Mayorista', True),
    'MARKETPLACE PARIS':          ('B2C', 'Marketplace', 'Paris', True),
    'EMPLEADOS':                  ('B2C', 'Empleados', '', True),
    'EMPELADOS':                  ('B2C', 'Empleados', '', True),
    'VEV SODIMAC':                ('B2B', 'Venta x Mayor', 'Retail', True),
    'OFICINA':                    ('EXCLUIR', '', '', False),
    'MERCADO LIBRE':              ('B2C', 'Marketplace', 'Mercado Libre', True),
    'MARKETPLACE HITES':          ('B2C', 'Marketplace', 'Hites', True),
    # 'PUNTO DE VENTA' se resuelve aparte, cruzando con x_branch (DIB vs Bazhars)
    # NOTA (28-09-2026): Canal_N3 ahora lleva la plataforma (Falabella/Ripley/Walmart/...)
    # tomada directo de x_canal. Antes esta identificacion dependia de que RazonSocial
    # (x_customer) trajera el nombre de la plataforma como cliente -- eso dejo de pasar
    # en la API: desde agosto 2026 x_customer trae el consumidor final real (a menudo
    # CLIENTE BOLETA), no la plataforma. x_canal es la unica fuente confiable de eso.
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
    # x_branch trae el nombre corto de la sucursal; el historico usa el nombre largo con
    # prefijo DIB/BAZHARS (ej. 'Outlet El Salto' vs 'DIB OUTLET EL SALTO'). Se remapea al
    # nombre historico para que el mismo local fisico no aparezca duplicado en el filtro.
    # Confirmado por el usuario (25-09-2026, caso Outlet El Salto) que aplica a todos los
    # locales DIB. Si aparece un local nuevo de verdad (no un rename), agregarlo aca solo
    # si corresponde -- no forzar un match dudoso.
    # Confirmado por el usuario (27-09-2026): Parque Arauco/El Trebol/La Dehesa/
    # La Serena/Temuco son locales Bazhars de Decostore (mismo caso de rename);
    # Local 207/315 son los locales de telas/alfombras de Viña del Mar.
    LOCAL_MAP = {
        'Outlet El Salto':        'DIB OUTLET EL SALTO',
        'Outlet Park':            'DIB VIÑA OUTLET PARK',
        'Outlet Alerce':          'DIB PUERTO MONTT ALERCE',
        'Easton Center':          'DIB QUILICURA EASTON CENTER',
        'Vivo La Florida':        'DIB LA FLORIDA',
        'La Fabrica':             'DIB SAN JOAQUIN LA FABRICA',
        'Vivo Temuco':            'DIB TEMUCO VIVO',
        'Vivo Outlet Maipu':      'DIB MAIPU VIVO',
        'Puerto Montt Costanera': 'DIB PUERTO MONTT COSTANERA',
        'Easton Temuco':          'DIB TEMUCO EASTON',
        'Dib Rancagua':           'DIB RANCAGUA',
        'Bazhars Vitacura':       'BAZHARS VITACURA',
        'B2C M PLACES':           'B2C M PLACE',
        'La Dehesa':              'BAZHARS LA DEHESA',
        'La Serena':              'BAZHARS LA SERENA',
        'Temuco':                 'BAZHARS TEMUCO',
        'El Trebol':              'BAZHARS TREBOL',
        'Parque Arauco':          'BAZHARS PARQUE ARAUCO',
        'Montemar':               'BAZHARS MONTEMAR',
        'Local 207':              'DIB VIÑA LOCAL TELAS',
        'Local 315':              'DIB VIÑA LOCAL ALFOMBRAS',
    }
    out['local'] = out['local'].replace(LOCAL_MAP)
    # es_bazhars se calcula sobre el local YA remapeado (out['local']), no sobre
    # x_branch crudo: x_branch de las sucursales Bazhars ya no trae el prefijo
    # 'BAZHARS' en la API (viene como 'Parque Arauco', 'Temuco', etc.), asi que
    # el startswith('BAZHARS') sobre x_branch fallaba para esos locales -- se
    # detecta despues del remapeo, cuando ya tienen el nombre historico completo.
    es_bazhars = out['local'].astype(str).str.upper().str.startswith('BAZHARS')

    # Canal: Punto de Venta se resuelve por marca de la sucursal (Bazhars vs DIB); el resto
    # sale del mapeo confirmado en PASO3_mapeo_canal_api.xlsx
    canal_up = df['x_canal'].astype(str).str.upper().str.strip().replace('NAN', np.nan)

    n1 = pd.Series(np.nan, index=df.index, dtype=object)
    n2 = pd.Series(np.nan, index=df.index, dtype=object)
    n3 = pd.Series(np.nan, index=df.index, dtype=object)

    n1 = np.where(es_pdv, 'B2C', n1)
    n2 = np.where(es_pdv & es_bazhars, 'Locales Bazhars', np.where(es_pdv, 'Locales DIB', n2))
    # Canal_N3 para Punto de Venta nunca se llenaba (quedaba en blanco / 'sin dato')
    # -- en el historico, Canal_N3 de un local fisico es el nombre del local mismo.
    # Confirmado por el usuario (28-09-2026), caso Decostore/Bazhars sin Detalle canal.
    n3 = np.where(es_pdv, out['local'], n3)

    sin_mapa = set()
    for canal, (c1, c2, c3, incluir) in CANAL_MAP.items():
        m = canal_up.eq(canal)
        n1 = np.where(m, c1, n1)
        n2 = np.where(m, c2, n2)
        n3 = np.where(m, c3, n3)

    resueltos = set(CANAL_MAP) | {'PUNTO DE VENTA'}
    n_sin_canal_antes = int(pd.isna(n1).sum())

    # Respaldo (28-09-2026): si x_canal vino vacio en Odoo y por eso Canal_N1/N2/N3
    # quedaron en blanco, pero el propio 'local' ya deja clara la categoria (ej.
    # 'M PLACE DEXP' -- marketplace de Decoexpress, inequivocamente B2C), no hace
    # falta dejarlo sin clasificar. Caso confirmado por el usuario: DECOEXPRESS con
    # local='M PLACE DEXP'.
    sin_canal = pd.isna(n1)
    es_mkp_dexp = sin_canal & out['local'].astype(str).str.upper().str.contains('M PLACE')
    n1 = np.where(es_mkp_dexp, 'B2C', n1)
    n2 = np.where(es_mkp_dexp, 'Marketplace', n2)
    n3 = np.where(es_mkp_dexp, 'Marketplace', n3)

    n_sin_canal = int(pd.isna(n1).sum())
    if n_sin_canal:
        print(f'AVISO: {n_sin_canal} filas sin x_canal (vacio en Odoo) y sin local reconocible '
              f'-> Canal_N1/N2/N3 quedan en blanco, revisar a mano')
    for c in sorted(set(canal_up.dropna().unique()) - resueltos):
        sin_mapa.add(c)
    if sin_mapa:
        print(f'AVISO: valores de x_canal sin mapeo (revisar CANAL_MAP): {sin_mapa}')

    out['Canal_N1'] = n1
    out['Canal_N2'] = n2
    out['Canal_N3'] = n3
    out['DesgloseEntrega'] = 'No aplica (API)'
    es_decoexpress = (
        df['x_cuenta_analytica'].astype(str).str.contains('DEXP', na=False) |
        df['x_branch'].astype(str).str.contains('DECOEXPRESS', case=False, na=False) |
        canal_up.str.contains('DECOEXPRESS', na=False))
    # Bazhars es la marca retail de Decostore -- antes de esto, ninguna fila de la API
    # quedaba clasificada como DECOSTORE (bug encontrado 27-09-2026: es_bazhars solo
    # miraba x_branch crudo, que ya no trae el prefijo 'BAZHARS').
    # Excepcion confirmada por el usuario (28-09-2026): BAZHARS VITACURA es, a pesar
    # del nombre/marca Bazhars, una tienda de la empresa EDUARDO DIB (no Decostore).
    # Sigue clasificada como canal 'Locales Bazhars' (es_bazhars sin cambios arriba),
    # solo se excluye de la asignacion de Empresa=DECOSTORE.
    es_decostore = es_bazhars & (out['local'] != 'BAZHARS VITACURA')
    out['Empresa'] = np.select([es_decostore, es_decoexpress], ['DECOSTORE', 'DECOEXPRESS'],
                               default='EDUARDO DIB')

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
