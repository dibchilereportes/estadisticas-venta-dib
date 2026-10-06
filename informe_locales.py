# -*- coding: utf-8 -*-
"""Informe diario de locales / webs / marketplaces (DIB, Decostore-Bazhars, DECOEXPRESS).
Uso: python informe_locales.py AAAA-MM-DD salida.xlsx [--datos carpeta]
Fuentes (carpeta --datos): ventas_bdd.parquet (miles), metas_local_2026.csv, historico_local_2025.csv.
NO envia correo."""
import sys, argparse, calendar, os
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

# (cc, etiqueta, selector). Selector: ('local', nombre) | ('f', empresa, columna, valor) | None (sin fuente en la plataforma)
BAZ = [(515,'Parque Arauco','BAZHARS PARQUE ARAUCO'),(162,'Plaza Trebol','BAZHARS TREBOL'),(579,'Vitacura','BAZHARS VITACURA'),
       (125,'Montemar','BAZHARS MONTEMAR'),(128,'La Dehesa','BAZHARS LA DEHESA'),(520,'Vivo La Serena','BAZHARS LA SERENA'),
       (381,'Temuco Los Pablos','BAZHARS TEMUCO')]
WEB_BAZ = (750,'Web bazhars',('f','DECOSTORE','Canal_N2','Web'))
MKP_DECO = [(405,'Market Place Falabella',('f','EDUARDO DIB','Canal_N3','Falabella')),
            (408,'Market Place Paris',None),(406,'Mercado Libre',None),(785,'Proyectos',None),(409,'Market Place Ripley',None)]
DIB = [(369,'Outlet Park','DIB VIÑA OUTLET PARK'),(360,'Dib Rancagua','DIB RANCAGUA'),(377,'Vivo La Florida','DIB LA FLORIDA'),
       (306,'Outlet El Salto','DIB OUTLET EL SALTO'),(370,'Temuco','DIB TEMUCO VIVO'),(395,'Puerto Montt Costanera','DIB PUERTO MONTT COSTANERA'),
       (390,'Outlet Alerce','DIB PUERTO MONTT ALERCE'),(385,'La Fabrica','DIB SAN JOAQUIN LA FABRICA'),(153,'Easton Center','DIB QUILICURA EASTON CENTER'),
       (315,'Local 315','DIB VIÑA LOCAL ALFOMBRAS'),(184,'Vivo Outlet Maipu','DIB MAIPU VIVO'),(207,'Local 207','DIB VIÑA LOCAL TELAS'),
       (364,'Plaza Oeste','DIB PLAZA OESTE'),(375,'Easton Temuco','DIB TEMUCO EASTON')]
WEB_DIB = (7401,'Web Dib',('f','EDUARDO DIB','Canal_N3','Web DIB'))
DEXP = [(152,'Marketplaces',('f','DECOEXPRESS','Canal_N2','Marketplace')),(740,'Web',('f','DECOEXPRESS','Canal_N2','Web'))]

def cargar(datos, fecha):
    v = pd.read_parquet(os.path.join(datos,'ventas_bdd.parquet'), columns=['local','Fecha','Venta','Empresa','Canal_N2','Canal_N3'])
    v['Venta'] = v['Venta'].astype('float64')*1000
    v = v[(v.Fecha>=min(fecha.replace(day=1), fecha-pd.Timedelta(days=20)))&(v.Fecha<=fecha)]
    m = pd.read_csv(os.path.join(datos,'metas_local_2026.csv'), encoding='utf-8-sig')
    h = pd.read_csv(os.path.join(datos,'historico_local_2025.csv'), encoding='utf-8-sig')
    return v, m, h

def serie(v, sel, fecha):
    if sel is None: return 0.0, 0.0
    if isinstance(sel, str): x = v[v['local']==sel]
    else: x = v[(v.Empresa==sel[1])&(v[sel[2]]==sel[3])]
    x = x[x.Fecha>=fecha.replace(day=1)]
    return float(x[x.Fecha==fecha].Venta.sum()), float(x.Venta.sum())

def activo(v, sel, fecha):
    return bool((v['local']==sel).any())

def fila(cc, etq, sel, v, m, h, fecha, faltantes):
    d, a = serie(v, sel, fecha)
    mm = m[(m.cc==cc)&(m.Mes==fecha.month)].Meta
    meta = float(mm.iloc[0]) if len(mm) else None
    if meta is None: faltantes.append((cc, etq))
    hh = h[(h.cc==cc)&(h.Mes==fecha.month)].Venta
    ant = float(hh.iloc[0]) if len(hh) else 0.0
    return dict(cc=cc, nombre=etq, dia=round(d), acum=round(a), meta=meta, ant=round(ant))

def bloque(lista, v, m, h, fecha, faltantes):
    out = []
    for it in lista:
        cc, etq, sel = it
        if not activo(v, sel, fecha): continue   # local cerrado / sin ventas en los ultimos 20 dias
        out.append(fila(cc, etq, sel, v, m, h, fecha, faltantes))
    return out

