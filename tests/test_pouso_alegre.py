"""Respostas controladas; não consultam Pouso Alegre nem emitem certidão real."""
import io
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'.tools')]
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from playwright.async_api import async_playwright
from pouso_alegre import HOST, URL, PortalError, consult_pouso_alegre, parse_pdf

CNPJ='23951916000122'
CONTROL='TESTE00000-000-ABCDEFGHIJKLM-0'

def pdf_bytes(cnpj=CNPJ,control=CONTROL,declaration='nao constam pendencias'):
    writer=PdfWriter();page=writer.add_blank_page(width=595,height=842)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    lines=['TESTE SEM VALOR - MUNICIPIO DE POUSO ALEGRE','CERTIDAO NEGATIVA DE DEBITOS 12345/2026',
           'Nome/Razao: 123 - CONTRIBUINTE DE TESTE',f'CNPJ/CPF: {cnpj}',
           'DATA DE EMISSAO DATA DE VALIDADE','10/09/2026 90 dias',declaration,
           'Certidao Emitida as 12:34:56 do dia 10/09/2026 - Codigo para Validacao da certidao:',control]
    stream=DecodedStreamObject();commands=['BT /F1 9 Tf 20 800 Td']
    for index,line in enumerate(lines):commands.append(('' if index==0 else '0 -18 Td ')+f'({line}) Tj')
    commands.append('ET');stream.set_data(' '.join(commands).encode('ascii'))
    page[NameObject('/Contents')]=writer._add_object(stream)
    result=io.BytesIO();writer.write(result);return result.getvalue()

class PdfTest(unittest.TestCase):
    def test_parses_identity_number_control_and_ninety_days(self):
        cert=parse_pdf(pdf_bytes(declaration='nao  constam, ate esta data,  pendencias'),CNPJ)
        self.assertEqual(cert['number'],'12345/2026')
        self.assertEqual(cert['control'],CONTROL)
        self.assertEqual(cert['issued_at'],'2026-09-10T12:34:56')
        self.assertEqual(cert['valid_until'],'2026-12-09')

    def test_rejects_invalid_or_mismatched_document(self):
        for content in [b'<html>erro</html>',b'%PDF-invalid',pdf_bytes(cnpj='18192898000102'),
                        pdf_bytes(declaration='existem pendencias')]:
            with self.subTest(content=content[:20]):
                with self.assertRaises(PortalError):parse_pdf(content,CNPJ)

class BrowserFlowTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.playwright=await async_playwright().start()
        self.browser=await self.playwright.chromium.launch(channel='msedge',headless=True)

    async def asyncTearDown(self):
        await self.browser.close();await self.playwright.stop()

    async def flow(self,content=None,captcha=False):
        submissions=[];opened=[]
        outer='<html><body><iframe src="https://'+HOST+'/autoatendimento/servicos/embed/data/test/servicos/certidao-negativa-de-debitos/detalhar/1"></iframe></body></html>'
        if captcha:
            inner='<html><body>Alerta A validação automática de segurança (captcha) identificou uma atividade incomum originada da sua rede. EST-000549</body></html>'
        else:
            inner='''<html><body><select name="opcaoEmissao" onchange="document.querySelector('#details').hidden=false">
            <option value="">Selecione a Forma de Emissão</option><option>Por CPF/CNPJ</option></select>
            <div id="details" hidden><input name="cpfCnpj"><select name="FinalidadeCertidaoDebito.codigo">
            <option value="">Selecione uma Finalidade...</option><option>Certidão por Contribuinte</option></select>
            <button onclick="fetch('atende.php',{method:'POST',body:'emitir=1'}).then(r=>r.arrayBuffer())">Confirmar</button></div></body></html>'''
        async def route(request_route):
            request=request_route.request
            if request.url==URL:
                await request_route.fulfill(status=200,content_type='text/html; charset=utf-8',body=outer)
            elif '/embed/data/' in request.url and request.method=='GET':
                await request_route.fulfill(status=200,content_type='text/html; charset=utf-8',body=inner)
            elif request.url.endswith('/atende.php') and request.method=='POST':
                submissions.append(request.post_data)
                await request_route.fulfill(status=200,content_type='application/pdf',body=content if content is not None else pdf_bytes())
            else:await request_route.abort()
        browser=self.browser
        class Adapter:
            contexts=[]
            async def new_page(self,**kwargs):
                page=await browser.new_page(**kwargs);opened.append(page)
                await page.context.route('**/*',route);return page
        result=await consult_pouso_alegre(Adapter(),CNPJ)
        self.assertTrue(opened[0].is_closed())
        return result,submissions

    async def test_one_click_selects_cnpj_and_captures_pdf_once(self):
        result,submissions=await self.flow()
        self.assertEqual(result['status'],'encontrada',result)
        self.assertEqual(result['_pdf'],pdf_bytes())
        self.assertEqual(submissions,['emitir=1'])

    async def test_wrong_pdf_is_never_reported_as_certificate(self):
        result,submissions=await self.flow(content=pdf_bytes(cnpj='18192898000102'))
        self.assertNotEqual(result['status'],'encontrada')
        self.assertNotIn('_pdf',result)
        self.assertEqual(len(submissions),1)

    async def test_captcha_is_reported_before_submission(self):
        result,submissions=await self.flow(captcha=True)
        self.assertEqual(result['status'],'captcha')
        self.assertEqual(submissions,[])

if __name__=='__main__':unittest.main()
