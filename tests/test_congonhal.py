"""Respostas controladas; nao consultam Congonhal nem emitem certidao real."""
import io
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'.tools')]

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from playwright.async_api import async_playwright

from congonhal import HOST, URL, CERTIFICATE_URL, PortalError, consult_congonhal, parse_pdf


CNPJ='23951916000122'
CONTROL='CONG-ABCDEF-2026'
USER_NAME='Usuario de Teste'
USER_CPF='52998224725'


def pdf_bytes(cnpj=CNPJ,control=CONTROL,declaration='Certidao Negativa de Debitos'):
    """PDF sintetico, exclusivamente para validar o parser local."""
    writer=PdfWriter()
    page=writer.add_blank_page(width=595,height=842)
    font=DictionaryObject({
        NameObject('/Type'):NameObject('/Font'),
        NameObject('/Subtype'):NameObject('/Type1'),
        NameObject('/BaseFont'):NameObject('/Helvetica'),
    })
    page[NameObject('/Resources')]=DictionaryObject({
        NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})
    })
    lines=[
        'TESTE SEM VALOR - PREFEITURA MUNICIPAL DE CONGONHAL',
        declaration,
        'Nome: CONTRIBUINTE DE TESTE',
        f'CNPJ: {cnpj}',
        'Numero da Certidao: 12345/2026',
        f'Controle: {control}',
        'Emitida: 10/09/2026 12:34:56',
        'Valida ate: 09/12/2026',
    ]
    commands=['BT /F1 9 Tf 20 800 Td']
    for index,line in enumerate(lines):
        commands.append(('' if index==0 else '0 -18 Td ')+f'({line}) Tj')
    commands.append('ET')
    stream=DecodedStreamObject()
    stream.set_data(' '.join(commands).encode('ascii'))
    page[NameObject('/Contents')]=writer._add_object(stream)
    result=io.BytesIO()
    writer.write(result)
    return result.getvalue()


class PdfTest(unittest.TestCase):
    def test_parses_congonhal_negative_certificate_identity_control_and_dates(self):
        certificate=parse_pdf(pdf_bytes(),CNPJ)

        self.assertEqual(certificate['cnpj'],CNPJ)
        self.assertEqual(certificate['issuer'],'Prefeitura Municipal de Congonhal')
        self.assertEqual(certificate['type'],'Negativa')
        self.assertEqual(certificate['number'],'12345/2026')
        self.assertEqual(certificate['control'],CONTROL)
        self.assertEqual(certificate['issued_at'],'2026-09-10T12:34:56')
        self.assertEqual(certificate['valid_until'],'2026-12-09')

    def test_rejects_html_invalid_pdf_other_cnpj_and_debts(self):
        for content in [
            b'<html>Falha na emissao</html>',
            b'%PDF-invalido',
            pdf_bytes(cnpj='18192898000102'),
            pdf_bytes(declaration='Certidao Negativa de Debitos - constam debitos em aberto'),
        ]:
            with self.subTest(content=content[:24]):
                with self.assertRaises(PortalError):
                    parse_pdf(content,CNPJ)


class BrowserFlowTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.playwright=await async_playwright().start()
        self.browser=await self.playwright.chromium.launch(headless=True)

    async def asyncTearDown(self):
        await self.browser.close()
        await self.playwright.stop()

    async def flow(self,content=None,requester=None,requester_fields=True,certificate_field=True,purpose_field=True):
        submissions=[]
        clicks={'menu_emissao':0,'autenticacao':0,'popup_get':0,'print_click':0}
        opened=[]
        certificate_html='<input name="nrcpfcnpj" class="form-control mb-2" type="text" placeholder="CPF/CNPJ da Certidao *" id="nrcpfcnpj" maxlength="50">' if certificate_field else ''
        requester_html='''
          <input name="nmrequerente" class="form-control mb-2" type="text" placeholder="Nome do Requerente *" id="nmrequerente" maxlength="50">
          <input name="nrdocumento" class="form-control mb-2" type="text" placeholder="Numero do CPF *" id="nrdocumento" maxlength="50">
        ''' if requester_fields else ''
        purpose_html='<input name="finalidade" class="form-control mb-2" type="text" placeholder="Finalidade" id="finalidade" maxlength="50">' if purpose_field else ''
        html=f'''<html><body>
        <script>
        function sendcertidao(form){{
          const data=new URLSearchParams(new FormData(form));
          fetch('/track/submit',{{method:'POST',body:data}});
          window.open('{CERTIFICATE_URL}','_blank');
          return false;
        }}
        </script>
        <section id="auth">
          <h6>Autenticacao do Contribuinte</h6>
            <label>CPF ou CNPJ <input name="auth_cnpj"></label>
            <button type="button" onclick="fetch('/track/auth',{{method:'POST'}})">Acessar</button>
          </section>
          <aside>
            <nav>
            <section onclick="document.querySelector('#service-list').hidden=false">Servicos</section>
            <div id="service-list" hidden>
              <div>Lista de Servicos</div>
              <span onclick="fetch('/track/menu',{{method:'POST'}});document.querySelector('#issue').hidden=false">Emissao de Certidao</span>
            </div>
          </nav>
        </aside>
        <section id="issue" hidden>
          <h1>Emitir Certidao de Debito</h1>
          <p>Certidao Debitos e um documento emitido pela Prefeitura.</p>
          <p>Metodo de geracao da Certidao de Debito: Rastreamento pelo CPF/CNPJ informado.</p>
          <form id="issue-form" action="imprime_certidao.php?" method="post" name="AForm" onsubmit="sendcertidao(this)">
          {certificate_html}
          {requester_html}
          {purpose_html}
          <input name="observacao" class="form-control mb-2" type="text" placeholder="Observacao" id="observacao" maxlength="50">
          <p>* CAMPOS DE PREENCHIMENTO OBRIGATORIO</p>
          <input type="submit" class="btn btn-primary" value="Emitir a Certidao">
          </form>
        </section>
        </body></html>'''
        print_page=f'''<html><body>
        <section id="print">
          <h1>Certidao de Debito</h1>
          <input type="button" value="Imprimir" onclick="fetch('/track/print',{{method:'POST'}}).then(()=>fetch('/meuiptu/cnd.pdf'))">
        </section>
        </body></html>'''

        async def route(route):
            request=route.request
            if request.url in (URL,URL.rstrip('#')) and request.method=='GET':
                await route.fulfill(status=200,content_type='text/html; charset=utf-8',body=html)
            elif request.url==CERTIFICATE_URL and request.method=='GET':
                clicks['popup_get']+=1
                await route.fulfill(status=200,content_type='text/html; charset=utf-8',body=print_page)
            elif request.url==f'https://{HOST}/track/submit' and request.method=='POST':
                submissions.append(request.post_data)
                await route.fulfill(status=204,body='')
            elif request.url==f'https://{HOST}/track/print' and request.method=='POST':
                clicks['print_click']+=1
                await route.fulfill(status=204,body='')
            elif request.url==f'https://{HOST}/meuiptu/cnd.pdf' and request.method=='GET':
                await route.fulfill(
                    status=200,
                    content_type='application/pdf',
                    body=content if content is not None else pdf_bytes(),
                )
            elif request.url==f'https://{HOST}/track/menu' and request.method=='POST':
                clicks['menu_emissao']+=1
                await route.fulfill(status=204,body='')
            elif request.url==f'https://{HOST}/track/auth' and request.method=='POST':
                clicks['autenticacao']+=1
                await route.fulfill(status=204,body='')
            else:
                await route.abort()

        browser=self.browser

        class BrowserAdapter:
            async def new_page(self,**kwargs):
                page=await browser.new_page(**kwargs)
                opened.append(page)
                await page.context.route('**/*',route)
                return page

        result=await consult_congonhal(BrowserAdapter(),CNPJ,requester=requester or {
            'nome_usuario':USER_NAME,
            'cpf_usuario':USER_CPF,
        })
        self.assertTrue(opened[0].is_closed())
        return result,submissions,clicks

    async def test_emits_and_captures_matching_pdf_once(self):
        result,submissions,clicks=await self.flow()

        self.assertEqual(result['status'],'encontrada',result)
        self.assertEqual(result['_pdf'],pdf_bytes())
        self.assertEqual(len(submissions),1)
        self.assertEqual(clicks['popup_get'],1)
        self.assertEqual(clicks['print_click'],1)
        self.assertEqual(clicks['menu_emissao'],1)
        self.assertEqual(clicks['autenticacao'],0)
        payload={key:values[-1] for key,values in parse_qs(submissions[0]).items()}
        self.assertEqual(payload['nrcpfcnpj'],'23.951.916/0001-22')
        self.assertEqual(payload['nmrequerente'],'Usuario de Teste')
        self.assertEqual(payload['nrdocumento'],'529.982.247-25')
        self.assertEqual(payload['finalidade'],'Emissao de certidao de debito')
        self.assertEqual(payload.get('observacao',''),'')
        self.assertNotIn('auth_cnpj',payload)

    async def test_mismatched_pdf_is_never_reported_as_found_or_retried(self):
        result,submissions,_=await self.flow(content=pdf_bytes(cnpj='18192898000102'))

        self.assertNotEqual(result['status'],'encontrada')
        self.assertNotIn('_pdf',result)
        self.assertEqual(len(submissions),1)

    async def test_requester_name_and_cpf_are_required(self):
        with self.assertRaises(PortalError):
            await consult_congonhal(object(),CNPJ,requester={})

    async def test_missing_requester_fields_on_portal_does_not_emit_pdf(self):
        result,submissions,_=await self.flow(requester_fields=False)

        self.assertEqual(result['status'],'indisponivel',result)
        self.assertIn('campo obrigatorio',result['message'])
        self.assertEqual(submissions,[])

    async def test_missing_certificate_field_on_portal_does_not_emit_pdf(self):
        result,submissions,_=await self.flow(certificate_field=False)

        self.assertEqual(result['status'],'indisponivel',result)
        self.assertIn('CPF/CNPJ da certidao',result['message'])
        self.assertEqual(submissions,[])

    async def test_missing_purpose_field_on_portal_does_not_emit_pdf(self):
        result,submissions,_=await self.flow(purpose_field=False)

        self.assertEqual(result['status'],'indisponivel',result)
        self.assertIn('finalidade',result['message'])
        self.assertEqual(submissions,[])


if __name__=='__main__':
    unittest.main()
