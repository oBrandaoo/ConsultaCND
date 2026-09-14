"""Certifica: interface local dedicada a consultas pontuais de CNDs."""
import argparse
import base64
import json
import os
import re
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from consultations import Consultations, ValidationError
ROOT=Path(__file__).resolve().parent

class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,consultations=None,allowed_hosts=None,basic_auth=None):
        self.consultations=consultations or Consultations()
        self.token=secrets.token_urlsafe(32)
        configured=allowed_hosts if allowed_hosts is not None else os.environ.get('CERTIFICA_ALLOWED_HOSTS','')
        if isinstance(configured,str):
            configured=configured.split(',')
        hosts={host.strip().lower() for host in configured if host.strip()}
        if any('/' in host or ':' in host for host in hosts):
            raise ValueError('CERTIFICA_ALLOWED_HOSTS deve conter apenas nomes separados por vírgula, sem porta ou protocolo.')
        self.allowed_hosts=frozenset(hosts|{'localhost','127.0.0.1'})
        if basic_auth is None:
            user=os.environ.get('CERTIFICA_BASIC_USER','')
            password=os.environ.get('CERTIFICA_BASIC_PASSWORD','')
        else:
            user,password=basic_auth
        if bool(user)!=bool(password):
            raise ValueError('CERTIFICA_BASIC_USER e CERTIFICA_BASIC_PASSWORD devem ser definidos juntos.')
        credentials=base64.b64encode(f'{user}:{password}'.encode('utf-8')).decode('ascii') if user else None
        self.auth_header=f'Basic {credentials}' if credentials else None
        super().__init__(address,Handler)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass
    def send_data(self,status,body,kind='application/json; charset=utf-8',filename=None,headers=None):
        if not isinstance(body,bytes):
            body=json.dumps(body,ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(body)))
        if filename:
            self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
        for name,value in (headers or {}).items():
            self.send_header(name,value)
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)
    def valid_host(self):
        try:
            hostname=urlsplit('//'+self.headers.get('Host','')).hostname
        except ValueError:
            return False
        return bool(hostname and hostname.lower() in self.server.allowed_hosts)
    def valid_origin(self):
        origin=self.headers.get('Origin')
        if not origin:
            return True
        parsed=urlsplit(origin)
        return parsed.scheme in ('http','https') and parsed.netloc.lower()==self.headers.get('Host','').lower()
    def authenticated(self):
        expected=self.server.auth_header
        return expected is None or secrets.compare_digest(self.headers.get('Authorization',''),expected)
    def require_authentication(self):
        if self.authenticated():return True
        self.send_data(401,{'error':'Autenticação necessária.'},headers={
            'WWW-Authenticate':'Basic realm="Certifica", charset="UTF-8"'
        })
        return False
    def do_GET(self):
        if not self.valid_host():
            return self.send_data(403,{'error':'Host não permitido.'})
        path=urlsplit(self.path).path
        if path=='/healthz':
            return self.send_data(200,{'status':'ok'})
        if not self.require_authentication():return
        if path=='/api/config':
            return self.send_data(200,{**self.server.consultations.config(),'token':self.server.token})
        document=re.fullmatch(r'/api/consultations/([A-Za-z0-9_-]+)/documents/(federal|fgts|trabalhista|falencia|estadual_mg|estadual_sp|municipal)',path)
        if document:
            try:
                content,filename=self.server.consultations.get_document(document[1],document[2])
                return self.send_data(200,content,'application/pdf',filename)
            except ValidationError as error:
                return self.send_data(404,{'error':str(error)})
        match=re.fullmatch(r'/api/consultations/([A-Za-z0-9_-]+)',path)
        if match:
            try:
                return self.send_data(200,self.server.consultations.get(match[1]))
            except ValidationError as error:
                return self.send_data(404,{'error':str(error)})
        files={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/styles.css':('styles.css','text/css; charset=utf-8')}
        if path in files:
            name,kind=files[path]
            return self.send_data(200,(ROOT/'static'/name).read_bytes(),kind)
        self.send_data(404,{'error':'Página não encontrada.'})
    def do_POST(self):
        if not self.valid_host():
            return self.send_data(403,{'error':'Host não permitido.'})
        if not self.require_authentication():return
        if self.headers.get('X-CSRF-Token')!=self.server.token:
            return self.send_data(403,{'error':'Recarregue a página antes de consultar.'})
        if not self.valid_origin():
            return self.send_data(403,{'error':'Origem não permitida.'})
        if urlsplit(self.path).path!='/api/consultations':
            return self.send_data(404,{'error':'Operação não encontrada.'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=8192:
                return self.send_data(413,{'error':'Requisição vazia ou acima do limite.'})
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':
                return self.send_data(415,{'error':'Envie os dados em JSON.'})
            data=json.loads(self.rfile.read(size))
            if not isinstance(data,dict):
                raise ValidationError('Dados inválidos.')
            return self.send_data(202,self.server.consultations.start(data))
        except (ValidationError,ValueError,UnicodeDecodeError) as error:
            self.send_data(400,{'error':str(error)})
        except Exception:
            self.send_data(500,{'error':'Não foi possível iniciar a consulta.'})

def main():
    parser=argparse.ArgumentParser(description='Consulta web de CNDs')
    parser.add_argument('--host',default=os.environ.get('HOST','127.0.0.1'))
    parser.add_argument('--port',type=int,default=int(os.environ.get('PORT','8000')))
    args=parser.parse_args()
    server=Server((args.host,args.port))
    print(f'Consulta de CNDs disponível em http://{args.host}:{args.port}',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
if __name__=='__main__':
    main()
