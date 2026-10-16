"""Envia por correo los informes diarios generados por la plataforma.
Uso: python enviar_informes.py AAAA-MM-DD --destinatarios archivo.txt
Modo (variable de entorno ENVIAR_CORREO): FALSE (default, no envia) | TEST (solo CORREO_TEST) | TRUE (todos).
Envia con el servidor de correo saliente de Odoo (mail.mail), usando los mismos secrets ODOO_*.
Extra: CORREO_REMITENTE (opcional; si falta usa el remitente por defecto de Odoo), CORREO_TEST (solo modo TEST).
"""
import argparse, base64, glob, os, sys, xmlrpc.client
from datetime import datetime


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

    remit = os.environ.get('CORREO_REMITENTE', '')
    if modo == 'TEST':
        dest = [os.environ['CORREO_TEST']]
    else:
        dest = [l.strip() for l in open(a.destinatarios, encoding='utf-8')
                if l.strip() and not l.startswith('#')]
    fstr = datetime.strptime(a.fecha, '%Y-%m-%d').strftime('%d-%m-%Y')

    asunto = ('[TEST] ' if modo == 'TEST' else '') + 'Informe Control Ventas ' + fstr
    cuerpo = ('<p>Buenos dias:</p><p>Adjunto informes Control Ventas del dia %s.</p>'
              '<p>Atte,<br>Control de Gestion</p><hr><small>Correo enviado automaticamente. '
              'Por favor no responder a este mensaje.</small>' % fstr)

    url, db = os.environ['ODOO_URL'].rstrip('/'), os.environ['ODOO_DB']
    user, key = os.environ['ODOO_USER'], os.environ['ODOO_KEY']
    uid = xmlrpc.client.ServerProxy(url + '/xmlrpc/2/common').authenticate(db, user, key, {})
    ex = xmlrpc.client.ServerProxy(url + '/xmlrpc/2/object', allow_none=True).execute_kw

    att = []
    for f in adj:
        with open(f, 'rb') as fh:
            att.append(ex(db, uid, key, 'ir.attachment', 'create', [{
                'name': os.path.basename(f), 'datas': base64.b64encode(fh.read()).decode(),
                'res_model': 'mail.mail', 'res_id': 0,
                'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}]))
    vals = {'subject': asunto, 'body_html': cuerpo, 'email_to': ', '.join(dest),
            'attachment_ids': [(6, 0, att)], 'auto_delete': False}
    if remit:
        vals['email_from'] = remit
    mid = ex(db, uid, key, 'mail.mail', 'create', [vals])
    try:
        ex(db, uid, key, 'mail.mail', 'send', [[mid]])
    except Exception as e:     # si el envio inmediato falla, queda en la cola de Odoo
        print('Aviso: envio inmediato fallo (%s); queda en cola de Odoo' % str(e)[:200])
    est = ex(db, uid, key, 'mail.mail', 'read', [[mid]], {'fields': ['state', 'failure_reason']})[0]
    print('Correo %s -> %d destinatario(s), estado Odoo: %s %s' % (modo, len(dest), est['state'], est['failure_reason'] or ''))
    if est['state'] == 'exception':
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
