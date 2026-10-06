# -*- coding: utf-8 -*-
"""
SOLO LECTURA. Vuelca de la vista Odoo las llaves de clasificacion gerencial
(cliente, branch, canal, cuenta analitica, linea) agregadas por dia, para
reconciliar contra el informe de ventas del CD. No toca ventas_bdd.parquet ni el dashboard.
Salida: diagnostico/clasif_diaria.csv.gz  (se guarda en el repo PRIVADO de datos)
Rangos: sep-2025 (igual mes ano anterior) y 2026-09-01 en adelante.
"""
import os, xmlrpc.client
import numpy as np
import pandas as pd

URL, DB, USER, KEY = (os.environ[k] for k in ('ODOO_URL', 'ODOO_DB', 'ODOO_USER', 'ODOO_KEY'))
MODELO = 'x_bi_sql_view.informe_ventas_cuadratura_v7_15'
CAMPOS = ['x_date', 'x_customer', 'x_rut', 'x_branch', 'x_canal', 'x_cuenta_analytica',
          'x_linea', 'x_tipo_dte', 'x_estado_documento', 'x_total_venta']
DOM = ['|', '&', ('x_date', '>=', '2025-09-01'), ('x_date', '<=', '2025-10-05'),
       ('x_date', '>=', '2026-09-01')]

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
    print(f'  {min(off + 5000, n)}/{n}')

df = pd.DataFrame(filas).drop(columns=['id'], errors='ignore')
for c in CAMPOS[1:-1]:
    df[c] = df[c].map(lambda v: np.nan if v is False else v)
g = (df.groupby(CAMPOS[:-1], dropna=False, as_index=False)
       .agg(venta=('x_total_venta', 'sum'), lineas=('x_total_venta', 'size')))
os.makedirs('diagnostico', exist_ok=True)
g.to_csv('diagnostico/clasif_diaria.csv.gz', index=False, encoding='utf-8-sig')
print('Filas agregadas:', len(g), '| venta total:', f"{g.venta.sum():,.0f}")
