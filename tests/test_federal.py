"""Contrato e navegação com servidor simulado, sem consultar contribuintes reais."""
import asyncio
import json
import unittest
from types import SimpleNamespace

import consultations  # Disponibiliza a instalação local de Playwright.
from federal import API, HOST, FederalTrace, consult_federal, parse_response

CNPJ='24492886000104'
CERT={'numeroControle':'TESTE.1234','tipoCertidao':'Negativa','dataEmissao':'2026-09-01T10:00:00',
      'dataValidade':'2027-03-01','situacao':'Válida'}


class ResponseTest(unittest.TestCase):
    def test_actual_captcha_error_and_missing_token(self):
        for value in ('CaptchaFalhaValidacao','CaptchaTokenNaoInformado'):
            result=parse_response(400,{'codigo':'023','statusValidacao':value},'validacao')
            self.assertEqual(result['status'],'captcha')
            self.assertIn(value,result['evidence'])
        # O código 023 sozinho não é suficiente para diagnosticar CAPTCHA.
        self.assertEqual(parse_response(400,{'codigo':'023'},'validacao')['status'],'indisponivel')

    def test_validation_or_unrecognized_response_never_confirms_certificate(self):
        self.assertIsNone(parse_response(200,{'status':'Sucesso','certidoes':[CERT]},'validacao'))
        for body in (None, {}, {'statusConsulta':'Sucesso','certidoes':[]},
                     {'statusConsulta':'Sucesso','certidoes':[{'tipoCertidao':'Negativa'}]}):
            self.assertNotEqual(parse_response(200,body,'pesquisa')['status'],'encontrada')

    def test_records_preserve_expiry_and_annulment_without_claiming_regular(self):
        result=parse_response(200,{'statusConsulta':'Sucesso','certidoes':[{**CERT,'situacao':'Anulada'}]},'pesquisa')
        self.assertEqual(result['status'],'encontrada')
        self.assertIn('Anulada',result['evidence'])
        self.assertIn('2027-03-01',result['evidence'])
        self.assertEqual(parse_response(200,{'statusConsulta':'CertidaoNaoEncontrada'},'pesquisa')['status'],'sem_certidao')

    def test_identity_stage_and_origin_binding(self):
        trace=FederalTrace(CNPJ)
        def req(ni=CNPJ,host=HOST,path=API):
            return SimpleNamespace(url=f'https://{host}{path}',method='POST',post_data_json={'ni':ni,'tipoContribuinte':'PJ'})
        trace.request(req(host='example.org'))
        self.assertFalse(trace.submitted)
        trace.request(req(path=API+'/validar-contribuinte'))
        self.assertTrue(trace.submitted)
        self.assertFalse(trace.searched)
        trace.request(req(ni='18192898000102'))
        self.assertEqual(trace.result['status'],'manual')


PAGE='''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"></head><body>
<input name="niContribuinte"><button id="query">Consultar Certidão</button>
<script>
document.querySelector('#query').onclick=async()=>{
  const ni=document.querySelector('input').value.replace(/[^0-9]/g,'');
  const response=await fetch('/servico/certidoes/api/consulta/validar-contribuinte',{
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ni,tipoContribuinte:'PJ'})});
  if(!response.ok){document.body.insertAdjacentHTML('beforeend','<p>Não foi possível concluir a ação. 023</p>');return;}
  location.hash='/home/cnpj/consultar';
  document.body.innerHTML=`<div id="metadados">CNPJ: ${ni}</div>
    <br-date-picker formcontrolname="dataInicial"><input value="10/09/2025"></br-date-picker>
    <br-date-picker formcontrolname="dataFinal"><input value="10/09/2026"></br-date-picker>
    <button id="search">Consultar Certidão</button>`;
  document.querySelector('#search').onclick=async()=>{
    await fetch('/servico/certidoes/api/consulta',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({ni,tipoContribuinte:'PJ',tipoPesquisa:'DATA_EMISSAO',periodoInicio:'2025-09-10',periodoFim:'2026-09-10'})});
    location.hash='/home/cnpj/consultar/resultado';
  };
};
</script></body></html>'''


class NavigationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        self.p=await async_playwright().start()
        self.browser=await self.p.chromium.launch(channel='msedge',headless=True)
        self.context=await self.browser.new_context()
        self.requests=[]
        self.captcha=False
        async def route(route):
            request=route.request
            if request.method=='POST':
                self.requests.append(request.url)
                if request.url.endswith('/validar-contribuinte'):
                    status,body=(400,{'codigo':'023','statusValidacao':'CaptchaFalhaValidacao'}) if self.captcha else (200,{'status':'Sucesso','idConsulta':'TESTE'})
                else: status,body=200,{'statusConsulta':'Sucesso','certidoes':[CERT]}
                await route.fulfill(status=status,content_type='application/json',body=json.dumps(body))
            else: await route.fulfill(content_type='text/html',body=PAGE)
        await self.context.route('**/*',route)
        # O runner recebe normalmente Browser; este adaptador isola a rede dos testes.
        async def new_page(**kwargs): return await self.context.new_page()
        self.adapter=SimpleNamespace(new_page=new_page)

    async def asyncTearDown(self):
        await self.browser.close()
        await self.p.stop()

    async def test_validation_then_period_then_structured_result(self):
        result=await consult_federal(self.adapter,CNPJ)
        self.assertEqual(result['status'],'encontrada')
        self.assertTrue(result['searched'])
        self.assertEqual(len(self.requests),2)
        self.assertTrue(self.requests[0].endswith('/validar-contribuinte'))
        self.assertTrue(self.requests[1].endswith('/consulta'))
        self.assertIn('2025-09-10 a 2026-09-10',result['evidence'])

    async def test_captcha_rejection_stops_without_search_or_retry(self):
        self.captcha=True
        result=await consult_federal(self.adapter,CNPJ)
        self.assertEqual(result['status'],'captcha')
        self.assertFalse(result['searched'])
        self.assertEqual(len(self.requests),1)

    async def test_assisted_waits_for_user_and_resumes_reading(self):
        ready=asyncio.Event()
        def update(**data):
            if data['status']=='aguardando_usuario':ready.set()
        task=asyncio.create_task(consult_federal(self.adapter,CNPJ,assisted=True,update=update))
        await asyncio.wait_for(ready.wait(),15)
        self.assertEqual(self.requests,[])
        await self.context.pages[0].get_by_role('button',name='Consultar Certidão').click()
        result=await asyncio.wait_for(task,15)
        self.assertEqual(result['status'],'encontrada')

    async def test_closing_assisted_window_finishes_without_certificate(self):
        ready=asyncio.Event()
        task=asyncio.create_task(consult_federal(self.adapter,CNPJ,assisted=True,update=lambda **kw:ready.set()))
        await asyncio.wait_for(ready.wait(),15)
        await self.context.pages[0].close()
        result=await asyncio.wait_for(task,10)
        self.assertEqual(result['status'],'manual')
        self.assertFalse(result['submitted'])


if __name__=='__main__':unittest.main()
