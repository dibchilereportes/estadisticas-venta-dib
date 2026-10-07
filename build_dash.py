# -*- coding: utf-8 -*-
"""Genera el dashboard HTML autocontenido desde ventas_bdd.parquet."""
import sys, os, json, gzip, base64, hashlib, secrets
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TOP_CLIENTES = 300
DIMS = ['Empresa','Año','Mes','Canal_N1','Canal_N2','Canal_N3','DesgloseEntrega','local','LINEA_STD',
        'CATEGORIA_STD','FAMILIA_STD','Descontinuado','TipoDoc','Cli','Vendedor','Negocio','PuntoVenta','CliGer','Segmento','LineaCom','BloqueInf','EntraCD']
# Dimensiones de desglose disponibles en la vista Comparativo (Empresa/Año van aparte,
# como filtro y como eje de comparacion respectivamente).
COMP_DIMS = ['Canal_N1','Canal_N2','Canal_N3','local','PuntoVenta','CliGer','LineaCom','LINEA_STD','CATEGORIA_STD','Vendedor','TipoDoc']

def _codificar_dim(serie):
    """str(valor) + relleno de vacios + categorias ordenadas -> (dims, codigos, dtype)."""
    s = pd.Series([str(x) for x in serie], index=serie.index)
    s = s.replace({'nan':'(sin dato)','None':'(sin dato)','':'(sin dato)',
                   '<NA>':'(sin dato)','NaT':'(sin dato)'})
    cats = sorted(s.unique().tolist())
    idx = {x: i for i, x in enumerate(cats)}
    cod = np.array([idx[x] for x in s])
    dt = 'u1' if len(cats) <= 255 else ('u2' if len(cats) <= 65535 else 'i4')
    return cats, cod.astype(dt), dt

FUERA = '(fuera de locales)'
MKP_DECO_N3 = {'Falabella','Paris','Ripley','Mercado Libre','Walmart'}

def clasificar_puntos_venta(v):
    """Negocio (DIB / DECOSTORE / DECOEXPRESS) y PuntoVenta (local, web o marketplace) por fila.
    Las filas que no son local/web/marketplace propio quedan en '(fuera de locales)'.
    Vitacura (Bazhars) esta contabilizado bajo la empresa EDUARDO DIB, y Falabella-marketplace
    tambien: por eso el negocio se deriva del canal y no de la columna Empresa."""
    emp = v['Empresa'].astype(str); n2 = v['Canal_N2'].astype(str); n3 = v['Canal_N3'].astype(str)
    loc = v['local'].astype(str)
    neg = pd.Series(FUERA, index=v.index); pv = pd.Series(FUERA, index=v.index)
    def poner(mask, negocio, punto):
        neg[mask] = negocio
        pv[mask] = punto if isinstance(punto, str) else punto[mask]
    # Locales
    bz = n2.eq('Locales Bazhars') | (n2.eq('Locales DIB') & loc.str.contains('BUENAVENTURA'))
    poner(bz, 'DECOSTORE', loc)
    poner(n2.eq('Locales DIB') & ~bz, 'DIB', loc)
    # Webs
    poner(n2.eq('Web') & emp.eq('DECOSTORE'), 'DECOSTORE', 'Web Bazhars')
    poner(n2.eq('Web') & emp.eq('EDUARDO DIB') & n3.isin(['Web','Web DIB']), 'DIB', 'Web DIB')
    poner(n2.eq('Web') & emp.eq('DECOEXPRESS'), 'DECOEXPRESS', 'Web DECOEXPRESS')
    # Marketplaces
    mk_baz = n2.eq('Marketplace') & ((emp.eq('DECOSTORE')) | (emp.eq('EDUARDO DIB') & n3.isin(MKP_DECO_N3)))
    poner(mk_baz, 'DECOSTORE', ('MKP ' + n3).where(n3.isin(MKP_DECO_N3), 'MKP Bazhars (sin detalle)'))
    poner(n2.eq('Marketplace') & emp.eq('DECOEXPRESS'), 'DECOEXPRESS', 'Marketplaces DECOEXPRESS')
    return neg, pv

def _datos_cd(parquet):
    """Datos del 'Informe CD' para la vista de niveles del dashboard (aggregados por mes). Tolerante a fallos."""
    try:
        import informe_cd as icd
        d = os.path.dirname(os.path.abspath(parquet))
        v26 = icd.preparar(pd.read_parquet(os.path.join(d, 'informe_cd_2026.parquet')))
        v25 = icd.preparar(pd.read_parquet(os.path.join(d, 'informe_cd_2025.parquet')), anio_anterior=True)
        t = pd.concat([v26, v25], ignore_index=True)
        t['a'] = t['f'].dt.year; t['m'] = t['f'].dt.month
        g = (t.groupby(['a','m','bloque','emp','G','L','linea','vtaemp'], dropna=False)['venta'].sum().round().astype('int64').reset_index())
        mc = pd.read_csv(os.path.join(d, 'metas_cliente_2026.csv'), encoding='utf-8-sig')
        ml = pd.read_csv(os.path.join(d, 'metas_linea_2026.csv'), encoding='utf-8-sig')
        return {"hasta": f"{v26['f'].max():%Y-%m-%d}",
                "rows": [[int(r.a), int(r.m), r.bloque, r.emp, str(r.G), str(r.L), str(r.linea), int(bool(r.vtaemp)), int(r.venta)] for r in g.itertuples()],
                "mc": [[r.Linea, r.CategoriaGerencial, int(r.Mes), float(r.Meta)] for r in mc.itertuples()],
                "ml": [[r.Empresa, r.Linea, int(r.Mes), float(r.Meta)] for r in ml.itertuples()]}
    except Exception as e:
        print('AVISO: sin datos del informe CD para el dashboard:', e)
        return None

