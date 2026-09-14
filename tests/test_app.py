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
URL='https://servicos.receitafederal.gov.br/servico/certidoes/'
DATA={'cnpj':CNPJ,'services':['federal']}

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

    def test_access_block_is_not_irregularity(self):
        result=assess_page('federal',CNPJ,'Estamos detectando comportamento malicioso no acesso.','https://validate.perfdrive.com/')
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

    def test_visible_captcha_remains_pending_fiscal_result(self):
        self.assertEqual(assess_page('federal',CNPJ,'',URL,challenge=True)['status'],'captcha')

    def test_header_login_alone_does_not_block_public_query(self):
        result=assess_page('federal',CNPJ,'Entrar com gov.br\nNão foram encontradas certidões.',URL,True)
        self.assertEqual(result['status'],'sem_certidao')

    def test_services_are_available_without_city_selector(self):
        config=Consultations(lambda _:None).config()
        self.assertEqual(list(config['services']),['federal','fgts','trabalhista','falencia','estadual_mg','estadual_sp','municipal'])
        self.assertNotIn('cities',config)
        self.assertIn('receitafederal',portal_url('federal',None))
        self.assertIn('consulta-crf.caixa.gov.br',portal_url('fgts',None))
        self.assertIn('cndt-certidao.tst.jus.br',portal_url('trabalhista',None))
        self.assertIn('rupe.tjmg.jus.br',portal_url('falencia',None))
        self.assertIn('fazenda.mg.gov.br',portal_url('estadual_mg',None))
        self.assertIn('fazenda.sp.gov.br',portal_url('estadual_sp',None))
        self.assertIn('santaritasapucai',portal_url('municipal',None))

