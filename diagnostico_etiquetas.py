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

paso('4. La vista YA trae x_etiquetas_texto y x_sale_order_name: cobertura desde 2026-08-01')
try:
    from collections import Counter
    dom = [('x_date', '>=', '2026-08-01')]
    n = call(VISTA, 'search_count', dom)
    tot = Counter(); cnt = Counter(); porcta = {}; con_so = 0; filas_n = 0
    for off in range(0, n, 5000):
        for r in call(VISTA, 'search_read', dom, fields=['x_etiquetas_texto', 'x_sale_order_name', 'x_cuenta_analytica', 'x_total_venta'], offset=off, limit=5000):
            filas_n += 1
            et = r['x_etiquetas_texto'] or ''; et = et if et and et is not False else ''
            so = r['x_sale_order_name'] or ''
            con_so += 1 if so and so is not False else 0
            cta = r['x_cuenta_analytica'] or '(sin cuenta)'
            v = r['x_total_venta'] or 0
            cnt[et or '(vacio)'] += 1; tot[et or '(vacio)'] += v
            porcta.setdefault(cta, Counter())['con' if et else 'sin'] += 1
    print(f'{filas_n} filas | con pedido (x_sale_order_name): {con_so}')
    print('valores de x_etiquetas_texto (filas, venta $):')
    for k, c in cnt.most_common(25): print(f'   {k!r}: {c} filas, ${tot[k]:,.0f}')
    print('por cuenta analitica (con/sin etiqueta):', {k: dict(v) for k, v in sorted(porcta.items(), key=lambda x: -sum(x[1].values()))[:12]})
    ej = call(VISTA, 'search_read', [('x_sale_order_name', '=', 'S177174')], fields=['x_folio', 'x_etiquetas_texto', 'x_cuenta_analytica', 'x_date'], limit=3)
    print('pedido S177174 (el de tu captura):', ej)
except Exception as e: print('ERROR', str(e)[:300])

paso('5. Ventas de NO-tienda sin etiqueta: ¿tienen pedido? (desde 2026-08-01)')
try:
    import re
    from collections import Counter
    dom = [('x_date', '>=', '2026-08-01')]
    n = call(VISTA, 'search_count', dom)
    tienda = re.compile(r'^(DIB|BAZHARS) (?!WEB$)')
    sin = []; cnt = Counter(); vta = Counter(); porcta = Counter()
    for off in range(0, n, 5000):
        for r in call(VISTA, 'search_read', dom, fields=['x_etiquetas_texto', 'x_sale_order_name', 'x_cuenta_analytica', 'x_folio', 'x_tipo_dte', 'x_customer', 'x_date', 'x_total_venta'], offset=off, limit=5000):
            cta = r['x_cuenta_analytica'] or ''
            if not isinstance(cta, str) or tienda.match(cta): continue
            if r['x_etiquetas_texto']: continue
            so = bool(r['x_sale_order_name'])
            cnt['con pedido' if so else 'SIN pedido'] += 1
            vta['con pedido' if so else 'SIN pedido'] += r['x_total_venta'] or 0
            porcta[cta] += 1
            sin.append(r)
    print('lineas de no-tienda sin etiqueta:', dict(cnt), '| venta $:', {k: round(v) for k, v in vta.items()})
    print('por cuenta analitica:', dict(porcta.most_common(10)))
    docs = {}
    for r in sin:
        k = (r['x_folio'], r['x_tipo_dte']); d = docs.setdefault(k, {'v': 0, 'n': 0, 'r': r}); d['v'] += r['x_total_venta'] or 0; d['n'] += 1
    print('documentos distintos:', len(docs), '| 15 mayores (folio, tipo, cuenta, cliente, fecha, lineas, venta, pedido):')
    for (f, t), d in sorted(docs.items(), key=lambda x: -abs(x[1]['v']))[:15]:
        r = d['r']; print('  ', f, t, r['x_cuenta_analytica'], r['x_customer'], r['x_date'], d['n'], round(d['v']), r['x_sale_order_name'] or '-')
except Exception as e: print('ERROR', str(e)[:300])

paso('6. Las facturas SIN pedido: ¿donde viven sus etiquetas? (account.move / account.move.line)')
try:
    def campos_tag(modelo):
        f = call(modelo, 'fields_get', attributes=['string', 'type', 'relation'])
        return {k: (v['string'], v['type'], v.get('relation')) for k, v in f.items()
                if any(t in (k + ' ' + v['string']).lower() for t in ('tag', 'etiq'))}
    ctm = campos_tag('account.move'); ctl = campos_tag('account.move.line')
    print('account.move campos tag/etiqueta:', ctm)
    print('account.move.line campos tag/etiqueta:', ctl)
    def leer(mv):
        out = {'move': mv['name']}
        for k in ctm:
            if k in mv: out[k] = mv[k]
        return out
    def mostrar(domain, titulo):
        mvs = call('account.move', 'search_read', domain, fields=['name', 'ref'] + list(ctm), limit=3)
        print(titulo, '->', len(mvs), 'facturas')
        for mv in mvs:
            print('   ', leer(mv))
            lns = call('account.move.line', 'search_read', [('move_id', '=', mv['id']), ('display_type', '=', 'product')], fields=['name'] + list(ctl), limit=4)
            for l in lns: print('       linea:', {k: l[k] for k in ctl if k in l})
    mostrar([('name', '=', 'INV/2026/028332')], 'Ejemplo de tu captura INV/2026/028332')
    folios = [str(f) for (f, t) in list(docs.keys())[:12]] if 'docs' in globals() else []
    for fo in folios:
        try: mostrar([('l10n_latam_document_number', 'ilike', fo), ('move_type', 'in', ['out_invoice', 'out_refund'])], 'folio ' + fo)
        except Exception as e: print('folio', fo, 'ERROR', str(e)[:120])
except Exception as e: print('ERROR', str(e)[:300])
