"""Contrato federal e navegação controlada, sem consultar contribuintes reais."""
import base64
import io
import json
import unittest
from types import SimpleNamespace
from urllib.parse import urlsplit

import consultations
from federal import API,EMISSION,HOST,consult_federal,parse_federal_pdf,parse_response

CNPJ='24492886000104'
CONTROL='ABCD.1234.EFGH.5678'
CERT={'idCertidao':'ID-TESTE','hasSegundaVia':True,'numeroControle':CONTROL,'tipoCertidao':'Negativa',
      'dataEmissao':'2026-09-01T10:00:00','dataValidade':'2027-03-01','situacao':'Válida'}


def pdf_bytes(cnpj=CNPJ,control=CONTROL):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
    writer=PdfWriter();page=writer.add_blank_page(width=595,height=842)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    lines=['TESTE SEM VALOR','MINISTERIO DA FAZENDA','Secretaria da Receita Federal do Brasil',
           'Procuradoria-Geral da Fazenda Nacional','CERTIDAO NEGATIVA DE DEBITOS RELATIVOS AOS TRIBUTOS FEDERAIS',
           'Nome: EMPRESA FEDERAL DE TESTE',f'CNPJ: {cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}',
           'Emitida as 10:00:00 do dia 01/09/2026','Valida ate: 01/03/2027',f'Codigo de controle da certidao: {control}']
    commands=['BT /F1 9 Tf 20 810 Td']
    for index,line in enumerate(lines):commands.append(('0 -18 Td ' if index else '')+f'({line}) Tj')
    commands.append('ET');stream=DecodedStreamObject();stream.set_data(' '.join(commands).encode('ascii'))
    page[NameObject('/Contents')]=writer._add_object(stream);result=io.BytesIO();writer.write(result);return result.getvalue()


class ResponseTest(unittest.TestCase):
    def test_captcha_failure_is_not_a_fiscal_result(self):
        for value in ('CaptchaFalhaValidacao','CaptchaTokenNaoInformado'):
            result=parse_response(400,{'codigo':'023','statusValidacao':value},'validacao')
            self.assertEqual(result['status'],'captcha')
            self.assertIn(value,result['evidence'])

    def test_search_classification(self):
        self.assertIsNone(parse_response(200,{'status':'Sucesso'},'validacao'))
        self.assertEqual(parse_response(200,{'statusConsulta':'CertidaoNaoEncontrada'},'pesquisa')['status'],'sem_certidao')
        result=parse_response(200,{'statusConsulta':'Sucesso','certidoes':[CERT]},'pesquisa')
        self.assertEqual(result['status'],'encontrada')
        self.assertIn('2027-03-01',result['evidence'])

    def test_pdf_identity_type_control_and_dates(self):
        certificate=parse_federal_pdf(pdf_bytes(),CNPJ,CONTROL)
        self.assertEqual(certificate['type'],'Negativa')
        self.assertEqual(certificate['control'],CONTROL)
        self.assertEqual(certificate['valid_until'],'2027-03-01')
        for content,cnpj,control in [(b'html',CNPJ,CONTROL),(pdf_bytes(), '18192898000102',CONTROL),(pdf_bytes(),CNPJ,'OUTRO.CONTROLE')]:
            with self.assertRaises(Exception):parse_federal_pdf(content,cnpj,control)


