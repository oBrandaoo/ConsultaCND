import asyncio
import json
import threading
import time
import unittest
import urllib.request
import urllib.error
from app import Server
from consultations import Consultations, ValidationError, assess_page, normalize_cnpj, portal_url

CNPJ='18192898000102'
CITY='Santa Rita do Sapucaí'
URL='https://servicos.receitafederal.gov.br/servico/certidoes/'
DATA={'cnpj':CNPJ,'city':CITY,'services':['federal']}

class ClassificationTest(unittest.TestCase):
    def test_numeric_and_alphanumeric_cnpj(self):
        self.assertEqual(normalize_cnpj('18.192.898/0001-02'),CNPJ)
        self.assertEqual(normalize_cnpj('12.ABC.345/01DE-35'),'12ABC34501DE35')
        for value in ['18192898000103','00000000000000',[],None,'<script>']:
            with self.assertRaises(ValidationError): normalize_cnpj(value)

    def test_federal_live_error_is_not_debt(self):
        text='Mensagem de Aviso\nNão foi possível concluir a ação para o contribuinte informado. Por favor, tente novamente dentro de alguns minutos. 023'
        result=assess_page('federal',CNPJ,text,URL,True)
        self.assertEqual(result['status'],'indisponivel')
        self.assertIn('023',result['evidence'])
        self.assertTrue(result['submitted'])

    def test_fgts_block_is_not_irregularity(self):
        result=assess_page('fgts',CNPJ,'Estamos detectando comportamento malicioso no acesso.','https://validate.perfdrive.com/')
        self.assertEqual(result['status'],'bloqueado')
        self.assertFalse(result['submitted'])

    def test_form_and_other_company_never_confirm_certificate(self):
        row='Certidão Negativa 01/09/2026 01/03/2027'
        for text,submitted in [('Emitir certidão negativa',False),('CNPJ 00.000.000/0001-91',True),('Consultar certidão',True)]:
            result=assess_page('federal',CNPJ,text,URL,submitted,rows=[row])
            self.assertNotEqual(result['status'],'encontrada')

    def test_certificate_requires_identity_and_explicit_result_row(self):
        result=assess_page('federal',CNPJ,'CNPJ: 18.192.898/0001-02',URL,True,rows=['Positiva com efeitos de negativa 01/09/2026 01/03/2027'])
        self.assertEqual(result['status'],'encontrada')
        self.assertIn('Positiva',result['evidence'])
        self.assertIn('vencidos',result['message'])

    def test_no_certificate_is_not_positive_or_negative(self):
        result=assess_page('federal',CNPJ,'Não foram encontradas certidões.',URL,True)
        self.assertEqual(result['status'],'sem_certidao')
        self.assertIn('não comprova',result['message'])

    def test_visible_login_and_captcha_remain_pending_fiscal_result(self):
        self.assertEqual(assess_page('federal',CNPJ,'',URL,challenge=True)['status'],'captcha')
        self.assertEqual(assess_page('estadual',CNPJ,'','https://sso.acesso.gov.br/')['status'],'login')
        self.assertEqual(assess_page('estadual',CNPJ,'CDT','https://cdt.fazenda.mg.gov.br/')['status'],'login')

    def test_header_login_alone_does_not_block_public_query(self):
        result=assess_page('federal',CNPJ,'Entrar com gov.br\nNão foram encontradas certidões.',URL,True)
        self.assertEqual(result['status'],'sem_certidao')

    def test_municipal_routing(self):
        self.assertIn('santaritasapucai',portal_url('municipal',CITY))
        self.assertIn('certidao-negativa-de-debitos',portal_url('municipal','Pouso Alegre'))
        self.assertIn('itajuba',portal_url('municipal','Itajubá'))
        self.assertIn('cdt.fazenda',portal_url('estadual',CITY))

