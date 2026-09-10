"""Respostas controladas; não consultam a prefeitura nem emitem certidão real."""
import io
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'.tools')]
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from playwright.async_api import async_playwright
from santa_rita import CITY, URL, HOST, PRINT_PATH, PortalError, parse_certificate, validate_pdf, consult_santa_rita

CNPJ='24492886000104'
CONTROL='ABCDEF1234567890'
TEXT='''CERTIDÃO NEGATIVA DE DÉBITOS
CPF/CNPJ:\t24.492.886/0001-04
Nome:\tCONTRIBUINTE DE TESTE
Código de Controle da Certidão/Número:\tEmitida às:\tVálida até:
ABCDEF1234567890\t12:00:00 do dia 10/09/2026\t09/12/2026
Declaração:
O contribuinte encontra-se quite com o Erário Municipal, até a presente data.
'''

def pdf_bytes(cnpj=CNPJ,control=CONTROL):
    # PDF sintético marcado como teste; não é usado pelo aplicativo.
    writer=PdfWriter()
    page=writer.add_blank_page(width=595,height=842)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    stream=DecodedStreamObject()
    stream.set_data(f'BT /F1 10 Tf 20 800 Td (TESTE SEM VALOR - Certidao Negativa - Santa Rita do Sapucai) Tj 0 -20 Td ({cnpj} {control}) Tj 0 -20 Td (CONTRIBUINTE DE TESTE - 10/09/2026 - 09/12/2026) Tj ET'.encode('ascii'))
    page[NameObject('/Contents')]=writer._add_object(stream)
    result=io.BytesIO();writer.write(result)
    return result.getvalue()

class CertificateTest(unittest.TestCase):
    def test_identity_type_control_and_dates(self):
        cert=parse_certificate(TEXT,CNPJ)
        self.assertEqual(cert['control'],CONTROL)
        self.assertEqual(cert['valid_until'],'2026-12-09')
        self.assertEqual(cert['type'],'Negativa')
        validate_pdf(pdf_bytes(),cert)

    def test_incomplete_or_different_company_never_confirmed(self):
        for text in [TEXT.replace('24.492.886/0001-04','18.192.898/0001-02'),
                     TEXT.split('Código de Controle')[0],
                     TEXT.replace('encontra-se quite','não se encontra quite'),
                     TEXT.replace('09/12/2026','31/02/2026'),
                     TEXT.replace('09/12/2026','09/12/2025')]:
            with self.subTest(text=text):
                with self.assertRaises(PortalError):parse_certificate(text,CNPJ)

    def test_pdf_must_match_html_identity_and_control(self):
        cert=parse_certificate(TEXT,CNPJ)
        for content in [b'<html>Erro</html>',b'%PDF-invalid',pdf_bytes(cnpj='18192898000102'),pdf_bytes(control='OUTROCONTROLE')]:
            with self.subTest(content=content[:20]):
                with self.assertRaises(PortalError):validate_pdf(content,cert)
        for mismatch in [{'name':'OUTRO CONTRIBUINTE'},{'valid_until':'2027-01-01'}]:
            with self.subTest(mismatch=mismatch):
                with self.assertRaises(PortalError):validate_pdf(pdf_bytes(),{**cert,**mismatch})

class BrowserFlowTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.playwright=await async_playwright().start()
        self.browser=await self.playwright.chromium.launch(channel='msedge',headless=True)

    async def asyncTearDown(self):
        await self.browser.close()
        await self.playwright.stop()

    async def flow(self,content=None,wrong_identity=False):
        submissions=[]
        opened=[]
        certificate_text=TEXT.replace('24.492.886/0001-04','18.192.898/0001-02') if wrong_identity else TEXT
        html='''<html><body>
        <button onclick="document.querySelector('#ident').hidden=false">Contribuinte</button>
        <div id="ident" hidden><label><input type="radio">Pessoa Jurídica</label>
        <input name="compInformarContribuinte:formNumero:itIdent">
        <button onclick="document.querySelector('#ident').hidden=true;document.querySelector('#contributor').hidden=false">OK</button></div>
        <div id="contributor" hidden><div>CPF/CNPJ: '''+('18.192.898/0001-02' if wrong_identity else '24.492.886/0001-04')+'''</div>
        <button onclick="document.querySelector('#contributor').hidden=true;document.querySelector('#certificate').hidden=false">CERTIDÃO NEGATIVA DE DÉBITOS</button></div>
        <div id="certificate" hidden><pre>'''+certificate_text+'''</pre>
        <form method="post" action="'''+f'https://{HOST}:8443{PRINT_PATH}'+'''" target="_blank">
        <input type="hidden" name="javax.faces.ViewState" value="TEST-VIEW-STATE">
        <button type="submit" name="printCertificate" value="Imprimir">Imprimir Certidão</button>
        </form></div></body></html>'''
        async def route(request_route):
            request=request_route.request
            if request.url==URL and request.method=='GET':
                await request_route.fulfill(status=200,content_type='text/html; charset=utf-8',body=html)
            elif request.url==f'https://{HOST}:8443{PRINT_PATH}' and request.method=='POST':
                submissions.append(parse_qs(request.post_data))
                await request_route.fulfill(status=200,content_type='application/pdf',body=content if content is not None else pdf_bytes())
            else:
                await request_route.abort()
        browser=self.browser
        class BrowserAdapter:
            async def new_page(self,**kwargs):
                page=await browser.new_page(**kwargs)
                opened.append(page)
                await page.context.route('**/*',route)
                return page
        result=await consult_santa_rita(BrowserAdapter(),CNPJ)
        self.assertTrue(opened[0].is_closed())
        return result,submissions

    async def test_one_click_captures_original_form_pdf_once(self):
        result,submissions=await self.flow()
        self.assertEqual(result['status'],'encontrada',result)
        self.assertEqual(result['_pdf'],pdf_bytes())
        self.assertEqual(len(submissions),1)
        self.assertEqual(submissions[0]['javax.faces.ViewState'],['TEST-VIEW-STATE'])
        self.assertEqual(submissions[0]['printCertificate'],['Imprimir'])

    async def test_pdf_failure_does_not_report_found_or_retry(self):
        result,submissions=await self.flow(content=b'<html>Falha de impressao</html>')
        self.assertNotEqual(result['status'],'encontrada')
        self.assertNotIn('_pdf',result)
        self.assertEqual(len(submissions),1)

    async def test_wrong_contributor_stops_before_issuance(self):
        result,submissions=await self.flow(wrong_identity=True)
        self.assertNotEqual(result['status'],'encontrada')
        self.assertEqual(submissions,[])

if __name__=='__main__':unittest.main()