PAGE='''<!doctype html><html lang="pt-BR"><body>
<input name="niContribuinte"><button id="consult">Consultar Certidão</button><button id="emit">Emitir Certidão</button>
<div id="modal" hidden><button id="modal-consult">Consultar Certidão</button><button>Emitir Nova Certidão</button></div>
<script>
const ni=()=>document.querySelector('input').value.replace(/[^0-9]/g,'');
document.querySelector('#emit').onclick=async()=>{
 const response=await fetch('/servico/certidoes/api/Emissao/verificar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ni:ni(),tipoContribuinteEnum:'CNPJ'})});
 if(!response.ok)return;const body=await response.json();
 if(body.status==='Emitida')document.querySelector('#modal').hidden=false;
 else{location.hash='/home/cnpj/resultado';await fetch('/servico/certidoes/api/Emissao',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ni:ni(),tipoContribuinteEnum:'CNPJ'})});}
};
document.querySelector('#modal-consult').onclick=async()=>{
 const value=ni();const response=await fetch('/servico/certidoes/api/consulta/validar-contribuinte',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ni:value,tipoContribuinte:'PJ'})});
 if(!response.ok)return;location.hash='/home/cnpj/consultar';
 document.body.innerHTML=`<div id="metadados">CNPJ: ${value}</div><br-date-picker formcontrolname="dataInicial"><input value="01/09/2025"></br-date-picker><br-date-picker formcontrolname="dataFinal"><input value="01/09/2026"></br-date-picker><button id="search">Consultar Certidão</button>`;
 document.querySelector('#search').onclick=async()=>{await fetch('/servico/certidoes/api/consulta',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ni:value,tipoContribuinte:'PJ',tipoPesquisa:'DATA_EMISSAO',periodoInicio:'2025-09-01',periodoFim:'2026-09-01'})});location.hash='/home/cnpj/consultar/resultado';document.body.innerHTML='<button title="Segunda via">Baixar</button>';document.querySelector('button').onclick=()=>fetch('/servico/certidoes/api/consulta/seg-via/ID-TESTE');};
};
</script></body></html>'''


class NavigationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        self.playwright=await async_playwright().start();self.browser=await self.playwright.chromium.launch(channel='msedge',headless=True)
        self.context=await self.browser.new_context();self.requests=[];self.mode='existing';self.captcha=False;self.pdf=pdf_bytes()
        async def route(route):
            request=route.request;path=urlsplit(request.url).path
            if path.startswith('/servico/certidoes/api/'):
                self.requests.append((request.method,path))
                if path==EMISSION+'/verificar':
                    status,body=((400,{'codigo':'023','statusValidacao':'CaptchaFalhaValidacao'}) if self.captcha else
                                 (200,{'status':'Emitida' if self.mode=='existing' else 'NaoEmitida'}))
                elif path==EMISSION:
                    status,body=200,{'statusEmissao':'Sucesso','pdf':base64.b64encode(self.pdf).decode(),'mensagem':{'texto':'Emitida'}}
                elif path==API+'/validar-contribuinte':status,body=200,{'status':'Sucesso'}
                elif path==API:status,body=200,{'statusConsulta':'Sucesso','certidoes':[CERT]}
                elif path.startswith(API+'/seg-via/'):
                    status,body=200,{'status':'Sucesso','pdf':base64.b64encode(self.pdf).decode(),'mensagem':{'texto':'Segunda via'}}
                else:status,body=404,{}
                await route.fulfill(status=status,content_type='application/json',body=json.dumps(body));return
            await route.fulfill(content_type='text/html; charset=utf-8',body=PAGE)
        await self.context.route('**/*',route)
        async def new_page(**kwargs):return await self.context.new_page()
        self.adapter=SimpleNamespace(new_page=new_page)

    async def asyncTearDown(self):
        await self.browser.close();await self.playwright.stop()

    async def test_existing_certificate_downloads_second_copy(self):
        result=await consult_federal(self.adapter,CNPJ)
        self.assertEqual(result['status'],'encontrada',result)
        self.assertEqual(result['_pdf'],self.pdf)
        self.assertEqual(result['certificate']['control'],CONTROL)
        self.assertEqual([path for _,path in self.requests],[EMISSION+'/verificar',API+'/validar-contribuinte',API,API+'/seg-via/ID-TESTE'])

    async def test_new_certificate_is_emitted_and_downloaded(self):
        self.mode='new'
        result=await consult_federal(self.adapter,CNPJ)
        self.assertEqual(result['status'],'encontrada',result)
        self.assertEqual(result['stage'],'emissao')
        self.assertEqual(result['_pdf'],self.pdf)
        self.assertEqual([path for _,path in self.requests],[EMISSION+'/verificar',EMISSION])

    async def test_invisible_validation_rejection_is_not_retried_or_confirmed(self):
        self.captcha=True
        result=await consult_federal(self.adapter,CNPJ)
        self.assertEqual(result['status'],'captcha')
        self.assertNotIn('_pdf',result)
        self.assertEqual(len(self.requests),1)

    async def test_mismatched_pdf_is_never_returned(self):
        self.pdf=pdf_bytes(cnpj='18192898000102')
        result=await consult_federal(self.adapter,CNPJ)
        self.assertNotEqual(result['status'],'encontrada')
        self.assertNotIn('_pdf',result)


if __name__=='__main__':unittest.main()
