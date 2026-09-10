# Estadísticas de Venta — DIB / Decoexpress

Dashboard estático de estadísticas de venta. Todo el contenido vive en `index.html`:
no hay servidor, base de datos ni llamadas externas.

## Cómo está protegido

El sitio de GitHub Pages es **público** (el control de acceso de Pages solo existe en
GitHub Enterprise Cloud). Por eso los datos no viajan en claro:

- El cubo de datos va cifrado con **AES-256-GCM**.
- La clave se deriva de una contraseña con **PBKDF2-SHA256, 310.000 iteraciones**.
- El descifrado ocurre en el navegador de quien tiene la clave. Sin la clave, `index.html`
  es un archivo binario ilegible.

La clave se comparte por canal interno, nunca por este repositorio.
Para cerrar sesión en un equipo: abrir la URL con `?salir` al final.

## Qué NO se sube nunca

`.gitignore` bloquea `.parquet`, `.xlsx`, `.csv` y `.db`. Los datos fuente y la BDD
estandarizada se quedan en la carpeta de trabajo local.

## Actualizar el dashboard

Desde la carpeta de trabajo (donde están `build_dash.py` y `datos/ventas_bdd.parquet`):

```bash
python publicar.py "CLAVE"
```

Regenera `index.html`, hace commit y push. GitHub Pages publica en 1-2 minutos.

## Ciclo mensual completo

```bash
python etl_ventas.py "ESTADISTICAS DE VENTA A JULIO 2026.xlsx" datos "ruta/catalogo.db"
python publicar.py "CLAVE"
```
