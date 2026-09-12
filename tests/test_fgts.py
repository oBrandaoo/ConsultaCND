"""Fluxo controlado do CRF; não consulta a Caixa nem cria certificado real."""
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'.tools')]
from playwright.async_api import async_playwright

from fgts import FGTSError, URL, consult_fgts, parse_certificate_text

CNPJ='00360305000104'
CONTROL='2026090402220022635496'
CERTIFICATE='''
Certificado de Regularidade do FGTS - CRF
Inscrição: 00.360.305/0001-04
Razão social: CONTRIBUINTE DE TESTE
Endereço: RUA DE TESTE 100 / CENTRO / BRASILIA / DF / 70000-000
A Caixa Econômica Federal certifica que, nesta data, a empresa acima identificada
encontra-se em situação regular perante o Fundo de Garantia do Tempo de Serviço - FGTS.
Validade: 04/09/2026 a 03/10/2026
Certificado Número: 2026090402220022635496
Informação obtida em 11/09/2026 20:00:00
'''


class CertificateTest(unittest.TestCase):
    def test_identity_validity_and_control(self):
        certificate=parse_certificate_text(CERTIFICATE,CNPJ)
        self.assertEqual(certificate['control'],CONTROL)
        self.assertEqual(certificate['valid_from'],'2026-09-04')
        self.assertEqual(certificate['valid_until'],'2026-10-03')

    def test_incomplete_or_different_certificate_is_rejected(self):
        for text in (CERTIFICATE.replace('00.360.305/0001-04','18.192.898/0001-02'),
                     CERTIFICATE.replace('encontra-se em situação regular','não se encontra regular'),
                     CERTIFICATE.replace('03/10/2026','03/10/2025'),
                     CERTIFICATE.replace('Certificado Número: '+CONTROL,'')):
            with self.subTest(text=text):
                with self.assertRaises(FGTSError):
                    parse_certificate_text(text,CNPJ)


class BrowserFlowTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.playwright=await async_playwright().start()
        self.browser=await self.playwright.chromium.launch(channel='msedge',headless=True)

    async def asyncTearDown(self):
        await self.browser.close()
        await self.playwright.stop()

    async def flow(self,regular=True,wrong_certificate=False):
        opened=[]
        result=('''<h1>Situação de Regularidade do Empregador</h1>
        <p>A empresa abaixo identificada esta REGULAR no FGTS.</p>
        <p>Inscrição: 00.360.305/0001-04</p>
        <a href="#" onclick="showCertificate();return false">Certificado de Regularidade do FGTS - CRF</a>'''
                if regular else '''<h1>Situação de Regularidade do Empregador</h1>
        <p>A empresa abaixo identificada NÃO está REGULAR no FGTS.</p>
        <p>Inscrição: 00.360.305/0001-04</p>''')
        certificate=CERTIFICATE.replace('00.360.305/0001-04','18.192.898/0001-02') if wrong_certificate else CERTIFICATE
        html='''<html><head><title>Consulta Regularidade do Empregador</title></head><body>
        <select id="mainForm:tipoEstabelecimento"><option value="1">CNPJ</option><option value="3">CPF</option></select>
        <input id="mainForm:txtInscricao1"><select id="mainForm:uf"><option value=""></option><option value="MG">MG</option></select>
        <input id="mainForm:btnConsultar" type="button" value="Consultar" onclick="showResult()">
        <script>
        function showResult(){document.title='Situação de Regularidade do Empregador';document.body.innerHTML=RESULT;}
        function showCertificate(){document.title='Certificado de Regularidade do FGTS - CRF';document.body.innerHTML='<pre>'+CERTIFICATE+'</pre><input id="mainForm:btnVisualizar" type="button" value="Visualizar">';}
        const RESULT='''+repr(result)+''';const CERTIFICATE='''+repr(certificate)+''';
        </script></body></html>'''

        async def route(request_route):
            if request_route.request.url==URL:
                await request_route.fulfill(status=200,content_type='text/html; charset=utf-8',body=html)
            else:
                await request_route.abort()

        browser=self.browser
        class Adapter:
            contexts=[]
            async def new_page(self,**kwargs):
                page=await browser.new_page(**kwargs)
                opened.append(page)
                await page.context.route('**/*',route)
                return page
        result=await consult_fgts(Adapter(),CNPJ)
        self.assertTrue(opened[0].is_closed())
        return result

    async def test_one_click_confirms_and_prints_crf_pdf(self):
        result=await self.flow()
        self.assertEqual(result['status'],'encontrada',result)
        self.assertTrue(result['_pdf'].startswith(b'%PDF-'))
        self.assertEqual(result['certificate']['control'],CONTROL)

    async def test_no_crf_is_not_reported_as_debt(self):
        result=await self.flow(regular=False)
        self.assertEqual(result['status'],'sem_certidao',result)
        self.assertIn('não comprova',result['message'])
        self.assertNotIn('_pdf',result)

    async def test_wrong_certificate_identity_is_never_downloaded(self):
        result=await self.flow(wrong_certificate=True)
        self.assertNotEqual(result['status'],'encontrada')
        self.assertNotIn('_pdf',result)


if __name__=='__main__':
    unittest.main()
