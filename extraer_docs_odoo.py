"""
extraer_docs_odoo.py  -  Documentos tributarios (SII) a nivel documento: emitidos, recibidos y guías.

Una fila por documento. Fuentes:
  - account.move  (state=posted)  facturas, NC, ND, liquidaciones, DIN, etc. -> EMITIDO / RECIBIDO
  - pos.order     (solo boleta y nota de crédito)                            -> EMITIDO
  - stock.picking (hechos, con guía y folio)                                 -> GUIA_SALIDA / GUIA_ENTRADA

Salida: datos/docs_odoo.parquet   (se reemplaza completo en cada corrida, no es incremental)
Credenciales: variables de entorno ODOO_URL, ODOO_DB, ODOO_USER, ODOO_KEY (nunca en el archivo).
Uso:  python extraer_docs_odoo.py [AÑO_DESDE] [AÑO_HASTA]      (default 2025 2026)
      Canal N1/N2/N3 de las ventas se toma de datos/ventas_bdd.parquet si existe.
"""
import os
import sys
import xmlrpc.client
import numpy as np
import pandas as pd

_anios = [a for a in sys.argv[1:] if a.isdigit()]
DESDE = int(_anios[0]) if len(_anios) > 0 else 2025
HASTA = int(_anios[1]) if len(_anios) > 1 else 2026
REUSAR = '--reusar' in sys.argv          # reutiliza datos/docs_odoo_raw.pkl sin volver a Odoo
CARPETA = os.path.dirname(os.path.abspath(__file__))
SALIDA = os.path.join(CARPETA, 'datos', 'docs_odoo.parquet')
RAW = os.path.join(CARPETA, 'datos', 'docs_odoo_raw.pkl')
BDD = os.path.join(CARPETA, 'datos', 'ventas_bdd.parquet')
try:
    import pyarrow  # noqa: F401
    HAY_PARQUET = True
except ImportError:
    HAY_PARQUET = False

EMPRESAS = {
    'EDUARDO DIB H. Y CIA. LTDA.': 'EDUARDO DIB',
    'COMERCIAL DECOSTORE LIMITADA': 'DECOSTORE',
    'COMERCIAL DECOEXPRESS LIMITADA': 'DECOEXPRESS',
    'COMERCIAL EUROHOGAR LTDA.': 'EUROHOGAR',
    'TRANSPORTES HASKY LIMITADA': 'HASKY',
}
# códigos SII que forman parte del RCV / DTE (el resto son documentos internos de Odoo)
COD_SII = {33, 34, 39, 41, 43, 46, 52, 56, 61, 110, 111, 112, 914}
ESTADOS_OFICIALES = {'Proceso', 'Aceptado', 'Reparo'}
GRUPO_TIPO = {33: 'FACTURA', 34: 'FACTURA', 39: 'BOLETA', 41: 'BOLETA', 61: 'NOTA_CREDITO',
              56: 'NOTA_DEBITO', 43: 'LIQUIDACION'}


# ------------------------------------------------------------------ conexión
def conectar():
    url = os.environ['ODOO_URL'].strip().rstrip('/')
    db, user, key = (os.environ[k].strip() for k in ('ODOO_DB', 'ODOO_USER', 'ODOO_KEY'))
    uid = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common').authenticate(db, user, key, {})
    if not uid:
        sys.exit('Autenticación fallida: revisa ODOO_DB, ODOO_USER y ODOO_KEY.')
    srv = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object', allow_none=True)

    def call(model, method, *args, **kw):
        return srv.execute_kw(db, uid, key, model, method, list(args), kw)
    return call


def leer(call, model, dominio, campos, lote=3000):
    out, off = [], 0
    while True:
        r = call(model, 'search_read', dominio, fields=campos, limit=lote, offset=off, order='id')
        out += r
        print(f'  {model}: {len(out)} filas')
        if len(r) < lote:
            return out
        off += lote


def lbl(v):
    """many2one -> nombre (False -> '')"""
    return v[1] if isinstance(v, (list, tuple)) and len(v) > 1 else ''


def num(v):
    return 0.0 if v in (False, None) else float(v)


