"""CND municipal gratuita de Pouso Alegre pelo portal público Atende.Net."""
import asyncio
import io
import os
import re
import subprocess
import tempfile
import time
import unicodedata
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parent
CITY='Pouso Alegre'
HOST='pousoalegre.atende.net'
URL=f'https://{HOST}/autoatendimento/servicos/certidao-negativa-de-debitos/detalhar/1'
MAX_PDF=5*1024*1024


class PortalError(Exception):
    def __init__(self,message,status='manual',evidence=''):
        super().__init__(message)
        self.status=status
        self.evidence=evidence[:1800]


class PersistentBrowser:
    """Adapta o contexto persistente à interface mínima usada pelo conector."""
    def __init__(self,context):
        self.context=context
        self.contexts=[context]

    async def close(self):
        await self.context.close()


def fold(text):
    return ''.join(c for c in unicodedata.normalize('NFD',text.casefold()) if not unicodedata.combining(c))


def find_edge():
    candidates=[]
    for variable in ('PROGRAMFILES(X86)','PROGRAMFILES','LOCALAPPDATA'):
        base=os.environ.get(variable)
        if base:candidates.append(Path(base)/'Microsoft/Edge/Application/msedge.exe')
    edge=next((path for path in candidates if path.is_file()),None)
    if not edge:
        raise PortalError('Microsoft Edge não encontrado. Instale o navegador para consultar Pouso Alegre.','indisponivel')
    return edge