class EngineTest(unittest.TestCase):
    def setUp(self):
        self.finished=threading.Event()
        async def runner(rid):
            await asyncio.sleep(.04)
            self.engine.update(rid,'federal',status='sem_certidao',message='Retorno de teste.',submitted=True)
            self.finished.set()
        self.engine=Consultations(runner)

    def wait_run(self,rid):
        limit=time.monotonic()+3
        while self.engine.get(rid)['running'] and time.monotonic()<limit: time.sleep(.01)
        self.assertFalse(self.engine.get(rid)['running'])

    def test_async_result_and_isolated_snapshot(self):
        run=self.engine.start(DATA)
        self.wait_run(run['id'])
        result=self.engine.get(run['id'])
        self.assertEqual(result['results']['federal']['status'],'sem_certidao')
        result['results']['federal']['status']='encontrada'
        self.assertEqual(self.engine.get(run['id'])['results']['federal']['status'],'sem_certidao')

    def test_invalid_request_never_starts_browser(self):
        for change in [{'services':[]},{'services':['unknown']},{'services':['federal','federal']},{'services':[{}]},{'city':[]},{'city':'Outro município'},{'cnpj':'000'},{'assisted':'true'},{'assisted':True,'services':['federal','fgts']}]:
            with self.assertRaises(ValidationError): self.engine.start({**DATA,**change})
        self.assertEqual(self.engine.runs,{})

    def test_one_active_query_and_expiry(self):
        run=self.engine.start(DATA)
        with self.assertRaises(ValidationError): self.engine.start(DATA)
        self.wait_run(run['id'])
        self.engine.runs[run['id']]['created']-=1900
        with self.assertRaises(ValidationError): self.engine.get(run['id'])

    def test_browser_failure_is_not_completed_query(self):
        async def broken(rid): raise RuntimeError('Browser unavailable')
        self.engine=Consultations(broken)
        run=self.engine.start(DATA)
        self.wait_run(run['id'])
        result=self.engine.get(run['id'])['results']['federal']
        self.assertEqual(result['status'],'indisponivel')
        self.assertFalse(result['submitted'])

class HttpTest(unittest.TestCase):
    def setUp(self):
        async def runner(rid):
            self.engine.update(rid,'federal',status='indisponivel',message='Resposta simulada para teste.',submitted=True)
        self.engine=Consultations(runner)
        self.server=Server(('127.0.0.1',0),self.engine)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_address[1]}'
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
    def request(self,path,body=None,headers=None):
        req=urllib.request.Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json','X-CSRF-Token':self.server.token,**(headers or {})})
        try: response=urllib.request.urlopen(req)
        except urllib.error.HTTPError as e: response=e
        with response: return response.status,response.read()
    def test_query_and_no_management_routes(self):
        status,body=self.request('/api/consultations',DATA)
        self.assertEqual(status,202)
        rid=json.loads(body)['id']
        self.assertEqual(self.request('/api/consultations/'+rid)[0],200)
        for path in ['/api/companies','/api/documents','/api/settings','/api/state','/data/certifica.sqlite3','/../app.py']:
            self.assertEqual(self.request(path)[0],404)
    def test_host_csrf_and_origin(self):
        self.assertEqual(self.request('/api/config',headers={'Host':'evil.example'})[0],403)
        self.assertEqual(self.request('/api/consultations',DATA,{'X-CSRF-Token':'wrong'})[0],403)
        self.assertEqual(self.request('/api/consultations',DATA,{'Origin':'https://evil.example'})[0],403)
    def test_assets_and_unknown_query(self):
        for path in ['/','/app.js','/styles.css','/api/config']: self.assertEqual(self.request(path)[0],200)
        self.assertEqual(self.request('/api/consultations/does-not-exist')[0],404)

    def test_pdf_download_matches_query_and_expires_with_it(self):
        from test_santa_rita import pdf_bytes
        content=pdf_bytes()
        async def runner(rid):
            self.engine.update(rid,'municipal',status='encontrada',_pdf=content)
        self.engine.runner=runner
        status,body=self.request('/api/consultations',{**DATA,'services':['municipal']})
        self.assertEqual(status,202)
        rid=json.loads(body)['id']
        deadline=time.monotonic()+3
        while self.engine.get(rid)['running'] and time.monotonic()<deadline:time.sleep(.01)
        result=json.loads(self.request('/api/consultations/'+rid)[1])['results']['municipal']
        self.assertNotIn('_pdf',result)
        with urllib.request.urlopen(self.base+result['document_url']) as response:
            self.assertEqual(response.headers['Content-Type'],'application/pdf')
            self.assertIn('attachment;',response.headers['Content-Disposition'])
            self.assertEqual(response.headers['Cache-Control'],'no-store')
            self.assertEqual(response.read(),content)
        self.assertEqual(self.request(f'/api/consultations/{rid}/documents/federal')[0],404)
        self.assertEqual(self.request('/api/consultations/unknown/documents/municipal')[0],404)
        self.engine.runs[rid]['created']-=1900
        self.assertEqual(self.request(result['document_url'])[0],404)

if __name__=='__main__': unittest.main()

