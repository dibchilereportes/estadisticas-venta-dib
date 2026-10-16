"""Envia por correo los informes diarios generados por la plataforma.
Uso: python enviar_informes.py AAAA-MM-DD --destinatarios archivo.txt
Modo (variable de entorno ENVIAR_CORREO): FALSE (default, no envia) | TEST (solo CORREO_TEST) | TRUE (todos).
SMTP por variables de entorno: SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASS, CORREO_REMITENTE, CORREO_TEST.
"""
import argparse, glob, os, smtplib, sys
from datetime import datetime
from email.message import EmailMessage


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('fecha')
    ap.add_argument('--destinatarios', default='datos-repo/datos/destinatarios_informe.txt')
    ap.add_argument('--carpeta', default='informes')
    a = ap.parse_args()

    modo = (os.environ.get('ENVIAR_CORREO') or 'FALSE').strip().upper()
    if modo not in ('TEST', 'TRUE'):
        print('Envio de correo desactivado (ENVIAR_CORREO=%s)' % modo); return 0

    adj = sorted(glob.glob(os.path.join(a.carpeta, '*_%s.xlsx' % a.fecha)))
    if not adj:
        print('Sin informes para %s; no se envia' % a.fecha); return 1

    remit = os.environ['CORREO_REMITENTE']
    if modo == 'TEST':
        dest = [os.environ['CORREO_TEST']]
    else:
        dest = [l.strip() for l in open(a.destinatarios, encoding='utf-8')
                if l.strip() and not l.startswith('#')]
    fstr = datetime.strptime(a.fecha, '%Y-%m-%d').strftime('%d-%m-%Y')

    m = EmailMessage()
    m['From'] = remit
    m['To'] = ', '.join(dest)
    m['Subject'] = ('[TEST] ' if modo == 'TEST' else '') + 'Informe Control Ventas ' + fstr
    m.set_content('Buenos dias:\n\nAdjunto informes Control Ventas del dia %s.\n\n'
                  'Atte,\nControl de Gestion\n\n---\nCorreo enviado automaticamente. '
                  'Por favor no responder a este mensaje.' % fstr)
    for f in adj:
        with open(f, 'rb') as fh:
            m.add_attachment(fh.read(), maintype='application',
                             subtype='vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                             filename=os.path.basename(f))
    with smtplib.SMTP(os.environ['SMTP_HOST'], int(os.environ.get('SMTP_PORT', '587'))) as s:
        s.starttls()
        s.login(os.environ['SMTP_USER'], os.environ['SMTP_PASS'])
        s.send_message(m)
    print('Correo %s enviado a %d destinatario(s): %s' % (modo, len(dest), m['Subject']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
