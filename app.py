"""Certifica: interface local dedicada a consultas pontuais de CNDs."""
import argparse
import json
import re
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from consultations import Consultations, ValidationError
ROOT=Path(__file__).resolve().parent

class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,consultations=None):
        self.consultations=consultations or Consultations()
        self.token=secrets.token_urlsafe(32)
        super().__init__(address,Handler)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass
    def send_data(self,status,body,kind='application/json; charset=utf-8',filename=None):
        if not isinstance(body,bytes):
            body=json.dumps(body,ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(body)))
        if filename:
            self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)
    def valid_host(self):
        return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_address[1]}',f'localhost:{self.server.server_address[1]}')
    def do_GET(self):
        if not self.valid_host():
            return self.send_data(403,{'error':'Use o endereço local do aplicativo.'})
        path=urlsplit(self.path).path
        if path=='/api/config':
            return self.send_data(200,{**self.server.consultations.config(),'token':self.server.token})
        document=re.fullmatch(r'/api/consultations/([A-Za-z0-9_-]+)/documents/(municipal)',path)
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
        if not self.valid_host() or self.headers.get('X-CSRF-Token')!=self.server.token:
            return self.send_data(403,{'error':'Recarregue a página antes de consultar.'})
        origin=self.headers.get('Origin')
        if origin and origin!=f'http://{self.headers.get("Host")}':
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
    parser=argparse.ArgumentParser(description='Consulta local de CNDs')
    parser.add_argument('--port',type=int,default=8000)
    args=parser.parse_args()
    server=Server(('127.0.0.1',args.port))
    print(f'Consulta de CNDs disponível em http://127.0.0.1:{args.port}',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
if __name__=='__main__':
    main()
