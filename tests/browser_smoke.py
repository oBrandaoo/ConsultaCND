"""Interface federal com respostas simuladas; não acessa órgãos públicos."""
import asyncio
import sys
import threading
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'.tools'))

from app import Server
from consultations import Consultations, timestamp
from playwright.sync_api import sync_playwright,expect


def main():
    async def runner(rid):
        run=engine.get(rid)
        if 'municipal' in run['results']:
            engine.update(rid,'municipal',status='encontrada',message='Certidão municipal simulada.',
                          evidence='Controle municipal de teste',submitted=True,searched=True,
                          _pdf=b'%PDF-1.4\n%%EOF',checked_at=timestamp())
        if 'federal' in run['results']:
            engine.update(rid,'federal',status='consultando',message='Download federal simulado.')
            await asyncio.sleep(.5)
            engine.update(rid,'federal',status='encontrada',message='Certidão federal simulada.',
                          evidence='<script>alert(1)</script>',submitted=True,searched=True,
                          _pdf=b'%PDF-1.4\n%%EOF',checked_at=timestamp())
        if 'fgts' in run['results']:
            engine.update(rid,'fgts',status='encontrada',message='CRF do FGTS simulado.',
                          evidence='Certificado FGTS de teste',submitted=True,searched=True,
                          _pdf=b'%PDF-1.4\n%%EOF',checked_at=timestamp())
        if 'trabalhista' in run['results']:
            engine.update(rid,'trabalhista',status='encontrada',message='CNDT trabalhista simulada.',
                          evidence='Certidão trabalhista de teste',submitted=True,searched=True,
                          _pdf=b'%PDF-1.4\n%%EOF',checked_at=timestamp())
        if 'falencia' in run['results']:
            engine.update(rid,'falencia',status='encontrada',message='Falência e concordata simulada.',
                          evidence='Certidão judicial de teste',submitted=True,searched=True,
                          _pdf=b'%PDF-1.4\n%%EOF',checked_at=timestamp())
        if 'estadual_mg' in run['results']:
            engine.update(rid,'estadual_mg',status='encontrada',message='CDT estadual MG simulada.',
                          evidence='Certidao estadual MG de teste',submitted=True,searched=True,
                          _pdf=b'%PDF-1.4\n%%EOF',checked_at=timestamp())
        if 'estadual_sp' in run['results']:
            engine.update(rid,'estadual_sp',status='encontrada',message='CND estadual SP simulada.',
                          evidence='Certidao estadual SP de teste',submitted=True,searched=True,
                          _pdf=b'%PDF-1.4\n%%EOF',checked_at=timestamp())

    engine=Consultations(runner)
    server=Server(('127.0.0.1',0),engine)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    artifacts=ROOT/'.runtime';artifacts.mkdir(exist_ok=True)
    errors=[]
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page(viewport={'width':1365,'height':900})
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_address[1]}')
            expect(page.get_by_role('heading',name='Consultar certidões',exact=True)).to_be_visible()
            expect(page.get_by_role('button',name='Consultar selecionadas')).to_be_enabled()
            assert page.get_by_label('Município',exact=True).count()==0
            expect(page.locator('input[value=federal]')).to_be_checked()
            expect(page.locator('input[value=fgts]')).not_to_be_checked()
            expect(page.locator('input[value=trabalhista]')).not_to_be_checked()
            expect(page.locator('input[value=falencia]')).not_to_be_checked()
            expect(page.locator('input[value=estadual_mg]')).not_to_be_checked()
            expect(page.locator('input[value=estadual_sp]')).not_to_be_checked()
            expect(page.locator('input[value=municipal]')).not_to_be_checked()
            page.screenshot(path=str(artifacts/'consulta-federal-inicial.png'),full_page=True)

            page.get_by_label('CNPJ',exact=True).fill('00000000000000')
            page.get_by_role('button',name='Consultar selecionadas').click()
            expect(page.locator('#form-error')).to_be_visible()
            page.get_by_label('CNPJ',exact=True).fill('18.192.898/0001-02')
            page.locator('input[value=fgts]').check()
            page.locator('input[value=trabalhista]').check()
            page.locator('input[value=falencia]').check()
            page.locator('input[value=estadual_mg]').check()
            page.locator('input[value=estadual_sp]').check()
            page.locator('input[value=municipal]').check()
            page.get_by_role('button',name='Consultar selecionadas').click()
            expect(page.locator('#progress-label')).to_have_text('Verificação encerrada',timeout=10000)
            expect(page.locator('.result-card')).to_have_count(7)
            federal_card=page.locator('.result-card').filter(has_text='CND federal')
            expect(federal_card.locator('.evidence')).to_have_text('<script>alert(1)</script>')
            expect(page.locator('.result-card').filter(has_text='CRF do FGTS')).to_contain_text('Certificado FGTS de teste')
            expect(page.locator('.result-card').filter(has_text='CNDT trabalhista')).to_contain_text('Certidão trabalhista de teste')
            expect(page.locator('.result-card').filter(has_text='CND falência e concordata')).to_contain_text('Certidão judicial de teste')
            expect(page.locator('.result-card').filter(has_text='CDT estadual MG')).to_contain_text('Certidao estadual MG de teste')
            expect(page.locator('.result-card').filter(has_text='CND estadual SP')).to_contain_text('Certidao estadual SP de teste')
            assert page.locator('.evidence script').count()==0
            expect(page.locator('.query-summary')).to_contain_text('Brasil + Minas Gerais + São Paulo + Santa Rita do Sapucaí')
            expect(page.get_by_role('link',name='Baixar certidão em PDF')).to_have_count(7)
            page.screenshot(path=str(artifacts/'consulta-federal-resultado.png'),full_page=True)

            page.reload()
            expect(page.locator('.result-card')).to_have_count(7)
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path=str(artifacts/'consulta-federal-mobile.png'),full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            browser.close()
        assert not errors,errors
        print('OK: fluxos federal, FGTS, CNDT, falência/concordata, estaduais MG/SP e Santa Rita, PDF, escape HTML, recuperação e layout móvel. Retornos simulados.')
    finally:
        server.shutdown();server.server_close();thread.join()


if __name__=='__main__':main()