def total(nombre, rows):
    metas = [r['meta'] for r in rows if r['meta'] is not None]
    return dict(cc=None, nombre=nombre, dia=sum(r['dia'] for r in rows), acum=sum(r['acum'] for r in rows),
                meta=sum(metas) if metas else None, ant=sum(r['ant'] for r in rows), total=True)

THIN = Side(style='thin', color='BFBFBF')
def escribir(secciones, fecha, ruta, faltantes):
    wb = Workbook(); ws = wb.active; ws.title = 'Informe'
    dias = calendar.monthrange(fecha.year, fecha.month)[1]
    ws['A1'] = 'Día'; ws['B1'] = fecha.day; ws['C1'] = fecha.strftime('%d-%m-%Y'); ws['G1'] = fecha.day/dias; ws['G1'].number_format = '0,0%'.replace(',', '.') if False else '0.0%'; ws['H1'] = dias
    ws['A1'].font = ws['B1'].font = Font(bold=True)
    fh = PatternFill('solid', fgColor='1F3864'); ft = PatternFill('solid', fgColor='D9E1F2')
    r = 3
    for titulo, filas, mostrar_hdr in secciones:
        ws.cell(r, 2, titulo).font = Font(bold=True, size=12); r += 1
        for j, t in enumerate(['VentaDiaria','VentaAcumulada','Meta','Igual Mes Año Ant','% Sobre Metas','% Sobre Años Anteriores'], 3):
            c = ws.cell(r, j, t); c.font = Font(bold=True, color='FFFFFF'); c.fill = fh; c.alignment = Alignment(horizontal='center', wrap_text=True)
        r += 1
        for f in filas:
            if f.get('cc') is not None: ws.cell(r, 1, f['cc'])
            ws.cell(r, 2, f['nombre'])
            ws.cell(r, 3, f['dia']); ws.cell(r, 4, f['acum'])
            ws.cell(r, 5, f['meta'] if f['meta'] is not None else 's/meta'); ws.cell(r, 6, f['ant'])
            ws.cell(r, 7, (f['acum']/f['meta']) if f['meta'] else 's/meta')
            ws.cell(r, 8, (f['acum']/f['ant']) if f['ant'] else 's/ant')
            for j in (3,4,5,6): ws.cell(r, j).number_format = '#,##0'
            for j in (7,8): ws.cell(r, j).number_format = '0.0%'
            for j in (5,7,8): ws.cell(r, j).alignment = Alignment(horizontal='right')
            if f.get('total'):
                for j in range(2, 9): ws.cell(r, j).font = Font(bold=True); ws.cell(r, j).fill = ft
            for j in range(2, 9): ws.cell(r, j).border = Border(bottom=THIN)
            r += 1
        r += 1
    ws.column_dimensions['A'].width = 7; ws.column_dimensions['B'].width = 26
    for col in 'CDEF': ws.column_dimensions[col].width = 16
    ws.column_dimensions['G'].width = 13; ws.column_dimensions['H'].width = 16
    ws.freeze_panes = 'A3'
    if faltantes:
        ws.cell(r, 2, 'Meta pendiente de carga en ' + fecha.strftime('%m-%Y') + ': ' + ', '.join(sorted({n for _, n in faltantes}))).font = Font(italic=True, color='C00000')
    wb.save(ruta)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('fecha'); ap.add_argument('salida'); ap.add_argument('--datos', default='datos')
    a = ap.parse_args(); fecha = pd.Timestamp(a.fecha)
    v, m, h = cargar(a.datos, fecha); falt = []
    baz = bloque(BAZ, v, m, h, fecha, falt); wb_ = fila(*WEB_BAZ[:2], WEB_BAZ[2], v, m, h, fecha, falt)
    baz = sorted(baz + [wb_], key=lambda x: -x['acum'])
    mk = [fila(cc, e, s, v, m, h, fecha, falt) for cc, e, s in MKP_DECO]
    t_baz = total('Total Bazhars', baz); t_deco = total('Total Decostore', baz + mk)
    dib = sorted(bloque(DIB, v, m, h, fecha, falt), key=lambda x: -x['acum']); t_dib = total('Total Dib', dib)
    wd = fila(*WEB_DIB[:2], WEB_DIB[2], v, m, h, fecha, falt)
    dx = [fila(cc, e, s, v, m, h, fecha, falt) for cc, e, s in DEXP]
    sec = [('Ventas Decostore %d' % fecha.year, baz + [t_baz] + mk + [t_deco], True),
           ('Ventas Dib %d' % fecha.year, dib + [t_dib], True), ('Web Dib %d' % fecha.year, [wd], True),
           ('Ventas DecoExpress %d' % fecha.year, dx, True)]
    escribir(sec, fecha, a.salida, falt)
    print('OK', a.salida, '| metas faltantes:', sorted({n for _, n in falt}) or 'ninguna')

if __name__ == '__main__': main()