def entero(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


# ------------------------------------------------------------------ transformaciones
def filas_move(regs):
    filas = []
    for r in regs:
        cod = entero(r.get('sii_code'))
        saliente = r['move_type'].startswith('out_')
        total = abs(num(r.get('amount_total_signed', r.get('amount_total'))))
        neto = abs(num(r.get('amount_untaxed_signed', r.get('amount_untaxed'))))
        iva = abs(num(r['amount_tax_signed'])) if 'amount_tax_signed' in r else max(total - neto, 0.0)
        exento = 0.0
        if cod in (34, 41):          # documentos exentos: todo el monto es exento
            exento, neto = neto, 0.0
        filas.append({
            'fecha': r['invoice_date'], 'empresa_legal': lbl(r['company_id']),
            'sentido': 'EMITIDO' if saliente else 'RECIBIDO', 'origen': 'account.move',
            'cod_sii': cod, 'tipo_doc': lbl(r.get('document_class_id')),
            'folio': entero(r.get('sii_document_number')), 'estado_sii': r.get('sii_result') or '',
            'sucursal': lbl(r.get('branch_id')), 'bodega': '', 'tipo_operacion': '',
            'contraparte': lbl(r.get('partner_id')),
            'clave_pedido': (r.get('invoice_origin') or '').strip() or lbl(r.get('reversed_entry_id')),
            'neto': neto, 'exento': exento, 'iva': iva, 'total': total,
        })
    return filas


def filas_pos(regs):
    filas = []
    for r in regs:
        total = abs(num(r.get('amount_total')))
        iva = abs(num(r.get('amount_tax')))
        filas.append({
            'fecha': str(r['date_order'])[:10], 'empresa_legal': lbl(r['company_id']),
            'sentido': 'EMITIDO', 'origen': 'pos.order',
            'cod_sii': entero(r.get('sii_code')), 'tipo_doc': lbl(r.get('document_class_id')),
            'folio': entero(r.get('sii_document_number')), 'estado_sii': r.get('sii_result') or '',
            'sucursal': lbl(r.get('branch_id')), 'bodega': '', 'tipo_operacion': '',
            'contraparte': '', 'clave_pedido': r.get('name') or '',
            'neto': total - iva, 'exento': 0.0, 'iva': iva, 'total': total,
        })
    return filas


def filas_picking(regs, cod_clase):
    filas = []
    for r in regs:
        clase = r.get('document_class_id')
        tipo_op = lbl(r.get('picking_type_id'))
        filas.append({
            'fecha': str(r['date_done'])[:10], 'empresa_legal': lbl(r['company_id']),
            'sentido': 'GUIA_ENTRADA' if r.get('picking_type_code') == 'incoming' else 'GUIA_SALIDA',
            'origen': 'stock.picking',
            'cod_sii': cod_clase.get(clase[0], 52) if clase else 52, 'tipo_doc': lbl(clase),
            'folio': entero(r.get('sii_document_number')), 'estado_sii': r.get('sii_result') or '',
            'sucursal': lbl(r.get('branch_id')), 'bodega': tipo_op.split(':')[0].strip(),
            'tipo_operacion': tipo_op, 'contraparte': lbl(r.get('partner_id')),
            'clave_pedido': lbl(r.get('sale_id')) or r.get('name') or '',
            'neto': 0.0, 'exento': 0.0, 'iva': 0.0, 'total': 0.0,
        })
    return filas


def asignar_canal(df):
    """Canal N1/N2/N3 de ventas emitidas: se toma de ventas_bdd.parquet (mismo criterio que el
    dashboard de ventas); boletas POS sin match se clasifican por empresa/sucursal."""
    for c in ('Canal_N1', 'Canal_N2', 'Canal_N3'):
        df[c] = pd.Series([None] * len(df), index=df.index, dtype='object')
    usa_bdd = os.path.exists(BDD) and HAY_PARQUET
    if not usa_bdd:
        print('  [!] sin pyarrow o sin ventas_bdd.parquet: canal N1/N2/N3 NO se asigna (solo boletas POS)')
    if usa_bdd:
        # OJO: 'Empresa' de la BDD es clasificación de negocio (p.ej. Marketplace Decostore figura como
        # EDUARDO DIB), no la empresa legal que emitió -> el cruce NO usa empresa: tipo + folio + fecha.
        b = pd.read_parquet(BDD, columns=['Factura', 'TipoDoc', 'Canal_N1', 'Canal_N2', 'Canal_N3',
                                          'Fecha', 'Venta'])
        b = b[b['Factura'].notna()].copy()
        b['folio'] = b['Factura'].astype('int64')
        b['fecha'] = pd.to_datetime(b['Fecha']).dt.normalize()
        b['anio'] = b['fecha'].dt.year.astype('int16')
        b['abs_venta'] = b['Venta'].abs()
        b = b.rename(columns={'TipoDoc': 'grupo'}).sort_values('abs_venta', ascending=False)
        cols = ['Canal_N1', 'Canal_N2', 'Canal_N3']
        df['grupo'] = df['cod_sii'].map(GRUPO_TIPO)
        df['fecha_d'] = df['fecha'].dt.normalize()
        # 1) tipo + folio + fecha
        k1 = ['grupo', 'folio', 'fecha']
        b1 = b.drop_duplicates(k1)[k1 + cols]
        m = df.drop(columns=cols).merge(b1.rename(columns={'fecha': 'fecha_d'}).rename(
            columns={'grupo': 'grupo', 'folio': 'folio'}), left_on=['grupo', 'folio', 'fecha_d'],
            right_on=['grupo', 'folio', 'fecha_d'], how='left')
        # 2) respaldo: tipo + folio + año, solo si ese folio es único en la BDD ese año
        falta = m['Canal_N1'].isna() & (m['sentido'] == 'EMITIDO') & m['grupo'].notna()
        if falta.any():
            k2 = ['grupo', 'folio', 'anio']
            b2 = b.drop_duplicates(k2 + ['fecha'], keep='first').drop_duplicates(k2, keep=False)[k2 + cols]
            extra = m.loc[falta, k2].merge(b2, on=k2, how='left')
            m.loc[falta, cols] = extra[cols].values
        df = m.drop(columns=['grupo', 'fecha_d'])
        for c in cols:
            df[c] = df[c].astype('object')
    # respaldo boletas/NC de POS: locales por empresa
    pos = (df['origen'] == 'pos.order') & df['Canal_N1'].isna()
    bazhars = (df['empresa'] == 'DECOSTORE') | df['sucursal'].str.contains('Vitacura', case=False, na=False)
    df.loc[pos, 'Canal_N1'] = 'B2C'
    df.loc[pos, 'Canal_N2'] = np.where(bazhars[pos], 'Locales Bazhars', 'Locales DIB')
    df.loc[pos, 'Canal_N3'] = df.loc[pos, 'sucursal']
    if usa_bdd:
        # Decoexpress no está en la BDD de ventas antes de agosto-2026: se clasifica por tipo de
        # documento (boleta = B2C, factura = B2B) hasta definir su clasificación de canales.
        dx = (df['empresa'] == 'DECOEXPRESS') & (df['sentido'] == 'EMITIDO') & df['Canal_N1'].isna()
        df.loc[dx & df['cod_sii'].isin([39, 41]), ['Canal_N1', 'Canal_N2', 'Canal_N3']] = [
            'B2C', 'Decoexpress (sin detalle)', 'Decoexpress (sin detalle)']
        df.loc[dx & df['cod_sii'].isin([33, 34]), ['Canal_N1', 'Canal_N2', 'Canal_N3']] = [
            'B2B', 'Decoexpress (sin detalle)', 'Decoexpress (sin detalle)']
        sin = (df['sentido'] == 'EMITIDO') & df['Canal_N1'].isna()
        df.loc[sin, ['Canal_N1', 'Canal_N2', 'Canal_N3']] = 'Sin clasificar'
    return df


def armar(filas):
    df = pd.DataFrame(filas)
    df['fecha'] = pd.to_datetime(df['fecha'])
    df['anio'] = df['fecha'].dt.year.astype('int16')
    df['mes'] = df['fecha'].dt.month.astype('int8')
    df['empresa'] = df['empresa_legal'].map(EMPRESAS).fillna(df['empresa_legal'])
    df['es_sii'] = df['cod_sii'].isin(COD_SII)
    # emitidos: oficial si el SII lo recibió (Proceso/Aceptado/Reparo); recibidos y guías de
    # entrada las emite un tercero, no tienen estado SII en Odoo -> oficial si es tipo SII
    df['oficial'] = df['estado_sii'].isin(ESTADOS_OFICIALES) | (
        df['sentido'].isin(['RECIBIDO', 'GUIA_ENTRADA']) & df['es_sii'])
    df['signo'] = np.where(df['cod_sii'].eq(61), -1, 1).astype('int8')   # NC resta
    return asignar_canal(df)


# ------------------------------------------------------------------ main
def extraer():
    call = conectar()
    f1, f2 = f'{DESDE}-01-01', f'{HASTA}-12-31'
    filas = []

    fm = call('account.move', 'fields_get', attributes=['type'])
    campos = [c for c in ('company_id', 'document_class_id', 'sii_code', 'sii_document_number',
                          'sii_result', 'branch_id', 'move_type', 'invoice_date', 'partner_id',
                          'invoice_origin', 'reversed_entry_id', 'amount_untaxed_signed',
                          'amount_tax_signed', 'amount_total_signed', 'amount_untaxed',
                          'amount_total') if c in fm]
    print('account.move ...')
    dom = [('state', '=', 'posted'),
           ('move_type', 'in', ['out_invoice', 'out_refund', 'in_invoice', 'in_refund']),
           ('invoice_date', '>=', f1), ('invoice_date', '<=', f2)]
    filas += filas_move(leer(call, 'account.move', dom, campos))

    print('pos.order (boletas y NC) ...')
    try:
        dom = [('state', 'in', ['paid', 'done', 'invoiced']),
               ('date_order', '>=', f1 + ' 00:00:00'), ('date_order', '<=', f2 + ' 23:59:59'),
               '|', ('document_class_id.name', 'ilike', 'Boleta'),
               ('document_class_id.name', 'ilike', 'Crédito')]
        campos = ['company_id', 'branch_id', 'document_class_id', 'sii_code', 'sii_document_number',
                  'sii_result', 'date_order', 'amount_total', 'amount_tax', 'name']
        filas += filas_pos(leer(call, 'pos.order', dom, campos))
    except Exception as e:
        print(f'  [!] pos.order omitido: {str(e)[:200]}')

    print('stock.picking (guías) ...')
    cod_clase = {c['id']: entero(c.get('sii_code')) for c in
                 call('sii.document_class', 'search_read', [], fields=['sii_code'])}
    fp = call('stock.picking', 'fields_get', attributes=['type'])
    campos = [c for c in ('company_id', 'branch_id', 'picking_type_id', 'picking_type_code',
                          'document_class_id', 'sii_document_number', 'sii_result', 'date_done',
                          'name', 'sale_id', 'partner_id') if c in fp]
    dom = [('state', '=', 'done'), ('picking_type_code', 'in', ['outgoing', 'internal', 'incoming']),
           ('document_class_id', '!=', False), ('sii_document_number', '!=', False),
           ('date_done', '>=', f1 + ' 00:00:00'), ('date_done', '<=', f2 + ' 23:59:59')]
    filas += filas_picking(leer(call, 'stock.picking', dom, campos), cod_clase)

    return filas


def main():
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    if REUSAR and os.path.exists(RAW):
        print(f'Reutilizando {RAW} (sin consultar Odoo)')
        filas = pd.read_pickle(RAW)
    else:
        filas = extraer()
        pd.to_pickle(filas, RAW)          # respaldo antes de clasificar: no se pierde si algo falla
        print(f'\nRespaldo de la extracción: {RAW}  ({len(filas):,} documentos)')
    df = armar(filas)
    if HAY_PARQUET:
        df.to_parquet(SALIDA, index=False)
        print(f'Guardado: {SALIDA}  ({len(df):,} documentos)')
    else:
        destino = SALIDA.replace('.parquet', '.pkl')
        df.to_pickle(destino)
        print(f'Guardado (sin pyarrow): {destino}  ({len(df):,} documentos)')
    print(df.groupby(['anio', 'sentido']).size().unstack(fill_value=0))
    sin = df[(df['sentido'] == 'EMITIDO') & (df['Canal_N1'] == 'Sin clasificar')]
    print(f'Emitidos sin canal: {len(sin):,} ({len(sin) / max(1, (df.sentido == "EMITIDO").sum()):.1%})')


if __name__ == '__main__':
    main()
