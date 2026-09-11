"""Respostas controladas; não consultam Pouso Alegre nem emitem certidão real."""
import io
import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'.tools')]
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from playwright.async_api import async_playwright
from pouso_alegre import HOST, URL, PortalError, consult_pouso_alegre, parse_pdf, wait_for_form

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

    async def flow(self,content=None,captcha=False,main_block=False,emission_block=False,http_status=200,missing_button=False,
                   delayed_form=False,transient_block=False,blocked_form=False):
        submissions=[];opened=[]
        self.updates=[]
        self.navigations=[]
        outer='<html><body><iframe src="https://'+HOST+'/autoatendimento/servicos/embed/data/test/servicos/certidao-negativa-de-debitos/detalhar/1"></iframe></body></html>'
        block='Alerta A validação automática de segurança (captcha) identificou uma atividade incomum originada da sua rede. Seu acesso foi restrito temporariamente. EST-000549'
        if captcha or main_block:
            inner='<html><body>'+block+'</body></html>'
            if main_block:outer=inner
        else:
            inner='''<html><body><select name="opcaoEmissao" onchange="document.querySelector('#details').hidden=false">
            <option value="">Selecione a Forma de Emissão</option><option>Por CPF/CNPJ</option></select>
            <div id="details" hidden><input name="cpfCnpj"><select name="FinalidadeCertidaoDebito.codigo">
            <option value="">Selecione uma Finalidade...</option><option>Certidão por Contribuinte</option></select>
            <button onclick="fetch('atende.php',{method:'POST',body:'emitir=1'}).then(r=>r.arrayBuffer())">Confirmar</button></div></body></html>'''
            if emission_block:
                inner=inner.replace('.then(r=>r.arrayBuffer())', '.then(r=>r.text()).then(text=>document.body.innerText=text)')
            if missing_button:
                inner=inner.replace('>Confirmar</button>','>Outro botão</button>')
            if delayed_form or transient_block:
                form=inner
                initial=block if transient_block else 'Carregando...'
                inner='<html><body>'+initial+'<script>window.releaseForm=()=>document.body.innerHTML='+json.dumps(form)+'</script></body></html>'
            if blocked_form:
                inner=inner.replace('<body>','<body><div class="modal-mensagem-overlay">'+block+'</div>')
        async def route(request_route):
            request=request_route.request
            if request.url==URL:
                self.navigations.append(request.url)
                await request_route.fulfill(status=http_status,content_type='text/html; charset=utf-8',body=outer)
            elif '/embed/data/' in request.url and request.method=='GET':
                await request_route.fulfill(status=200,content_type='text/html; charset=utf-8',body=inner)
            elif request.url.endswith('/atende.php') and request.method=='POST':
                submissions.append(request.post_data)
                await request_route.fulfill(status=200,content_type='text/plain; charset=utf-8' if emission_block else 'application/pdf',
                                            body=block if emission_block else content if content is not None else pdf_bytes())
            else:await request_route.abort()
        browser=self.browser
        class Adapter:
            contexts=[]
            async def new_page(self,**kwargs):
                page=await browser.new_page(**kwargs);opened.append(page)
                if missing_button:
                    original=page.set_default_timeout
                    page.set_default_timeout=lambda timeout:original(200)
                await page.context.route('**/*',route);return page
        async def short_wait(page,**kwargs):
            # O prazo reduzido mede a transição controlada, não a inicialização do iframe no Edge.
            await page.wait_for_load_state('load')
            if delayed_form or transient_block:
                frame=next(f for f in page.frames if '/embed/data/' in f.url)
                await frame.evaluate('setTimeout(releaseForm, 1000)')
            return await wait_for_form(page,timeout=2,**kwargs)
        started=time.monotonic()
        with patch('pouso_alegre.wait_for_form',side_effect=short_wait):
            result=await consult_pouso_alegre(Adapter(),CNPJ,update=lambda **changes:self.updates.append(changes))
        self.elapsed=time.monotonic()-started
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

    async def test_security_block_preserves_portal_evidence_before_submission(self):
        result,submissions=await self.flow(captcha=True)
        self.assertEqual(result['status'],'bloqueado')
        self.assertIn('EST-000549',result['evidence'])
        self.assertIn('atividade incomum',result['evidence'])
        self.assertEqual(result['diagnostic'],'Etapa: formulario')
        self.assertFalse(result['submitted'])
        self.assertFalse(result['searched'])
        self.assertEqual(submissions,[])
        self.assertGreaterEqual(self.elapsed,2)
        self.assertTrue(any('EST-000549' in change.get('evidence','') and change['status']=='consultando' for change in self.updates))
        self.assertEqual(self.navigations,[URL])

    async def test_delayed_form_continues_to_pdf(self):
        result,submissions=await self.flow(delayed_form=True)
        self.assertEqual(result['status'],'encontrada',result)
        self.assertEqual(submissions,['emitir=1'])

    async def test_transient_security_notice_waits_for_release_then_emits_once(self):
        result,submissions=await self.flow(transient_block=True)
        self.assertEqual(result['status'],'encontrada',result)
        self.assertTrue(any('EST-000549' in change.get('evidence','') for change in self.updates))
        self.assertTrue(any(change.get('evidence')=='' for change in self.updates))
        self.assertNotIn('EST-000549',result['evidence'])
        self.assertEqual(submissions,['emitir=1'])
        self.assertEqual(self.navigations,[URL])

    async def test_form_behind_security_notice_is_never_submitted(self):
        result,submissions=await self.flow(blocked_form=True)
        self.assertEqual(result['status'],'bloqueado',result)
        self.assertEqual(submissions,[])

    async def test_security_block_on_main_page(self):
        result,submissions=await self.flow(main_block=True)
        self.assertEqual(result['status'],'bloqueado')
        self.assertIn('EST-000549',result['evidence'])
        self.assertEqual(submissions,[])

    async def test_security_block_after_submission_never_retries(self):
        result,submissions=await self.flow(emission_block=True)
        self.assertEqual(result['status'],'bloqueado')
        self.assertIn('EST-000549',result['evidence'])
        self.assertTrue(result['submitted'])
        self.assertTrue(result['searched'])
        self.assertEqual(submissions,['emitir=1'])
        self.assertNotIn('_pdf',result)

    async def test_http_access_block_is_not_generic_unavailability(self):
        result,submissions=await self.flow(http_status=403)
        self.assertEqual(result['status'],'bloqueado')
        self.assertEqual(result['evidence'],'HTTP 403')
        self.assertEqual(submissions,[])

    async def test_failure_before_click_does_not_claim_submission(self):
        result,submissions=await self.flow(missing_button=True)
        self.assertEqual(result['status'],'indisponivel')
        self.assertEqual(result['evidence'],'')
        self.assertIn('TimeoutError',result['diagnostic'])
        self.assertFalse(result['submitted'])
        self.assertFalse(result['searched'])
        self.assertEqual(submissions,[])

if __name__=='__main__':unittest.main()
