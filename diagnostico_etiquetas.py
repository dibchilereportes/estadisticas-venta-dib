# -*- coding: utf-8 -*-
"""Diagnostico SOLO LECTURA: ¿se puede rescatar 'Etiquetas' (sale.order.tag_ids) para las estadisticas de venta?
Revisa (1) si la vista de ventas ya trae algun campo de etiqueta/pedido, (2) si la API deja leer etiquetas
de sale.order y (3) que porcentaje de las ventas recientes se puede enlazar a su pedido de venta por folio.
No escribe nada en Odoo ni en los repos."""
import os, xmlrpc.client
url, db, user, key = (os.environ[k] for k in ('ODOO_URL', 'ODOO_DB', 'ODOO_USER', 'ODOO_KEY'))
uid = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common').authenticate(db, user, key, {})
m = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object', allow_none=True)
def call(modelo, metodo, *a, **kw): return m.execute_kw(db, uid, key, modelo, metodo, list(a), kw)
def paso(t): print('\n=== ' + t)
VISTA = 'x_bi_sql_view.informe_ventas_cuadratura_v7_15'

paso('1. Campos de la vista que podrian traer etiqueta / pedido')
try:
    f = call(VISTA, 'fields_get', attributes=['string', 'type'])
    ks = [k for k, v in f.items() if any(s in (k + ' ' + v['string']).lower() for s in ('tag', 'etiq', 'pedido', 'orden', 'origen', 'sale', 'order', 'move', 'factura_id'))]
    print(len(f), 'campos en total. Candidatos:', {k: f[k]['string'] for k in ks} or 'NINGUNO')
except Exception as e: print('ERROR', str(e)[:300])

paso('2. sale.order.tag_ids: lectura y etiquetas existentes')
try:
    f = call('sale.order', 'fields_get', ['tag_ids'], attributes=['string', 'type', 'relation'])
    print(f)
    rel = f['tag_ids']['relation']
    tags = call(rel, 'search_read', [], fields=['name'], limit=300)
    print(len(tags), 'etiquetas en', rel, ':', [t['name'] for t in tags][:60])
    print('pedidos con alguna etiqueta:', call('sale.order', 'search_count', [('tag_ids', '!=', False)]), 'de', call('sale.order', 'search_count', []))
except Exception as e: print('ERROR', str(e)[:300])

paso('3. Enlace venta -> factura -> pedido (muestra de 60 folios recientes, DIB y Decoexpress)')
try:
    filas = call(VISTA, 'search_read', [('x_date', '>=', '2026-10-01'), ('x_tipo_dte', 'ilike', 'factura')],
                 fields=['x_folio', 'x_numero_documento', 'x_cuenta_analytica', 'x_tipo_dte'], limit=60)
    ok = 0; con_tag = 0; detalles = []
    for r in filas:
        folio = str(r['x_folio'] or '').strip()
        if not folio or folio == 'False': continue
        mv = []
        for campo in ('l10n_latam_document_number', 'name'):
            try:
                mv = call('account.move', 'search_read', [(campo, 'ilike', folio), ('move_type', 'in', ['out_invoice', 'out_refund'])],
                          fields=['name', 'invoice_origin'], limit=3)
            except Exception: mv = []
            if mv: break
        orig = next((x['invoice_origin'] for x in mv if x.get('invoice_origin')), None)
        if not orig: continue
        so = call('sale.order', 'search_read', [('name', '=', orig.split(',')[0].strip())], fields=['name', 'tag_ids'], limit=1)
        if so:
            ok += 1
            if so[0]['tag_ids']:
                con_tag += 1
                if len(detalles) < 8: detalles.append((folio, r['x_cuenta_analytica'], so[0]['name'], so[0]['tag_ids']))
    print(f'{len(filas)} facturas de muestra | enlazadas a pedido: {ok} | con etiqueta: {con_tag}')
    print('ejemplos (folio, cuenta analitica, pedido, ids de etiqueta):', detalles)
except Exception as e: print('ERROR', str(e)[:300])
