# -*- coding: utf-8 -*-
"""
SOLO LECTURA sobre Odoo. Trae 2025 completo de la vista de ventas, aplica la clasificacion
gerencial y guarda una tabla diaria agregada (llave + linea de producto) en
datos/informe_cd_2025.parquet. No modifica ventas_bdd.parquet: sirve de base de
'igual mes ano anterior' para el informe diario y para analisis por clasificacion.
"""
import os
import xmlrpc.client
import numpy as np
import pandas as pd
from clasificacion_gerencial import clasificar

URL, DB, USER, KEY = (os.environ[k] for k in ('ODOO_URL', 'ODOO_DB', 'ODOO_USER', 'ODOO_KEY'))
MODELO = 'x_bi_sql_view.informe_ventas_cuadratura_v7_15'
CAMPOS = ['x_date', 'x_customer', 'x_branch', 'x_canal', 'x_cuenta_analytica', 'x_linea',
          'x_tipo_dte', 'x_total_venta', 'x_margen_contribucion']
DOM = [('x_date', '>=', '2025-01-01'), ('x_date', '<=', '2025-12-31')]
SALIDA = 'datos/informe_cd_2025.parquet'

common = xmlrpc.client.ServerProxy(f'{URL}/xmlrpc/2/common')
uid = common.authenticate(DB, USER, KEY, {})
if not uid:
    raise SystemExit('No se pudo autenticar en Odoo')
m = xmlrpc.client.ServerProxy(f'{URL}/xmlrpc/2/object')
call = lambda metodo, *a, **k: m.execute_kw(DB, uid, KEY, MODELO, metodo, list(a), k)

n = call('search_count', DOM)
print('Registros 2025:', n)
filas = []
for off in range(0, n, 5000):
    filas.extend(call('search_read', DOM, fields=CAMPOS, offset=off, limit=5000))
    if (off // 5000) % 10 == 0:
        print(f'  {min(off + 5000, n)}/{n}')

df = pd.DataFrame(filas).drop(columns=['id'], errors='ignore')
for c in CAMPOS[1:7]:
    df[c] = df[c].map(lambda v: np.nan if v is False else v)
df = df.join(clasificar(df))
llave = ['x_date', 'x_customer', 'x_branch', 'x_canal', 'x_cuenta_analytica', 'x_linea', 'x_tipo_dte',
         'ClasifGerencial', 'LineaComercial', 'BloqueInforme', 'EntraInforme_CD', 'MotivoExclusion']
g = (df.groupby(llave, dropna=False, as_index=False)
       .agg(venta=('x_total_venta', 'sum'), contribucion=('x_margen_contribucion', 'sum'),
            lineas=('x_total_venta', 'size')))
os.makedirs('datos', exist_ok=True)
g.to_parquet(SALIDA, index=False)
print('Filas:', len(g), '| venta total:', f"{g.venta.sum():,.0f}",
      '| entra al informe:', f"{g.loc[g.EntraInforme_CD == 'SI', 'venta'].sum():,.0f}")
