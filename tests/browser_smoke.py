"""Interface com respostas simuladas e controladas; não acessa órgãos públicos."""
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
        for service in run['results']:
            engine.update(rid,service,status='consultando',message='Consultando…')
            await asyncio.sleep(.2)
            engine.update(rid,service,status='indisponivel' if service=='federal' else 'login',
                message='Retorno simulado para teste de interface.',
                evidence='<script>alert(1)</script>' if service=='federal' else '',
                submitted=service=='federal',checked_at=timestamp())
    engine=Consultations(runner)
    server=Server(('127.0.0.1',0),engine)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    artifacts=ROOT/'.runtime';artifacts.mkdir(exist_ok=True)
    errors=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1100},locale='pt-BR')
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_address[1]}')
            expect(page.get_by_role('button',name='Consultar selecionadas')).to_be_enabled()
            expect(page.get_by_role('heading',name='Pronto para consultar')).to_be_visible()
            assert page.get_by_role('button',name='Nova empresa').count()==0
            assert page.locator('input[type=file]').count()==0
            page.screenshot(path=str(artifacts/'consulta-inicial.png'),full_page=True)
            page.get_by_label('CNPJ',exact=True).fill('00000000000000')
            page.get_by_label('Município',exact=True).select_option(label='Santa Rita do Sapucaí')
            page.get_by_role('button',name='Consultar selecionadas').click()
            expect(page.locator('#form-error')).to_be_visible()
            page.get_by_label('CNPJ',exact=True).fill('18.192.898/0001-02')
            page.get_by_role('button',name='Consultar selecionadas').click()
            expect(page.locator('#progress-label')).to_have_text('Verificação encerrada',timeout=15000)
            expect(page.locator('.result-card')).to_have_count(5)
            expect(page.locator('.evidence')).to_have_text('<script>alert(1)</script>')
            assert page.locator('.evidence script').count()==0
            assert page.locator('a[href*="santaritasapucai"]').count()==1
            page.screenshot(path=str(artifacts/'consulta-resultados-teste.png'),full_page=True)
            page.reload()
            expect(page.locator('.result-card')).to_have_count(5)
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path=str(artifacts/'consulta-mobile.png'),full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.get_by_role('button',name='Desmarcar todas').click()
            page.get_by_role('button',name='Consultar selecionadas').click()
            expect(page.locator('#form-error')).to_have_text('Selecione pelo menos uma certidão.')
            browser.close()
        assert not errors,errors
        print('OK: consulta, validação, seleção, resultados, escape HTML, recuperação após recarga e layout móvel. Retornos simulados.')
    finally:
        server.shutdown();server.server_close();thread.join()
if __name__=='__main__':main()

