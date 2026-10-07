# -*- coding: utf-8 -*-
"""
SOLO LECTURA sobre Odoo. Trae 2025-01-01 hasta antes de DESDE (historico del dashboard), clasifica cada
linea (nivel gerencial, linea comercial, bloque, entra al informe CD, venta empresa) y guarda
datos/clasif_filas_hist.parquet con la llave (Fecha, Factura, Codigo, Tipo) para cruzarla con las filas
del historico en extraer_api_odoo.py. Imprime la cobertura del cruce contra datos/ventas_bdd.parquet.
"""
import os
import xmlrpc.client
import numpy as np
import pandas as pd
import informe_cd

URL, DB, USER, KEY = (os.environ[k] for k in ('ODOO_URL', 'ODOO_DB', 'ODOO_USER', 'ODOO_KEY'))
MODELO = 'x_bi_sql_view.informe_ventas_cuadratura_v7_15'
CAMPOS = ['x_date', 'x_folio', 'x_codigo', 'x_customer', 'x_branch', 'x_canal', 'x_cuenta_analytica',
          'x_linea', 'x_tipo_dte', 'x_total_venta', 'x_margen_contribucion']
HASTA = '2026-07-31'
DOM = [('x_date', '>=', '2025-01-01'), ('x_date', '<=', HASTA)]
SALIDA = 'datos/clasif_filas_hist.parquet'

common = xmlrpc.client.ServerProxy(f'{URL}/xmlrpc/2/common')
uid = common.authenticate(DB, USER, KEY, {})
if not uid:
    raise SystemExit('No se pudo autenticar en Odoo')
m = xmlrpc.client.ServerProxy(f'{URL}/xmlrpc/2/object')
call = lambda metodo, *a, **k: m.execute_kw(DB, uid, KEY, MODELO, metodo, list(a), k)

n = call('search_count', DOM)
print('Registros:', n)
filas = []
for off in range(0, n, 5000):
    filas.extend(call('search_read', DOM, fields=CAMPOS, offset=off, limit=5000))
    if (off // 5000) % 10 == 0:
        print(f'  {min(off + 5000, n)}/{n}')

df = pd.DataFrame(filas).drop(columns=['id'], errors='ignore')
for c in ['x_folio', 'x_codigo', 'x_customer', 'x_branch', 'x_canal', 'x_cuenta_analytica', 'x_linea', 'x_tipo_dte']:
    df[c] = df[c].map(lambda v: np.nan if v is False else v)
df['venta'] = df['x_total_venta']
df['x_date'] = pd.to_datetime(df['x_date'])

partes = []
for anio, g in df.groupby(df['x_date'].dt.year):
    partes.append(informe_cd.clasificar_filas(g.copy(), anio_anterior=(anio == 2025)))
cl = pd.concat(partes).reindex(df.index)

out = pd.DataFrame({
    'Fecha': df['x_date'],
    'Factura': pd.to_numeric(df['x_folio'], errors='coerce'),
    'Codigo': df['x_codigo'].where(df['x_codigo'].astype(bool), np.nan),
    'Tipo': df['x_tipo_dte'],
}).join(cl)
claves = ['Fecha', 'Factura', 'Codigo', 'Tipo']
dup = out.duplicated(claves, keep=False)
amb = out[dup].groupby(claves, dropna=False)[['CliGer', 'LineaCom', 'EntraCD']].nunique(dropna=False).gt(1).any(axis=1).sum()
print(f'Lineas: {len(out)} | llaves repetidas: {dup.sum()} | llaves con clasificacion ambigua: {amb}')
out = out.drop_duplicates(claves)
os.makedirs('datos', exist_ok=True)
out.to_parquet(SALIDA, index=False)
print('Guardado', SALIDA, len(out), 'filas')

# cobertura del cruce contra el historico del dashboard (si esta disponible)
try:
    h = pd.read_parquet('datos/ventas_bdd.parquet', columns=claves + ['Venta'])
    h = h[(h['Fecha'] >= '2025-01-01') & (h['Fecha'] <= HASTA)]
    mm = h.merge(out[claves + ['EntraCD']], on=claves, how='left')
    ok = mm['EntraCD'].notna()
    print(f'Cobertura del cruce: {ok.mean():.1%} de las lineas | {mm.loc[ok, "Venta"].sum() / mm["Venta"].sum():.1%} de la venta')
except Exception as e:
    print('No se pudo medir la cobertura:', repr(e))
