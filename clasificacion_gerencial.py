# -*- coding: utf-8 -*-
"""
Clasificacion gerencial de ventas (informe diario del CD, DIB y DECOEXPRESS).

La clave es (cliente, branch, canal de venta, cuenta analitica) -> fila gerencial,
segun la matriz clasificacion_gerencial.csv (mantenida por el usuario). Reglas validadas
al peso contra el informe de ventas del 30-09-2026:

  1. Canal INTEREMPRESA                      -> excluido (no es venta a terceros).
  2. Documentos 'Liquidacion...' y 'Operaciones Visual' -> excluidos (no son venta:
     comisiones de marketplace / ajustes internos).
  3. DECOEXPRESS: se clasifica solo por cuenta analitica (VENTAS X MAYOR DEXP = B2B,
     M PLACE DEXP = B2C).
  4. Marketplace: siempre B2C, aunque la cuenta analitica diga B2B.
  5. Cuentas de la matriz sin combinacion en la matriz -> 'SIN CLASIFICAR' (no entra al
     informe, pero queda visible para auditar).
  6. Cuentas de tiendas/webs (DIB ..., BAZHARS ...) no pertenecen al informe del CD:
     EntraInforme_CD='NO' y sin fila gerencial (se informan por local).
Columnas que agrega: ClasifGerencial, LineaComercial, BloqueInforme, EntraInforme_CD,
MotivoExclusion.
"""
import os
import re
import unicodedata
import numpy as np
import pandas as pd

RUTA_MATRIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'clasificacion_gerencial.csv')
DEXP = {'VENTAS X MAYOR DEXP': 'DECOEXPRESS B2B', 'M PLACE DEXP': 'DECOEXPRESS B2C'}
GRUPO_MKT = 'MARKET PLACE (HITES-LA POLAR-ML)'
SALIDA = ['ClasifGerencial', 'LineaComercial', 'BloqueInforme', 'EntraInforme_CD', 'MotivoExclusion']


def _n(s):
    if s is None or (not isinstance(s, str) and pd.isna(s)):
        return None
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode().upper()
    s = re.sub(r'\s+', ' ', s).strip()
    for a, b in (('ECCOMERCE', 'ECOMMERCE'), ('FLORING', 'FLOORING'),
                 ('WALLMART', 'WALMART'), ('EMPELADOS', 'EMPLEADOS')):
        s = s.replace(a, b)
    return s or None


def _cargar_matriz(ruta=None):
    m = pd.read_csv(ruta or RUTA_MATRIZ)
    for c in m.columns:
        m[c] = m[c].map(_n)
    m = m.drop_duplicates()
    k4, k3 = {}, {}
    for r in m.itertuples(index=False):
        cl, br, ca = (None if pd.isna(x) else x for x in (r.Cliente, r.Branch, r.Canal))
        k4[(cl or '~', br or '~', ca or '~', r.Cuenta)] = r.Gerencial
        if cl is None:                             # fila "cualquier cliente"
            k3[(br or '~', ca or '~', r.Cuenta)] = r.Gerencial
    return k4, k3, set(m.Cuenta.dropna())


def clasificar(df, ruta_matriz=None):
    """df requiere x_customer, x_branch, x_canal, x_cuenta_analytica, x_tipo_dte."""
    k4, k3, cuentas = _cargar_matriz(ruta_matriz)
    cli = df['x_customer'].map(_n)
    bra = df['x_branch'].map(_n)
    can = df['x_canal'].map(_n)
    cta = df['x_cuenta_analytica'].map(_n)
    dte = df['x_tipo_dte'].map(_n).fillna('')

    n = len(df)
    g = np.full(n, None, dtype=object)
    linea = np.full(n, None, dtype=object)
    bloque = np.full(n, None, dtype=object)
    entra = np.zeros(n, dtype=bool)
    motivo = np.full(n, None, dtype=object)

    for i, (c, b, v, a, t) in enumerate(zip(cli, bra, can, cta, dte)):
        if a in DEXP:
            g[i] = DEXP[a]; linea[i] = a; bloque[i] = DEXP[a]
        elif a in cuentas:
            linea[i] = a
            gg = k4.get((c or '~', b or '~', v or '~', a)) or k3.get((b or '~', v or '~', a))
            if gg is None:
                g[i] = 'SIN CLASIFICAR'; motivo[i] = 'Sin combinacion en la matriz'
            else:
                g[i] = gg
                if gg == GRUPO_MKT:                # marketplace siempre B2C
                    linea[i] = a.replace('B2B', 'B2C')
            if g[i] != 'SIN CLASIFICAR':
                bloque[i] = ('VENTA EMPRESA' if 'VTA EMPRESA' in linea[i]
                             else 'B2C' if linea[i].endswith('B2C') else 'B2B')
        else:
            motivo[i] = 'No pertenece al informe del CD (tienda/web)'
            continue
        # exclusiones de no-venta (aplican sobre cuentas del informe)
        if v == 'INTEREMPRESA':
            motivo[i] = 'Interempresa'
        elif t.startswith('LIQUIDACION') or t.startswith('OPERACIONES VISUAL'):
            motivo[i] = 'Documento no-venta (' + t.title() + ')'
        elif g[i] == 'SIN CLASIFICAR':
            pass
        else:
            entra[i] = True
    return pd.DataFrame({'ClasifGerencial': g, 'LineaComercial': linea, 'BloqueInforme': bloque,
                         'EntraInforme_CD': np.where(entra, 'SI', 'NO'), 'MotivoExclusion': motivo}, index=df.index)