async def launch_pouso_browser(playwright):
    """Abre Edge visível sem alterar proteções do portal e conecta pelo CDP local."""
    external=os.environ.get('CERTIFICA_POUSO_CDP')
    if external:
        parsed=urlsplit(external)
        if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost') or not parsed.port:
            raise PortalError('A configuração local do Edge para Pouso Alegre é inválida.','indisponivel')
        browser=await playwright.chromium.connect_over_cdp(external,timeout=10000)
        return browser,None,None
    runtime=ROOT/'.runtime';runtime.mkdir(exist_ok=True)
    profile=tempfile.TemporaryDirectory(prefix='pouso-edge-',dir=runtime)
    port_file=Path(profile.name)/'DevToolsActivePort'
    arguments=[str(find_edge()),'--remote-debugging-port=0','--remote-debugging-address=127.0.0.1',
               f'--user-data-dir={profile.name}','--no-first-run','--disable-features=msEdgeFirstRunExperience',
               '--no-default-browser-check','--new-window','about:blank']
    try:
        process=subprocess.Popen(arguments,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        deadline=time.monotonic()+25
        last_error=None
        while time.monotonic()<deadline:
            try:
                # O processo inicial do Edge pode encerrar ao transferir o perfil
                # para o processo principal; o arquivo é a fonte confiável da porta.
                lines=port_file.read_text(encoding='utf-8').splitlines()
                port=int(lines[0])
                endpoint=f'http://127.0.0.1:{port}'
                await asyncio.to_thread(lambda:urllib.request.urlopen(endpoint+'/json/version',timeout=.5).close())
                browser=await playwright.chromium.connect_over_cdp(endpoint,timeout=10000)
                return browser,process,profile
            except Exception as error:
                last_error=error
                await asyncio.sleep(.2)
        detail=type(last_error).__name__ if last_error else 'sem resposta'
        raise PortalError(f'Não foi possível conectar à janela temporária do Edge ({detail}). Feche outras janelas de teste e tente novamente.','indisponivel')
    except Exception as direct_error:
        if 'process' in locals() and process.poll() is None:process.terminate()
        try:profile.cleanup()
        except OSError:pass
        # Alguns ambientes do Windows impedem a conexão CDP criada por um
        # subprocesso. O contexto persistente visível mantém o fluxo oficial.
        fallback=tempfile.TemporaryDirectory(prefix='pouso-playwright-',dir=runtime)
        try:
            context=await playwright.chromium.launch_persistent_context(
                fallback.name,channel='msedge',headless=False,locale='pt-BR',
                args=['--no-first-run','--no-default-browser-check'])
            return PersistentBrowser(context),None,fallback
        except Exception as fallback_error:
            try:fallback.cleanup()
            except OSError:pass
            if isinstance(direct_error,PortalError):
                raise PortalError(f'{direct_error} A abertura alternativa também falhou ({type(fallback_error).__name__}).','indisponivel')
            raise PortalError(f'Não foi possível abrir o Edge ({type(direct_error).__name__} / {type(fallback_error).__name__}).','indisponivel')


async def close_pouso_browser(browser,process,profile):
    try:
        await browser.close()
    finally:
        try:
            if process and process.poll() is None:
                process.terminate()
                await asyncio.to_thread(process.wait,5)
        except Exception:
            if process and process.poll() is None:process.kill()
        try:
            if profile:profile.cleanup()
        except OSError:pass


def parse_pdf(content,cnpj):
    from pypdf import PdfReader
    if not isinstance(content,bytes) or not content.startswith(b'%PDF-') or len(content)>MAX_PDF:
        raise PortalError('O portal não entregou um PDF válido dentro do limite de tamanho.')
    try:
        reader=PdfReader(io.BytesIO(content))
        if not 1<=len(reader.pages)<=5:raise ValueError('Quantidade de páginas inesperada')
        text='\n'.join(page.extract_text() or '' for page in reader.pages)
    except Exception:
        raise PortalError('Não foi possível ler o PDF retornado por Pouso Alegre.')
    normalized=fold(text)
    normalized_space=re.sub(r'\s+',' ',normalized)
    compact=re.sub(r'[^A-Z0-9]','',text.upper())
    if cnpj not in compact:
        raise PortalError('O PDF retornado não corresponde ao CNPJ solicitado.')
    if ('municipio de pouso alegre' not in normalized_space or 'certidao negativa de debitos' not in normalized_space or
            'nao constam' not in normalized_space or 'pendencias' not in normalized_space):
        raise PortalError('O PDF não contém uma declaração negativa reconhecida de Pouso Alegre.')
    number=re.search(r'certidao negativa de debitos\s+([0-9]+/[0-9]{4})',normalized)
    name=re.search(r'Nome/Raz[aã]o:\s*[0-9]+\s*-\s*([^\r\n]+)',text,re.I)
    dates=re.search(r'DATA DE EMISS[AÃ]O\s+DATA DE VALIDADE\s*(\d{2}/\d{2}/\d{4})\s+(\d+)\s+dias',text,re.I)
    control=re.search(r'C[oó]digo para Valida[cç][aã]o da certid[aã]o:\s*([A-Z0-9-]+)',text,re.I)
    footer=re.search(r'Emitida [àa]s\s+(\d{2}:\d{2}:\d{2})\s+do dia\s+(\d{2}/\d{2}/\d{4})',text,re.I)
    if not all((number,name,dates,control,footer)):
        raise PortalError('Não foi possível identificar número, contribuinte, emissão, validade e controle no PDF.')
    try:
        issue_date=datetime.strptime(dates[1],'%d/%m/%Y').date()
        issued=datetime.strptime(footer[2]+' '+footer[1],'%d/%m/%Y %H:%M:%S')
        validity_days=int(dates[2])
    except (ValueError,OverflowError):
        raise PortalError('A certidão retornou uma data ou validade não reconhecida.')
    if issued.date()!=issue_date or not 1<=validity_days<=365:
        raise PortalError('As datas da certidão são inconsistentes.')
    return {'cnpj':cnpj,'name':name[1].strip(),'type':'Negativa','issuer':'Prefeitura Municipal de Pouso Alegre',
            'number':number[1],'control':control[1].upper(),'issued_at':issued.isoformat(),
            'valid_until':(issue_date+timedelta(days=validity_days)).isoformat(),'validity_days':validity_days}


def check_security_block(text):
    normalized=fold(text)
    if ('est-000549' in normalized or
            ('atividade incomum' in normalized and 'restrit' in normalized)):
        raise PortalError(
            'Pouso Alegre recusou o acesso na validação automática de segurança. '
            'A emissão não foi concluída. O portal orienta aguardar antes de tentar novamente. '
            'Se o aviso persistir também ao abrir o portal diretamente, contate o atendimento da prefeitura.',
            'bloqueado',text.strip())


async def wait_for_form(page,timeout=60,update=None):
    """Observa a mesma página; um aviso inicial não encerra a janela imediatamente."""
    deadline=time.monotonic()+timeout
    last_block=None
    last_notice=None
    while time.monotonic()<deadline:
        if page.is_closed():raise PortalError('A janela de Pouso Alegre foi fechada antes de concluir a consulta.')
        candidate=None
        blocked=False
        for frame in page.frames:
            if frame!=page.main_frame and '/embed/data/' not in frame.url:continue
            try:
                text=await frame.locator('body').inner_text(timeout=1000)
                check_security_block(text)
                field=frame.locator('select[name=opcaoEmissao]')
                if (await field.is_visible() and await field.is_enabled() and
                        not await frame.locator('.modal-mensagem-overlay:visible').count()):
                    candidate=frame
            except PortalError as error:
                last_block=error
                blocked=True
                if update and error.evidence!=last_notice:
                    update(status='consultando',
                           message=f'O portal exibiu um aviso de segurança. A janela continuará aberta até o fim da espera de {timeout:g} segundos pelo formulário.',
                           evidence=error.evidence)
                    last_notice=error.evidence
            except Exception:pass
        # Um formulário atrás de um aviso de bloqueio não significa acesso liberado.
        if candidate and not blocked:
            if update:update(status='consultando',message='Formulário liberado. Preenchendo os dados de Pouso Alegre…',evidence='')
            return candidate
        await asyncio.sleep(.4)
    if last_block:raise last_block
    raise PortalError('O formulário de Pouso Alegre não ficou disponível no prazo.','indisponivel')


async def wait_for_pdf(frame,future,timeout=50):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if future.done():return await future
        if frame.page.is_closed():raise PortalError('A janela de Pouso Alegre foi fechada antes de concluir a emissão.')
        try:
            text=await frame.locator('body').inner_text(timeout=1000)
            check_security_block(text)
            modal=frame.locator('.modal-mensagem-overlay:visible')
            if await modal.count():
                detail=(await modal.inner_text()).strip()
                if detail:raise PortalError('Pouso Alegre não concluiu a emissão. Confira o retorno do órgão abaixo.',evidence=detail)
        except PortalError:raise
        except Exception:pass
        await asyncio.sleep(.3)
    raise PortalError('Pouso Alegre não concluiu a emissão do PDF no prazo.','indisponivel')


async def consult_pouso_alegre(browser,cnpj,update=None):
    contexts=getattr(browser,'contexts',[])
    if contexts:
        context=contexts[0]
        page=context.pages[0] if context.pages and context.pages[0].url=='about:blank' else await context.new_page()
    else:
        page=await browser.new_page(locale='pt-BR')
        context=page.context
    page.set_default_timeout(15000)
    formatted=f'{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}'
    stage='acesso';submitted=False
    def progress(value,message):
        nonlocal stage
        stage=value
        if update:update(status='consultando',message=message)
    try:
        response=await page.goto(URL,wait_until='domcontentloaded',timeout=40000)
        if response and response.status>=400:
            text=await page.locator('body').inner_text(timeout=1000)
            check_security_block(text)
            raise PortalError(f'O portal respondeu HTTP {response.status}.',
                              'bloqueado' if response.status in (401,403,429) else 'indisponivel',
                              f'HTTP {response.status}')
        reject=page.get_by_role('button',name='Rejeitar não necessários',exact=True)
        try:
            if await reject.is_visible(timeout=800):await reject.click()
        except Exception:pass
        progress('formulario','Aguardando a validação automática de Pouso Alegre…')
        frame=await wait_for_form(page,update=update)
        await frame.locator('select[name=opcaoEmissao]').select_option(label='Por CPF/CNPJ')
        field=frame.locator('input[name=cpfCnpj]')
        await field.wait_for(state='visible')
        await field.fill(formatted)
        if re.sub(r'\D','',await field.input_value())!=cnpj:
            raise PortalError('Não foi possível preencher o CNPJ de forma confiável.')
        await frame.locator('select[name="FinalidadeCertidaoDebito.codigo"]').select_option(label='Certidão por Contribuinte')
        progress('emissao','Emitindo a certidão municipal de Pouso Alegre…')
        future=asyncio.get_running_loop().create_future()
        tasks=[]
        async def read_pdf(result):
            try:
                content=await result.body()
                if len(content)>MAX_PDF:raise PortalError('O PDF excedeu o tamanho esperado.')
                if not future.done():future.set_result(content)
            except Exception as error:
                if not future.done():future.set_exception(error)
        def response_seen(result):
            if (result.request.method=='POST' and result.url.startswith('https://'+HOST+'/') and
                    'application/pdf' in result.headers.get('content-type','').lower()):
                tasks.append(asyncio.create_task(read_pdf(result)))
        context.on('response',response_seen)
        try:
            await frame.get_by_role('button',name='Confirmar',exact=True).click()
            submitted=True
            content=await wait_for_pdf(frame,future)
        finally:
            context.remove_listener('response',response_seen)
            if tasks:await asyncio.gather(*tasks,return_exceptions=True)
            if not future.done():future.cancel()
        certificate=parse_pdf(content,cnpj)
        valid=datetime.fromisoformat(certificate['valid_until']).date()>=datetime.now().date()
        return {'status':'encontrada','message':'Certidão negativa municipal de Pouso Alegre obtida automaticamente. '+('Confira o PDF e a validade abaixo.' if valid else 'O documento retornado está vencido.'),
                'evidence':f"{certificate['name']}\nCNPJ: {formatted}\nTipo: Negativa\nNúmero: {certificate['number']}\nControle: {certificate['control']}\nEmissão: {datetime.fromisoformat(certificate['issued_at']).strftime('%d/%m/%Y %H:%M:%S')}\nVálida até: {datetime.fromisoformat(certificate['valid_until']).strftime('%d/%m/%Y')}",
                'submitted':True,'searched':True,'stage':'concluida','certificate':certificate,'_pdf':content}
    except Exception as error:
        status=error.status if isinstance(error,PortalError) else 'indisponivel'
        message=str(error) if isinstance(error,PortalError) else 'Não foi possível concluir esta etapa no portal de Pouso Alegre.'
        return {'status':status,'message':message,'evidence':getattr(error,'evidence',''),
                'diagnostic':f'Etapa: {stage}'+('' if isinstance(error,PortalError) else f' · {type(error).__name__}'),
                'submitted':submitted,'searched':submitted,'stage':stage}
    finally:
        if not page.is_closed():await page.close()
