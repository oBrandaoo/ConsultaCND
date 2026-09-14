"""Fluxos estaduais controlados; nao consultam SEF/MG ou Sefaz/SP reais."""
import asyncio
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / '.tools')]

from playwright.async_api import async_playwright

from estadual_mg import MGCndError, URL as MG_URL, consult_estadual_mg, parse_certificate_text as parse_mg_certificate
from estadual_sp import SPCndError, URL as SP_URL, consult_estadual_sp, parse_certificate_text as parse_sp_certificate


CNPJ = '18192898000102'
MG_CONTROL = '123456789.123456'
SP_CONTROL = '987654321/2026'
MG_CERTIFICATE = '''
SECRETARIA DE ESTADO DE FAZENDA DE MINAS GERAIS
CERTIDAO DE DEBITOS TRIBUTARIOS - CDT

Certidao no: 123456789.123456
CNPJ: 18.192.898/0001-02
Data de emissao: 13/09/2026
Validade: 12/12/2099

Certifica-se que NAO CONSTAM debitos tributarios perante a Fazenda Publica
do Estado de Minas Gerais para o contribuinte acima identificado.
'''
SP_CERTIFICATE = '''
SECRETARIA DA FAZENDA E PLANEJAMENTO DO ESTADO DE SAO PAULO
CERTIDAO NEGATIVA DE DEBITOS TRIBUTARIOS NAO INSCRITOS NA DIVIDA ATIVA

Certidao no: 987654321/2026
CNPJ: 18.192.898/0001-02
Data de emissao: 13/09/2026
Validade: 12/12/2099

Certifica-se que NAO CONSTAM debitos tributarios nao inscritos na divida ativa
do Estado de Sao Paulo para o contribuinte acima identificado.
'''


class CertificateTest(unittest.TestCase):
    def test_parses_mg_negative_cdt(self):
        certificate = parse_mg_certificate(MG_CERTIFICATE, CNPJ)
        self.assertEqual(certificate['control'], MG_CONTROL)
        self.assertEqual(certificate['issued_at'], '2026-09-13')
        self.assertEqual(certificate['valid_until'], '2099-12-12')

    def test_rejects_invalid_mg_certificate(self):
        for text in (
            MG_CERTIFICATE.replace('18.192.898/0001-02', '00.360.305/0001-04'),
            MG_CERTIFICATE.replace('NAO CONSTAM debitos tributarios', 'CONSTAM debitos tributarios'),
            MG_CERTIFICATE.replace('12/12/2099', '12/12/2025'),
        ):
            with self.subTest(text=text):
                with self.assertRaises(MGCndError):
                    parse_mg_certificate(text, CNPJ)

    def test_parses_sp_negative_non_enrolled_tax_debt_certificate(self):
        certificate = parse_sp_certificate(SP_CERTIFICATE, CNPJ)
        self.assertEqual(certificate['control'], SP_CONTROL)
        self.assertEqual(certificate['issued_at'], '2026-09-13')
        self.assertEqual(certificate['valid_until'], '2099-12-12')

    def test_rejects_invalid_sp_certificate(self):
        for text in (
            SP_CERTIFICATE.replace('18.192.898/0001-02', '00.360.305/0001-04'),
            SP_CERTIFICATE.replace('NAO CONSTAM debitos tributarios', 'CONSTAM debitos tributarios'),
            SP_CERTIFICATE.replace('12/12/2099', '12/12/2025'),
        ):
            with self.subTest(text=text):
                with self.assertRaises(SPCndError):
                    parse_sp_certificate(text, CNPJ)


class BrowserFlowTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)

    async def asyncTearDown(self):
        await self.browser.close()
        await self.playwright.stop()

    async def flow(self, url, consult, certificate, captcha=False):
        opened = []
        content = 'CAPTCHA: informe o codigo de seguranca exibido' if captcha else certificate
        html = '''<html><head><title>Certidao Estadual</title></head><body>
        <label for="cnpj">CNPJ</label><input id="cnpj">
        <button type="button" onclick="emitir()">Emitir</button>
        <script>
        const CERTIFICATE = ''' + json.dumps(content) + ''';
        function emitir() { document.body.innerHTML = '<pre>' + CERTIFICATE + '</pre>'; }
        </script></body></html>'''

        async def route(request_route):
            if request_route.request.url == url:
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

        result = await consult(Adapter(), CNPJ)
        self.assertTrue(opened[0].is_closed())
        return result

    async def test_mg_and_sp_emit_and_print_certificates(self):
        for url, consult, certificate in (
            (MG_URL, consult_estadual_mg, MG_CERTIFICATE),
            (SP_URL, consult_estadual_sp, SP_CERTIFICATE),
        ):
            with self.subTest(url=url):
                result = await self.flow(url, consult, certificate)
                self.assertEqual(result['status'], 'encontrada', result)
                self.assertTrue(result['_pdf'].startswith(b'%PDF-'))

    async def test_mg_and_sp_captcha_is_not_a_certificate(self):
        for url, consult, certificate in (
            (MG_URL, consult_estadual_mg, MG_CERTIFICATE),
            (SP_URL, consult_estadual_sp, SP_CERTIFICATE),
        ):
            with self.subTest(url=url):
                result = await self.flow(url, consult, certificate, captcha=True)
                self.assertEqual(result['status'], 'captcha', result)
                self.assertNotIn('_pdf', result)

    async def assisted_sp_flow(self):
        """Sefaz/SP local, com CAPTCHA e resolucoes humanas simuladas."""
        opened = []
        html = '''<html><head><title>Certidao Estadual SP</title></head><body>
        <label for="cnpj">CNPJ</label><input id="cnpj">
        <p>CAPTCHA: informe o codigo de seguranca exibido antes de emitir</p>
        <button type="button" onclick="emitir()">Emitir</button>
        <script>
        const CERTIFICATE = ''' + json.dumps(SP_CERTIFICATE) + ''';
        function emitir() {
          if (!document.querySelector('#cnpj').value) {
            document.body.innerHTML = '<p>CNPJ nao preenchido</p>';
            return;
          }
          document.body.innerHTML = '<p>CAPTCHA: informe o codigo de seguranca exibido</p>';
        }
        window.invalidateCaptcha = () => {
          document.body.innerHTML = '<p>CAPTCHA invalido. Informe o codigo de seguranca novamente.</p>';
        };
        window.completeCaptcha = () => {
          document.body.innerHTML = '<pre>' + CERTIFICATE + '</pre>';
        };
        </script></body></html>'''

        async def route(request_route):
            if request_route.request.url == SP_URL:
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

        return Adapter(), opened

    async def wait_for_user_update(self, updates, count=1):
        for _ in range(100):
            if sum(item.get('status') == 'aguardando_usuario' for item in updates) >= count:
                return
            await asyncio.sleep(.02)
        self.fail('A consulta assistida nao publicou aguardando_usuario.')

    async def test_assisted_sp_captcha_publishes_waiting_for_user(self):
        adapter, opened = await self.assisted_sp_flow()
        updates = []
        task = asyncio.create_task(consult_estadual_sp(
            adapter, CNPJ, assisted=True, update=lambda **changes: updates.append(changes)
        ))
        try:
            await self.wait_for_user_update(updates)
            self.assertFalse(opened[0].is_closed())
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_assisted_sp_captcha_continues_after_simulated_human_action(self):
        adapter, opened = await self.assisted_sp_flow()
        updates = []
        task = asyncio.create_task(consult_estadual_sp(
            adapter, CNPJ, assisted=True, update=lambda **changes: updates.append(changes)
        ))
        try:
            await self.wait_for_user_update(updates)
            await opened[0].evaluate('window.completeCaptcha()')
            result = await asyncio.wait_for(task, 5)
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(result['status'], 'encontrada', result)
        self.assertTrue(result['_pdf'].startswith(b'%PDF-'))
        self.assertEqual(result['certificate']['control'], SP_CONTROL)

    async def test_assisted_sp_captcha_timeout_returns_captcha_without_pdf(self):
        adapter, _ = await self.assisted_sp_flow()
        updates = []
        result = await asyncio.wait_for(consult_estadual_sp(
            adapter, CNPJ, assisted=True, update=lambda **changes: updates.append(changes),
            captcha_timeout=.05,
        ), 2)
        self.assertTrue(any(item.get('status') == 'aguardando_usuario' for item in updates))
        self.assertEqual(result['status'], 'captcha', result)
        self.assertNotIn('_pdf', result)

    async def test_assisted_sp_invalid_captcha_allows_a_new_attempt(self):
        adapter, opened = await self.assisted_sp_flow()
        updates = []
        task = asyncio.create_task(consult_estadual_sp(
            adapter, CNPJ, assisted=True, update=lambda **changes: updates.append(changes)
        ))
        try:
            await self.wait_for_user_update(updates)
            await opened[0].evaluate('window.invalidateCaptcha()')
            await self.wait_for_user_update(updates, count=2)
            await opened[0].evaluate('window.completeCaptcha()')
            result = await asyncio.wait_for(task, 5)
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(result['status'], 'encontrada', result)
        self.assertTrue(result['_pdf'].startswith(b'%PDF-'))


if __name__ == '__main__':
    unittest.main()