def _leer_metas(parquet):
    """Metas por local (metas_local_2026.csv junto al parquet) para el panel editable. Tolerante a fallos."""
    try:
        ruta = os.path.join(os.path.dirname(os.path.abspath(parquet)), 'metas_local_2026.csv')
        m = pd.read_csv(ruta, encoding='utf-8-sig')
        out = []
        for (cc, emp, nom), g in m.groupby(['cc','Empresa','Nombre'], sort=False):
            meses = [None]*12
            for _, r in g.iterrows(): meses[int(r.Mes)-1] = int(r.Meta)
            out.append([int(cc), emp, nom, meses])
        return out
    except Exception as e:
        print('AVISO: sin metas por local para el panel:', e)
        return []

def construir(parquet, template, salida, clave=None):
    v = pd.read_parquet(parquet)
    tot = v.groupby('ClienteNombre', observed=True).Venta.sum().sort_values(ascending=False)
    top = set(tot.head(TOP_CLIENTES).index)
    v['Cli'] = np.where(v.ClienteNombre.isin(top), v.ClienteNombre.astype(str), 'OTROS CLIENTES')
    v['Descontinuado'] = np.where(v.Descontinuado, 'Descontinuado', 'Vigente')
    # Unidades: solo lineas donde Cantidad significa unidades (ver UnidadValida en el ETL).
    v['Negocio'], v['PuntoVenta'] = clasificar_puntos_venta(v)
    # Niveles del informe CD (por fila). Vienen de la API (2026-08 en adelante) y del cruce historico
    # (datos/clasif_filas_hist.parquet). Lo que no tiene clasificacion queda como '(sin dato)'.
    for c in ('CliGer', 'LineaCom', 'BloqueInf', 'EntraCD'):
        if c not in v.columns:
            v[c] = np.nan
    lc = v['LineaCom'].astype(str)
    seg = np.where(lc.str.endswith('B2B'), 'B2B', np.where(lc.str.endswith('B2C'), 'B2C',
          np.where(lc.str.contains('VTA EMPRESA'), 'VENTA EMPRESA', 'nan')))
    # 2025 no tenia cuenta analitica que separara B2B/B2C: no se muestra una separacion que no es real
    v['Segmento'] = np.where(v['Año'] < 2026, 'nan', seg)
    v['Qval'] = np.where(v.UnidadValida, v.Cantidad, 0.0)
    v['L'] = 1
    c = (v.groupby(DIMS, observed=True, dropna=False)
           .agg(Q=('Qval','sum'), V=('Venta','sum'), C=('Costo','sum'), D=('L','sum'))
           .reset_index())
    sub = (f"{len(v):,} líneas · {v.Fecha.min():%d-%m-%Y} a {v.Fecha.max():%d-%m-%Y} · "
           f"cifras en miles de pesos").replace(',','.')

    # ---- cubo comparativo (vista "Comparativo", agosto-2026) -----------------
    # Tabla larga agrupada por (Empresa, Año, Dim, Valor) para cada dimension de
    # desglose en COMP_DIMS -- mucho mas chica que el cubo principal (no cruza
    # dimensiones entre si), y permite nunique real de clientes/documentos por
    # cada combinacion, cosa que el cubo principal no puede dar (ya viene sumado).
    piezas = []
    for dim in COMP_DIMS:
        g = (v.groupby(['Empresa','Año', dim], observed=True, dropna=False)
               .agg(V=('Venta','sum'), C=('Costo','sum'), Q=('Qval','sum'),
                    N=('ClienteKey','nunique'), M=('Factura','nunique'))
               .reset_index().rename(columns={dim: 'Valor'}))
        g.insert(2, 'Dim', dim)
        piezas.append(g)
    # fila TOTAL (Dim='TOTAL', Valor='(todos)'): nunique real de clientes/documentos
    # para toda la Empresa+Año, sin desglosar -- sumar el nunique de cada categoria
    # de un desglose sobredimensiona (un mismo cliente puede comprar por mas de un
    # canal/local/linea), asi que el total real necesita su propio groupby aparte.
    tot = (v.groupby(['Empresa','Año'], observed=True, dropna=False)
             .agg(V=('Venta','sum'), C=('Costo','sum'), Q=('Qval','sum'),
                  N=('ClienteKey','nunique'), M=('Factura','nunique'))
             .reset_index())
    tot.insert(2, 'Dim', 'TOTAL')
    tot.insert(3, 'Valor', '(todos)')
    piezas.append(tot)
    cmp_df = pd.concat(piezas, ignore_index=True)

    # ---- payload binario columnar --------------------------------------------
    # El formato anterior (JSON con 1,7 millones de números) reventaba la memoria de
    # Safari en iPhone al hacer JSON.parse. Ahora las columnas viajan como typed arrays
    # dentro de un solo buffer: el navegador crea vistas sobre él sin copiar ni parsear.
    header = {"n": len(c), "dims": {}, "cols": [], "meta": {"sub": sub, "metas": _leer_metas(parquet), "cd": _datos_cd(parquet)},
              "cmp": {"n": len(cmp_df), "dims": {}, "cols": []}}
    columnas = []                                   # (seccion, clave, dtype numpy, arreglo)
    for k in DIMS:
        cats, cod, dt = _codificar_dim(c[k])
        header["dims"][k] = cats
        columnas.append(('main', k, dt, cod))
    # Venta y Costo en float64: son la base de todos los totales y del margen.
    # Cantidad y Líneas toleran float32/int32 sin afectar los agregados.
    for m, dt in [("V", 'f8'), ("C", 'f8'), ("Q", 'f4'), ("D", 'i4')]:
        columnas.append(('main', m, dt, c[m].to_numpy().astype(dt)))

    for k in ['Empresa', 'Año', 'Dim', 'Valor']:
        cats, cod, dt = _codificar_dim(cmp_df[k])
        header["cmp"]["dims"][k] = cats
        columnas.append(('cmp', k, dt, cod))
    # V/C/Q: venta, costo, cantidad (mismo criterio que el cubo principal).
    # N: clientes distintos (nunique ClienteKey). M: documentos distintos (nunique Factura).
    for m, dt in [("V", 'f8'), ("C", 'f8'), ("Q", 'f4'), ("N", 'i4'), ("M", 'i4')]:
        columnas.append(('cmp', m, dt, cmp_df[m].to_numpy().astype(dt)))

    ORDEN = {'f8': 0, 'i4': 1, 'f4': 1, 'u2': 2, 'u1': 3}   # mayor alineación primero
    columnas.sort(key=lambda t: ORDEN[t[2]])
    cuerpo, off = [], 0
    for seccion, k, dt, arr in columnas:
        ancho = arr.dtype.itemsize
        pad = (-off) % ancho                        # cada vista debe quedar alineada
        if pad:
            cuerpo.append(b'\x00' * pad); off += pad
        destino = header["cols"] if seccion == 'main' else header["cmp"]["cols"]
        destino.append({"k": k, "t": dt, "off": off})
        cuerpo.append(arr.tobytes()); off += arr.nbytes

    # Los offsets son relativos al inicio del cuerpo; el navegador calcula la base
    # como 4 + largo del header + relleno de alineación. Así el header no depende de
    # su propio tamaño y no hay que recalcularlo.
    hb = json.dumps(header, separators=(',', ':')).encode()
    pad0 = (-(4 + len(hb))) % 8
    crudo_bin = b''.join([len(hb).to_bytes(4, 'little'), hb, b'\x00' * pad0] + cuerpo)
    crudo = gzip.compress(crudo_bin, 9)
    html = open(template, encoding='utf-8').read()
    if clave:
        # AES-256-GCM con clave derivada por PBKDF2-SHA256. El HTML puede quedar en un
        # sitio publico (GitHub Pages): sin la clave el payload es ilegible.
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
        it = 310000
        k = hashlib.pbkdf2_hmac('sha256', clave.encode(), salt, it, 32)
        crudo = AESGCM(k).encrypt(iv, crudo, None)
        b64 = base64.b64encode(crudo).decode()
        html = html.replace('<script id="payload" type="application/octet-stream">',
            f'<script id="payload" type="application/octet-stream" '
            f'data-salt="{base64.b64encode(salt).decode()}" '
            f'data-iv="{base64.b64encode(iv).decode()}" data-it="{it}">')
        print(f"payload cifrado (AES-256-GCM, PBKDF2 {it:,} iteraciones)")
    else:
        b64 = base64.b64encode(crudo).decode()
    html = html.replace('__DATA__', b64)
    open(salida,'w',encoding='utf-8').write(html)
    print(f"filas cubo={len(c):,}  filas comparativo={len(cmp_df):,}  html={os.path.getsize(salida)/1e6:.2f} MB")

if __name__ == "__main__":
    construir(sys.argv[1] if len(sys.argv)>1 else 'out2/ventas_bdd.parquet',
              sys.argv[2] if len(sys.argv)>2 else 'dash_template.html',
              sys.argv[3] if len(sys.argv)>3 else '/mnt/user-data/outputs/Estadisticas_Venta_DIB.html',
              sys.argv[4] if len(sys.argv)>4 else os.environ.get('DASH_CLAVE'))
