"""Fluxo controlado da certidao civel; nao consulta o TJMG nem emite documento real."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / '.tools')]

from playwright.async_api import async_playwright
from falencia import FalenciaError, URL, consult_falencia, parse_certificate_text


CNPJ = '18192898000102'
CONTROL = '123456/2026'
COMARCA = 'Belo Horizonte'
CERTIFICATE = '''
CERTIDAO CIVEL DE FALENCIA E CONCORDATA/RECUPERACAO JUDICIAL

Comarca: Belo Horizonte
Certidao no: 123456/2026
Data de emissao: 13/09/2026
Validade: 13/10/2026

Certifico que, em consulta aos registros desta comarca, para o CNPJ
18.192.898/0001-02, NAO CONSTA distribuicao de falencia, concordata ou
recuperacao judicial em nome de CONTRIBUINTE DE TESTE LTDA.
'''


class CertificateTest(unittest.TestCase):
    def test_parses_identity_number_district_and_validity(self):
        certificate = parse_certificate_text(CERTIFICATE, CNPJ)
        self.assertEqual(certificate['control'], CONTROL)
        self.assertEqual(certificate['comarca'], COMARCA)
        self.assertEqual(certificate['issued_at'], '2026-09-13')
        self.assertEqual(certificate['valid_until'], '2026-10-13')

    def test_different_non_negative_or_inconsistent_certificate_is_rejected(self):
        for text in (
            CERTIFICATE.replace('18.192.898/0001-02', '00.360.305/0001-04'),
            CERTIFICATE.replace('NAO CONSTA distribuicao', 'CONSTA distribuicao'),
            CERTIFICATE.replace('13/10/2026', '13/10/2025'),
        ):
            with self.subTest(text=text):
                with self.assertRaises(FalenciaError):
                    parse_certificate_text(text, CNPJ)


class BrowserFlowTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(channel='msedge', headless=True)

    async def asyncTearDown(self):
        await self.browser.close()
        await self.playwright.stop()

    async def flow(self, captcha=False, assisted=False):
        opened = []
        body = 'Codigo de Verificacao/CAPTCHA' if captcha else CERTIFICATE
        completion = CERTIFICATE if captcha and assisted else body
        html = '''<html><head><title>Certidao Civel</title></head><body>
        <label><input type="radio" name="pessoa" value="juridica"> Pessoa Juridica</label>
        <label for="cpf-cnpj">CPF/CNPJ</label><input id="cpf-cnpj">
        <label for="tipo">Tipo</label><select id="tipo"><option>Concordata/Falencia</option></select>
        <button type="button" onclick="solicitar()">Solicitar</button>
        <script>
        const CERTIFICATE = ''' + json.dumps(body) + ''';
        const COMPLETION = ''' + json.dumps(completion) + ''';
        function solicitar() {
          document.body.innerHTML = '<pre>' + CERTIFICATE + '</pre>';
          if (COMPLETION !== CERTIFICATE) setTimeout(() => document.body.innerHTML = '<pre>' + COMPLETION + '</pre>', 100);
        }
        </script></body></html>'''

        async def route(request_route):
            if request_route.request.url == URL:
                await request_route.fulfill(
                    status=200, content_type='text/html; charset=utf-8', body=html
                )
            else:
                await request_route.abort()

        browser = self.browser

        class Adapter:
            contexts = []

            async def new_page(self, **kwargs):
                page = await browser.new_page(**kwargs)
                opened.append(page)
                await page.context.route('**/*', route)
                return page

        result = await consult_falencia(Adapter(), CNPJ, assisted=assisted)
        self.assertTrue(opened[0].is_closed())
        return result

    async def test_selects_company_and_prints_negative_certificate(self):
        result = await self.flow()
        self.assertEqual(result['status'], 'encontrada', result)
        self.assertTrue(result['_pdf'].startswith(b'%PDF-'))
        self.assertEqual(result['certificate']['control'], CONTROL)

    async def test_captcha_waits_for_user_and_resumes_when_assisted(self):
        result = await self.flow(captcha=True, assisted=True)
        self.assertEqual(result['status'], 'encontrada', result)
        self.assertTrue(result['_pdf'].startswith(b'%PDF-'))

    async def test_captcha_is_reported_without_assistance(self):
        result = await self.flow(captcha=True)
        self.assertEqual(result['status'], 'captcha', result)
        self.assertNotIn('_pdf', result)


if __name__ == '__main__':
    unittest.main()