class EngineTest(unittest.TestCase):
    def setUp(self):
        self.finished=threading.Event()
        self.processed=[]
        async def runner(rid):
            self.processed.append(rid)
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
        for change in [{'services':[]},{'services':['unknown']},{'services':['federal','federal']},{'services':[{}]},{'city':'Pouso Alegre'},{'cnpj':'000'},{'assisted':True},{'services':['federal','fgts','municipal','unknown']}]:
            with self.assertRaises(ValidationError): self.engine.start({**DATA,**change})
        self.assertEqual(self.engine.runs,{})

    def test_queries_are_processed_in_queue_order_and_expire(self):
        first=self.engine.start(DATA)
        second=self.engine.start(DATA)
        self.wait_run(first['id'])
        self.wait_run(second['id'])
        self.assertEqual(self.processed,[first['id'],second['id']])
        self.assertEqual(self.engine.get(second['id'])['phase'],'finished')
        self.engine.runs[first['id']]['created']-=1900
        with self.assertRaises(ValidationError): self.engine.get(first['id'])

    def test_queue_capacity_is_bounded(self):
        release=threading.Event()
        async def blocked(rid):
            await asyncio.to_thread(release.wait)
            self.engine.update(rid,'federal',status='sem_certidao',message='Concluída.')
        self.engine=Consultations(blocked,max_queue=1)
        first=self.engine.start(DATA)
        deadline=time.monotonic()+2
        while self.engine.get(first['id'])['phase']=='queued' and time.monotonic()<deadline:time.sleep(.01)
        second=self.engine.start(DATA)
        with self.assertRaises(ValidationError):self.engine.start(DATA)
        release.set()
        self.wait_run(first['id']);self.wait_run(second['id'])

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

    def test_configured_https_domain_is_accepted_behind_proxy(self):
        self.server.allowed_hosts=frozenset((*self.server.allowed_hosts,'certidoes.example'))
        headers={'Host':'certidoes.example','Origin':'https://certidoes.example'}
        self.assertEqual(self.request('/api/config',headers=headers)[0],200)
        self.assertEqual(self.request('/api/consultations',DATA,headers)[0],202)
    def test_assets_and_unknown_query(self):
        for path in ['/','/app.js','/styles.css','/api/config','/healthz']: self.assertEqual(self.request(path)[0],200)
        self.assertEqual(self.request('/api/consultations/does-not-exist')[0],404)

    def test_optional_basic_auth_protects_app_but_not_health(self):
        authorization='Basic Y2xpZW50ZTpzZW5oYS1kZS10ZXN0ZQ=='
        self.server.auth_header=authorization
        self.assertEqual(self.request('/healthz')[0],200)
        self.assertEqual(self.request('/api/config')[0],401)
        headers={'Authorization':authorization}
        self.assertEqual(self.request('/api/config',headers=headers)[0],200)
        self.assertEqual(self.request('/api/consultations',DATA,headers)[0],202)

    def test_only_configured_certificate_requests_are_accepted(self):
        status,body=self.request('/api/consultations',{'cnpj':CNPJ,'services':['estadual']})
        self.assertEqual(status,400)
        self.assertIn('Santa Rita',json.loads(body)['error'])
        config=json.loads(self.request('/api/config')[1])
        self.assertEqual(list(config['services']),['federal','fgts','trabalhista','falencia','estadual_mg','estadual_sp','municipal'])
        self.assertNotIn('cities',config)

    def test_santa_rita_pdf_download_matches_query(self):
        from tests.test_santa_rita import pdf_bytes
        content=pdf_bytes()
        async def runner(rid):
            self.engine.update(rid,'municipal',status='encontrada',message='Certidão municipal de teste.',_pdf=content)
        self.engine.runner=runner
        status,body=self.request('/api/consultations',{'cnpj':CNPJ,'services':['municipal']})
        self.assertEqual(status,202)
        rid=json.loads(body)['id']
        deadline=time.monotonic()+3
        while self.engine.get(rid)['running'] and time.monotonic()<deadline:time.sleep(.01)
        result=json.loads(self.request('/api/consultations/'+rid)[1])['results']['municipal']
        with urllib.request.urlopen(self.base+result['document_url']) as response:
            self.assertEqual(response.headers['Content-Type'],'application/pdf')
            self.assertEqual(response.read(),content)

    def test_federal_pdf_download_matches_query(self):
        content=b'%PDF-1.7\nFederal controlled test\n%%EOF'
        async def runner(rid):
            self.engine.update(rid,'federal',status='encontrada',message='Certidão federal de teste.',_pdf=content)
        self.engine.runner=runner
        status,body=self.request('/api/consultations',DATA)
        self.assertEqual(status,202)
        rid=json.loads(body)['id']
        deadline=time.monotonic()+3
        while self.engine.get(rid)['running'] and time.monotonic()<deadline:time.sleep(.01)
        result=json.loads(self.request('/api/consultations/'+rid)[1])['results']['federal']
        self.assertIn('/documents/federal',result['document_url'])
        with urllib.request.urlopen(self.base+result['document_url']) as response:
            self.assertEqual(response.headers['Content-Type'],'application/pdf')
            self.assertIn('cnd-federal-',response.headers['Content-Disposition'])
            self.assertEqual(response.read(),content)

    def test_fgts_pdf_download_matches_query(self):
        content=b'%PDF-1.7\nFGTS controlled test\n%%EOF'
        async def runner(rid):
            self.engine.update(rid,'fgts',status='encontrada',message='CRF de teste.',_pdf=content)
        self.engine.runner=runner
        status,body=self.request('/api/consultations',{'cnpj':CNPJ,'services':['fgts']})
        self.assertEqual(status,202)
        rid=json.loads(body)['id']
        deadline=time.monotonic()+3
        while self.engine.get(rid)['running'] and time.monotonic()<deadline:time.sleep(.01)
        result=json.loads(self.request('/api/consultations/'+rid)[1])['results']['fgts']
        self.assertIn('/documents/fgts',result['document_url'])
        with urllib.request.urlopen(self.base+result['document_url']) as response:
            self.assertEqual(response.headers['Content-Type'],'application/pdf')
            self.assertIn('crf-fgts-',response.headers['Content-Disposition'])
            self.assertEqual(response.read(),content)

    def test_trabalhista_pdf_download_matches_query(self):
        content=b'%PDF-1.7\nTrabalhista controlled test\n%%EOF'
        async def runner(rid):
            self.engine.update(rid,'trabalhista',status='encontrada',message='CNDT de teste.',_pdf=content)
        self.engine.runner=runner
        status,body=self.request('/api/consultations',{'cnpj':CNPJ,'services':['trabalhista']})
        self.assertEqual(status,202)
        rid=json.loads(body)['id']
        deadline=time.monotonic()+3
        while self.engine.get(rid)['running'] and time.monotonic()<deadline:time.sleep(.01)
        result=json.loads(self.request('/api/consultations/'+rid)[1])['results']['trabalhista']
        self.assertIn('/documents/trabalhista',result['document_url'])
        with urllib.request.urlopen(self.base+result['document_url']) as response:
            self.assertEqual(response.headers['Content-Type'],'application/pdf')
            self.assertIn('cndt-trabalhista-',response.headers['Content-Disposition'])
            self.assertEqual(response.read(),content)

    def test_falencia_pdf_download_matches_query(self):
        content=b'%PDF-1.7\nFalencia controlled test\n%%EOF'
        async def runner(rid):
            self.engine.update(rid,'falencia',status='encontrada',message='Falencia e concordata de teste.',_pdf=content)
        self.engine.runner=runner
        status,body=self.request('/api/consultations',{'cnpj':CNPJ,'services':['falencia'],'falencia':{
            'comarca':'Belo Horizonte','nome_empresa':'Contribuinte de Teste',
            'solicitante_nome':'Solicitante','solicitante_cpf':'000.000.000-00',
            'solicitante_email':'teste@example.com','codigo_verificacao':'1234'}})
        self.assertEqual(status,202)
        rid=json.loads(body)['id']
        deadline=time.monotonic()+3
        while self.engine.get(rid)['running'] and time.monotonic()<deadline:time.sleep(.01)
        payload=json.loads(self.request('/api/consultations/'+rid)[1])
        self.assertNotIn('falencia',payload)
        self.assertNotIn('_inputs',payload)
        result=payload['results']['falencia']
        self.assertIn('/documents/falencia',result['document_url'])
        with urllib.request.urlopen(self.base+result['document_url']) as response:
            self.assertEqual(response.headers['Content-Type'],'application/pdf')
            self.assertIn('cnd-falencia-concordata-',response.headers['Content-Disposition'])
            self.assertEqual(response.read(),content)

    def test_estadual_mg_pdf_download_matches_query(self):
        content=b'%PDF-1.7\nEstadual MG controlled test\n%%EOF'
        async def runner(rid):
            self.engine.update(rid,'estadual_mg',status='encontrada',message='CDT estadual MG de teste.',_pdf=content)
        self.engine.runner=runner
        status,body=self.request('/api/consultations',{'cnpj':CNPJ,'services':['estadual_mg']})
        self.assertEqual(status,202)
        rid=json.loads(body)['id']
        deadline=time.monotonic()+3
        while self.engine.get(rid)['running'] and time.monotonic()<deadline:time.sleep(.01)
        result=json.loads(self.request('/api/consultations/'+rid)[1])['results']['estadual_mg']
        self.assertIn('/documents/estadual_mg',result['document_url'])
        with urllib.request.urlopen(self.base+result['document_url']) as response:
            self.assertEqual(response.headers['Content-Type'],'application/pdf')
            self.assertIn('cdt-estadual-mg-',response.headers['Content-Disposition'])
            self.assertEqual(response.read(),content)

    def test_estadual_sp_pdf_download_matches_query(self):
        content=b'%PDF-1.7\nEstadual SP controlled test\n%%EOF'
        async def runner(rid):
            self.engine.update(rid,'estadual_sp',status='encontrada',message='CND estadual SP de teste.',_pdf=content)
        self.engine.runner=runner
        status,body=self.request('/api/consultations',{'cnpj':CNPJ,'services':['estadual_sp']})
        self.assertEqual(status,202)
        rid=json.loads(body)['id']
        deadline=time.monotonic()+3
        while self.engine.get(rid)['running'] and time.monotonic()<deadline:time.sleep(.01)
        result=json.loads(self.request('/api/consultations/'+rid)[1])['results']['estadual_sp']
        self.assertIn('/documents/estadual_sp',result['document_url'])
        with urllib.request.urlopen(self.base+result['document_url']) as response:
            self.assertEqual(response.headers['Content-Type'],'application/pdf')
            self.assertIn('cnd-estadual-sp-',response.headers['Content-Disposition'])
            self.assertEqual(response.read(),content)

if __name__=='__main__': unittest.main()

