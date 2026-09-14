"""Fluxo controlado da CNDT; nao consulta o TST nem emite certidao real."""
import asyncio
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / '.tools')]

from playwright.async_api import async_playwright
from trabalhista import TrabalhistaError, URL, consult_trabalhista, parse_certificate_text


CNPJ = '18192898000102'
CONTROL = '12345678/2026'
CERTIFICATE = '''
CERTIDAO NEGATIVA DE DEBITOS TRABALHISTAS

Nome: CONTRIBUINTE DE TESTE LTDA
CNPJ: 18.192.898/0001-02

Certidao no: 12345678/2026
Expedicao: 13/09/2026, as 10:00:00
Validade: 12/03/2027 - 180 (cento e oitenta) dias, contados da data
de sua expedicao.

Certifica-se que CONTRIBUINTE DE TESTE LTDA, inscrito(a) no CNPJ sob o
no 18.192.898/0001-02, NAO CONSTA do Banco Nacional de Devedores
Trabalhistas.
'''


class CertificateTest(unittest.TestCase):
    def test_identity_number_and_validity(self):
        certificate = parse_certificate_text(CERTIFICATE, CNPJ)
        self.assertEqual(certificate['control'], CONTROL)
        self.assertEqual(certificate['issued_at'], '2026-09-13')
        self.assertEqual(certificate['valid_until'], '2027-03-12')

    def test_different_incomplete_or_inconsistent_certificate_is_rejected(self):
        for text in (
            CERTIFICATE.replace('18.192.898/0001-02', '00.360.305/0001-04'),
            CERTIFICATE.replace('NAO CONSTA do Banco Nacional de Devedores Trabalhistas.', ''),
            CERTIFICATE.replace('12/03/2027', '12/03/2025'),
        ):
            with self.subTest(text=text):
                with self.assertRaises(TrabalhistaError):
                    parse_certificate_text(text, CNPJ)


class BrowserFlowTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(channel='msedge', headless=True)

    async def asyncTearDown(self):
        await self.browser.close()
        await self.playwright.stop()

    async def flow(self, captcha=False):
        opened = []
        content = 'Digite os caracteres exibidos na imagem' if captcha else CERTIFICATE
        html = '''<html><head><title>Certidao Negativa de Debitos Trabalhistas</title></head>
        <body><label for="cpf-cnpj">CPF/CNPJ</label><input id="cpf-cnpj">
        <button type="button" onclick="emitir()">Emitir Certidao</button>
        <script>
        const CERTIFICATE = ''' + json.dumps(content) + ''';
        function emitir() { document.body.innerHTML = '<pre>' + CERTIFICATE + '</pre>'; }
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

        result = await consult_trabalhista(Adapter(), CNPJ)
        self.assertTrue(opened[0].is_closed())
        return result

    async def test_emits_and_prints_cndt_pdf_without_captcha(self):
        result = await self.flow()
        self.assertEqual(result['status'], 'encontrada', result)
        self.assertTrue(result['_pdf'].startswith(b'%PDF-'))
        self.assertEqual(result['certificate']['control'], CONTROL)

    async def test_visible_captcha_without_assistance_is_not_a_certificate(self):
        result = await self.flow(captcha=True)
        self.assertEqual(result['status'], 'captcha', result)
        self.assertNotIn('_pdf', result)

    async def assisted_flow(self):
        """Portal local que so exibe a CNDT depois da acao humana simulada."""
        opened = []
        html = '''<html><head><title>Certidao Negativa de Debitos Trabalhistas</title></head>
        <body><label for="cpf-cnpj">CPF/CNPJ</label><input id="cpf-cnpj">
        <button type="button" onclick="emitir()">Emitir Certidao</button>
        <script>
        const CERTIFICATE = ''' + json.dumps(CERTIFICATE) + ''';
        function emitir() {
          document.body.innerHTML = '<p>Digite os caracteres exibidos na imagem</p>';
        }
        window.completeCaptcha = () => {
          document.body.innerHTML = '<pre>' + CERTIFICATE + '</pre>';
        };
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

        return Adapter(), opened

    async def wait_for_user_update(self, updates):
        for _ in range(100):
            if any(item.get('status') == 'aguardando_usuario' for item in updates):
                return
            await asyncio.sleep(.02)
        self.fail('A consulta assistida nao publicou aguardando_usuario.')

    async def test_assisted_captcha_publishes_waiting_for_user(self):
        adapter, opened = await self.assisted_flow()
        updates = []
        task = asyncio.create_task(consult_trabalhista(
            adapter, CNPJ, assisted=True, update=lambda **changes: updates.append(changes)
        ))
        try:
            await self.wait_for_user_update(updates)
            self.assertFalse(opened[0].is_closed())
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_assisted_captcha_continues_after_simulated_human_action(self):
        adapter, opened = await self.assisted_flow()
        updates = []
        task = asyncio.create_task(consult_trabalhista(
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
        self.assertEqual(result['certificate']['control'], CONTROL)

    async def test_assisted_invalid_captcha_keeps_waiting_for_retry(self):
        adapter, opened = await self.assisted_flow()
        updates = []
        task = asyncio.create_task(consult_trabalhista(
            adapter, CNPJ, assisted=True, update=lambda **changes: updates.append(changes)
        ))
        try:
            await self.wait_for_user_update(updates)
            await opened[0].evaluate(
                "document.body.innerHTML = '<p>Captcha invalido. Digite os caracteres exibidos na imagem</p>'"
            )
            await asyncio.sleep(.2)
            self.assertFalse(task.done())
            await opened[0].evaluate('window.completeCaptcha()')
            result = await asyncio.wait_for(task, 5)
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(result['status'], 'encontrada', result)
        self.assertTrue(result['_pdf'].startswith(b'%PDF-'))

    async def test_assisted_captcha_timeout_returns_captcha_without_pdf(self):
        adapter, _ = await self.assisted_flow()
        updates = []
        result = await asyncio.wait_for(consult_trabalhista(
            adapter, CNPJ, assisted=True, update=lambda **changes: updates.append(changes),
            captcha_timeout=.05,
        ), 2)
        self.assertTrue(any(item.get('status') == 'aguardando_usuario' for item in updates))
        self.assertEqual(result['status'], 'captcha', result)
        self.assertNotIn('_pdf', result)


if __name__ == '__main__':
    unittest.main()
