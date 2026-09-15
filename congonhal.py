"""CND municipal de Congonhal pelo portal publico Prefeitura Moderna."""
import asyncio
import io
import logging
import re
import time
import unicodedata
from datetime import datetime

CITY='Congonhal'
HOST='congonhal-mg.prefeituramoderna.com.br'
URL=f'https://{HOST}/meuiptu/index.php#'
CERTIFICATE_URL=f'https://{HOST}/meuiptu/imprime_certidao.php?'
DTE_URL=f'https://{HOST}/dte/'
MAX_PDF=5*1024*1024


class PortalError(Exception):
    def __init__(self,message,status='manual',evidence=''):
        super().__init__(message)
        self.status=status
        self.evidence=evidence[:1800]


def fold(text):
    return ''.join(c for c in unicodedata.normalize('NFD',text.casefold()) if not unicodedata.combining(c))


def formatted_cnpj(cnpj):
    return f'{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}'


def compact(value):
    return re.sub(r'[^A-Z0-9]','',value.upper())


def only_digits(value):
    return re.sub(r'\D','',value or '')


def formatted_cpf(cpf):
    digits=only_digits(cpf)
    return f'{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:11]}'


def first_match(patterns,text,flags=re.I):
    for pattern in patterns:
        match=re.search(pattern,text,flags)
        if match:
            return match[1].strip()
    return ''


def parse_date(value):
    return datetime.strptime(value,'%d/%m/%Y').date()


def parse_pdf(content,cnpj):
    from pypdf import PdfReader
    if not isinstance(content,bytes) or not content.startswith(b'%PDF-') or len(content)>MAX_PDF:
        raise PortalError('O portal de Congonhal nao entregou um PDF valido dentro do limite de tamanho.')
    try:
        reader=PdfReader(io.BytesIO(content))
        if not 1<=len(reader.pages)<=5:
            raise ValueError('Quantidade de paginas inesperada')
        text='\n'.join(page.extract_text() or '' for page in reader.pages)
    except Exception:
        raise PortalError('Nao foi possivel ler o PDF retornado por Congonhal.')
    normalized=fold(text)
    normalized_space=re.sub(r'\s+',' ',normalized)
    text_compact=compact(text)
    if cnpj not in text_compact:
        raise PortalError('O PDF retornado nao corresponde ao CNPJ solicitado.')
    if 'congonhal' not in normalized_space or 'certidao' not in normalized_space:
        raise PortalError('Nao foi possivel identificar Congonhal e o tipo de certidao no PDF.')
    if 'positiva' in normalized_space and 'efeito' not in normalized_space:
        raise PortalError('O PDF retornou uma certidao positiva, nao uma CND municipal.')
    negative=(
        'certidao negativa' in normalized_space or
        'positiva com efeito' in normalized_space or
        'nao constam' in normalized_space or
        'nada consta' in normalized_space or
        'inexistencia de debitos' in normalized_space or
        'sem debitos' in normalized_space
    )
    if not negative or any(term in normalized_space for term in ['constam debitos','existem debitos','possui debitos em aberto']):
        raise PortalError('O PDF nao contem uma declaracao negativa reconhecida de Congonhal.')
    name=first_match([
        r'Nome/Raz[aã]o(?: Social)?:\s*(?:[0-9]+\s*-\s*)?([^\r\n]+)',
        r'Raz[aã]o Social:\s*([^\r\n]+)',
        r'Contribuinte:\s*(?:[0-9]+\s*-\s*)?([^\r\n]+)',
        r'Nome:\s*([^\r\n]+)',
    ],text)
    number=first_match([
        r'Certid[aã]o(?: Negativa)?(?: de D[eé]bitos)?\s*(?:n[ºo.]*|numero)?\s*[:\-]?\s*([0-9]+/[0-9]{4})',
        r'N[úu]mero(?: da Certid[aã]o)?\s*[:\-]\s*([A-Z0-9./-]{3,})',
    ],text)
    control=first_match([
        r'C[oó]digo(?: para)? Valida[cç][aã]o(?: da certid[aã]o)?\s*[:\-]?\s*([A-Z0-9.-]{6,})',
        r'C[oó]digo de Controle\s*[:\-]?\s*([A-Z0-9.-]{6,})',
        r'Chave de Autenticidade\s*[:\-]?\s*([A-Z0-9.-]{6,})',
        r'Controle\s*[:\-]?\s*([A-Z0-9.-]{6,})',
    ],text)
    dates=re.findall(r'\b\d{2}/\d{2}/\d{4}\b',text)
    issued_text=first_match([
        r'(?:Data\s+de\s+)?Emiss[aã]o\s*[:\-]?\s*(\d{2}/\d{2}/\d{4})',
        r'Emitida(?:\s+em|:)?\s*(\d{2}/\d{2}/\d{4})',
    ],text)
    expires_text=first_match([
        r'(?:Data\s+de\s+)?Validade\s*[:\-]?\s*(\d{2}/\d{2}/\d{4})',
        r'V[aá]lid[ao]?\s+at[eé]\s*[:\-]?\s*(\d{2}/\d{2}/\d{4})',
    ],text)
    if not issued_text and dates:
        issued_text=dates[0]
    if not expires_text and len(dates)>1:
        expires_text=dates[1]
    if not name or not (number or control) or not issued_text or not expires_text:
        raise PortalError('Nao foi possivel identificar contribuinte, numero/controle, emissao e validade no PDF.')
    try:
        issued_date=parse_date(issued_text)
        expires=parse_date(expires_text)
    except ValueError:
        raise PortalError('A certidao retornou uma data nao reconhecida.')
    time_match=re.search(r'(?:Emitida|Emiss[aã]o).*?(\d{2}:\d{2}(?::\d{2})?)',text,re.I|re.S)
    issued_time=time_match[1] if time_match else '00:00:00'
    if len(issued_time)==5:
        issued_time+=':00'
    try:
        issued=datetime.strptime(f'{issued_date:%d/%m/%Y} {issued_time}','%d/%m/%Y %H:%M:%S')
    except ValueError:
        raise PortalError('A certidao retornou um horario de emissao nao reconhecido.')
    if expires<issued.date():
        raise PortalError('As datas da certidao de Congonhal sao inconsistentes.')
    cert_type='Positiva com efeito de negativa' if 'positiva com efeito' in normalized_space else 'Negativa'
    return {'cnpj':cnpj,'name':name,'type':cert_type,'issuer':'Prefeitura Municipal de Congonhal',
            'number':number,'control':(control or number).upper(),'issued_at':issued.isoformat(),
            'valid_until':expires.isoformat()}


def check_portal_block(text):
    normalized=fold(text)
    if any(term in normalized for term in ['atividade incomum','acesso restrito','acesso bloqueado','est-000549']):
        raise PortalError('Congonhal recusou o acesso automatizado nesta tentativa.', 'bloqueado', text.strip())
    if any(term in normalized for term in ['captcha','nao sou um robo','codigo de seguranca']):
        raise PortalError('O portal de Congonhal exigiu validacao humana antes de continuar.','captcha',text.strip())


async def body_text(page,timeout=1000):
    try:
        text=await page.locator('body').inner_text(timeout=timeout)
        check_portal_block(text)
        return text
    except PortalError:
        raise
    except Exception:
        return ''


async def wait_for_text(page,pattern,timeout=20):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        text=await body_text(page)
        if re.search(pattern,text,re.I):
            return text
        if await page.locator('input[type=password]:visible').count():
            raise PortalError('O portal de Congonhal passou a exigir login.','login')
        await asyncio.sleep(.3)
    raise PortalError('O portal de Congonhal nao concluiu esta etapa no prazo.','indisponivel')


def is_certificate_issue_page(text):
    normalized=fold(text)
    return (
        'emitir certidao de debito' in normalized and
        'cpf/cnpj da certidao' in normalized and
        'nome do requerente' in normalized
    )


async def wait_for_certificate_issue_page(page,timeout=20):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        text=await body_text(page)
        if is_certificate_issue_page(text):
            return text
        await asyncio.sleep(.3)
    raise PortalError('Nao foi possivel abrir a tela de emissao de certidao de debito de Congonhal.','indisponivel')


async def click_first(page,selectors,names=(),timeout=10):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        for selector in selectors:
            locator=page.locator(selector).first
            try:
                if await locator.is_visible(timeout=300) and await locator.is_enabled(timeout=300):
                    await locator.click()
                    return
            except Exception:
                pass
        for name in names:
            try:
                button=page.get_by_role('button',name=re.compile(name,re.I)).first
                if await button.is_visible(timeout=300) and await button.is_enabled(timeout=300):
                    await button.click()
                    return
            except Exception:
                pass
            try:
                link=page.get_by_role('link',name=re.compile(name,re.I)).first
                if await link.is_visible(timeout=300):
                    await link.click()
                    return
            except Exception:
                pass
            try:
                text=page.get_by_text(re.compile(name,re.I)).first
                if await text.is_visible(timeout=300):
                    await text.click()
                    return
            except Exception:
                pass
        await asyncio.sleep(.2)
    raise PortalError('Nao foi possivel acionar o comando esperado no portal de Congonhal.','indisponivel')


async def click_visible_text(page,texts,timeout=10,prefer_menu=True,required=True):
    targets=list(texts)
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        clicked=await page.evaluate("""({targets, preferMenu}) => {
            const normalize = value => String(value || '')
                .normalize('NFD').replace(/[\\u0300-\\u036f]/g, '')
                .replace(/\\s+/g, ' ').trim().toLowerCase();
            const wanted = targets.map(normalize);
            const selectors = 'a,button,[role="button"],[role="link"],li,span,div';
            const visible = element => {
                const style = getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
            };
            const candidates = [...document.querySelectorAll(selectors)]
                .filter(visible)
                .map(element => {
                    const text = normalize(element.innerText || element.textContent || '');
                    if (!wanted.includes(text)) return null;
                    const menu = !!element.closest('aside,nav,.sidebar,.menu,.menu-sidebar,.sidebar-menu,[class*="side"],[class*="menu"]');
                    const interactive = element.matches('a,button,[role="button"],[role="link"]');
                    const clickable = element.hasAttribute('onclick') || getComputedStyle(element).cursor === 'pointer';
                    let depth = 0;
                    for (let parent = element.parentElement; parent; parent = parent.parentElement) depth++;
                    return {element, score: (menu && preferMenu ? 10 : 0) + (interactive ? 8 : 0) + (clickable ? 6 : 0) + depth / 100 - text.length / 1000};
                })
                .filter(Boolean)
                .sort((a,b) => b.score - a.score);
            if (!candidates.length) return false;
            candidates[0].element.click();
            return true;
        }""", {'targets':targets,'preferMenu':prefer_menu})
        if clicked:
            return True
        await asyncio.sleep(.2)
    if required:
        raise PortalError('Nao foi possivel clicar no item de menu de emissao de certidao de Congonhal.','indisponivel')
    return False


async def click_exact_text(page,texts,timeout=3000,prefer_menu=True):
    scopes=('aside,nav,.sidebar,.menu,.menu-sidebar,.sidebar-menu,[class*="side"],[class*="menu"]','body') if prefer_menu else ('body',)
    for text in texts:
        for scope in scopes:
            try:
                await page.locator(scope).get_by_text(text,exact=True).first.click(timeout=timeout)
                return True
            except Exception:
                pass
    return False


async def click_emission_menu(page,timeout=8):
    opened=await click_exact_text(page,('Emissao de Certidao','Emissão de Certidão'),timeout=2500,prefer_menu=True)
    if not opened:
        await click_exact_text(page,('Servicos','Serviços'),timeout=2500,prefer_menu=True)
        opened=await click_exact_text(page,('Emissao de Certidao','Emissão de Certidão'),timeout=timeout*1000,prefer_menu=True)
    if not opened:
        opened=await click_visible_text(page,('Emissao de Certidao','Emissão de Certidão'),timeout=timeout,prefer_menu=True,required=False)
    if not opened:
        raise PortalError('Nao foi possivel clicar no item Emissao de Certidao no menu lateral de Congonhal.','indisponivel')


async def open_certificate_issue_page(page):
    if is_certificate_issue_page(await body_text(page)):
        return page
    await click_emission_menu(page)
    await wait_for_certificate_issue_page(page)
    return page


async def submit_certificate_form(page):
    popup=None
    try:
        async with page.expect_popup(timeout=15000) as popup_info:
            await click_first(page,['input[type=submit][value*="Emitir" i]:visible','button[type=submit]:visible'],
                              names=('Emitir a Certidao','Emitir a Certidão','Emitir','Gerar','Confirmar','Solicitar'))
        popup=await popup_info.value
        await popup.wait_for_load_state('domcontentloaded',timeout=35000)
    except Exception:
        if popup and not popup.is_closed():
            return popup
        popup=None
    return popup or page


async def click_print_if_available(page):
    clicked=False
    try:
        async with page.expect_download(timeout=3000) as download_info:
            await click_first(page,['input[type=button][value*="Imprimir" i]:visible','button:has-text("Imprimir"):visible','a:has-text("Imprimir"):visible'],
                              names=('Imprimir','Imprimir Certidao','Imprimir Certidão'),timeout=6)
            clicked=True
        return clicked,await download_info.value
    except PortalError:
        return False,None
    except Exception:
        return clicked,None


async def read_download_pdf(download):
    try:
        failure=await download.failure()
        if failure:
            raise PortalError(f'O download da certidao falhou: {failure}.','indisponivel')
        path=await download.path()
        def load():
            with open(path,'rb') as handle:
                return handle.read(MAX_PDF+1)
        content=await asyncio.to_thread(load)
        if content and content.startswith(b'%PDF-') and len(content)<=MAX_PDF:
            return content
    except PortalError:
        raise
    except Exception:
        pass
    raise PortalError('Congonhal nao entregou um download PDF valido da certidao.','indisponivel')


async def field_metadata(field):
    try:
        return await field.evaluate("""element => {
            const labels=[...document.querySelectorAll('label')].filter(label =>
                label.control===element || (element.id && label.getAttribute('for')===element.id) || label.contains(element)
            ).map(label => label.innerText || label.textContent || '');
            return [
                element.name || '', element.id || '', element.placeholder || '',
                element.getAttribute('aria-label') || '', element.getAttribute('title') || '',
                ...labels
            ].join(' ');
        }""")
    except Exception:
        return ''


async def fill_field_by_keywords(page,value,keywords,avoid=(),required=True,digits=None,allow_fallback=True):
    keywords=tuple(fold(item) for item in keywords)
    avoid=tuple(fold(item) for item in avoid)
    fields=page.locator('input:visible, textarea:visible')
    fallback=None
    for index in range(min(await fields.count(),12)):
        field=fields.nth(index)
        try:
            if not await field.is_visible(timeout=300) or not await field.is_enabled(timeout=300):
                continue
            meta=fold(await field_metadata(field))
            if not meta:
                continue
            if any(term in meta for term in avoid):
                continue
            if any(term in meta for term in keywords):
                await field.fill(value)
                current=await field.input_value()
                if digits and digits not in only_digits(current):
                    await field.fill(digits)
                    current=await field.input_value()
                if not digits or digits in only_digits(current):
                    return True
            if allow_fallback and fallback is None and not await field.input_value():
                fallback=field
        except Exception:
            pass
    if fallback and not required:
        return False
    if fallback and required:
        try:
            await fallback.fill(value)
            current=await fallback.input_value()
            if not digits or digits in only_digits(current):
                return True
        except Exception:
            pass
    if required:
        raise PortalError('Nao foi possivel preencher um campo obrigatorio no portal de Congonhal.','indisponivel')
    return False


async def fill_field_by_selectors(page,selectors,value,digits=None):
    for selector in selectors:
        field=page.locator(selector).first
        try:
            if not await field.is_visible(timeout=300) or not await field.is_enabled(timeout=300):
                continue
            await field.fill(value)
            current=await field.input_value()
            if digits and digits not in only_digits(current):
                await field.fill(digits)
                current=await field.input_value()
            if (digits and digits in only_digits(current)) or (not digits and current==value):
                return True
        except Exception:
            pass
    return False


async def fill_certificate_cnpj(page,cnpj):
    filled=await fill_field_by_selectors(
        page,
        ('#nrcpfcnpj','input[name="nrcpfcnpj"]'),
        formatted_cnpj(cnpj),
        digits=cnpj)
    if not filled:
        filled=await fill_field_by_keywords(
            page,formatted_cnpj(cnpj),
            keywords=('cpf/cnpj da certidao','cpf/cnpj da certidão','cpf cnpj da certidao','cnpj da certidao'),
            avoid=('usuario','solicitante','requerente','nome','numero do cpf','número do cpf','nº de cpf'),
            required=False,
            digits=cnpj,
            allow_fallback=False)
    if not filled:
        raise PortalError('Nao foi possivel preencher o CPF/CNPJ da certidao no portal de Congonhal.','indisponivel')


async def fill_requester(page,requester,required):
    name=(requester or {}).get('nome_usuario','')
    cpf=(requester or {}).get('cpf_usuario','')
    name_filled=await fill_field_by_selectors(
        page,
        ('#nmrequerente','input[name="nmrequerente"]'),
        name)
    if not name_filled:
        await fill_field_by_keywords(
            page,name,
            keywords=('nome do requerente','nome do usuario','nome do usuário','usuario','usuário','solicitante','requerente','nome'),
            avoid=('razao','razão','empresa','cnpj','cpf/cnpj','certidao','certidão'),
            required=required,
            allow_fallback=False)
    cpf_filled=await fill_field_by_selectors(
        page,
        ('#nrdocumento','input[name="nrdocumento"]'),
        formatted_cpf(cpf),
        digits=only_digits(cpf))
    if not cpf_filled:
        await fill_field_by_keywords(
            page,formatted_cpf(cpf),
            keywords=('numero do cpf','número do cpf','nº de cpf','cpf do requerente','cpf requerente','cpf do usuario','cpf do usuário','cpf usuario','cpf usuário','cpf solicitante'),
            avoid=('cnpj','cpf/cnpj','cpf cnpj','empresa','certidao','certidão'),
            required=required,
            digits=only_digits(cpf),
            allow_fallback=False)


async def fill_purpose(page,required=True):
    if await fill_field_by_selectors(
            page,
            ('#finalidade','input[name="finalidade"],textarea[name="finalidade"]'),
            'Emissao de certidao de debito'):
        return True
    fields=page.locator('select:visible, input:visible, textarea:visible')
    for index in range(min(await fields.count(),12)):
        field=fields.nth(index)
        try:
            meta=fold(await field_metadata(field))
            if 'finalidade' not in meta:
                continue
            tag=await field.evaluate('element => element.tagName.toLowerCase()')
            if tag=='select':
                options=await field.locator('option').evaluate_all("""items => items.map(option => ({
                    text: option.textContent || '',
                    value: option.value || '',
                    disabled: option.disabled
                }))""")
                candidates=[option for option in options if not option['disabled'] and fold(option['text']).strip() and 'selecione' not in fold(option['text'])]
                if not candidates:
                    if required:
                        raise PortalError('Nao foi possivel selecionar a finalidade da certidao de Congonhal.','indisponivel')
                    return False
                choice=next((option for option in candidates if any(term in fold(option['text']+' '+option['value']) for term in ('certidao','debito','regularidade'))),candidates[0])
                if choice['value']:
                    await field.select_option(value=choice['value'])
                else:
                    await field.select_option(label=choice['text'])
                return True
            if not await field.input_value():
                await field.fill('Emissao de certidao de debito')
            return True
        except Exception:
            pass
    if required:
        raise PortalError('Nao foi possivel preencher a finalidade da certidao de Congonhal.','indisponivel')
    return False


async def choose_certificate_options(page):
    selects=page.locator('select:visible')
    for index in range(min(await selects.count(),6)):
        select=selects.nth(index)
        try:
            options=await select.locator('option').evaluate_all(
                '(items) => items.map(option => ({text: option.textContent || "", value: option.value}))')
            for label in ('Certidao Negativa','Certidão Negativa','Certidao por Contribuinte','Contribuinte','CPF/CNPJ'):
                found=next((option for option in options if fold(label) in fold(option['text'])),None)
                if found:
                    await select.select_option(value=found['value'])
                    break
        except Exception:
            pass


async def wait_for_pdf(page,future,timeout=45):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if future.done():
            return await future
        text=await body_text(page)
        if any(term in fold(text) for term in ['nao possui cadastro','nao encontrado','nenhum contribuinte','sem cadastro']):
            raise PortalError('Congonhal nao localizou cadastro municipal para o CNPJ informado.','sem_certidao',text)
        if any(term in fold(text) for term in ['possui debitos','debitos em aberto','certidao positiva']):
            raise PortalError('Congonhal retornou pendencias no cadastro municipal.','manual',text)
        await asyncio.sleep(.3)
    raise PortalError('Congonhal nao concluiu a emissao do PDF no prazo.','indisponivel')


async def consult_congonhal(browser,cnpj,update=None,requester=None):
    requester=requester or {}
    if not requester.get('nome_usuario') or not requester.get('cpf_usuario'):
        raise PortalError('Informe nome e CPF do usuario para emitir a CND municipal de Congonhal.','manual')
    page=await browser.new_page(locale='pt-BR')
    root_page=page
    page.set_default_timeout(15000)
    page.set_default_navigation_timeout(40000)
    stage='acesso'
    submitted=False
    def progress(value,message):
        nonlocal stage
        stage=value
        if update:
            update(status='consultando',message=message)
    try:
        response=await page.goto(URL,wait_until='domcontentloaded',timeout=35000)
        if response and response.status>=400:
            raise PortalError(f'O portal respondeu HTTP {response.status}.',
                              'bloqueado' if response.status in (401,403,429) else 'indisponivel',
                              f'HTTP {response.status}')
        await wait_for_text(page,r'CPF|CNPJ|Certid')
        progress('certidao','Abrindo a emissao de certidao de debito de Congonhal...')
        page=await open_certificate_issue_page(page)
        page.set_default_timeout(15000)
        page.set_default_navigation_timeout(40000)
        if root_page is not page and not root_page.is_closed():
            await root_page.close()
        progress('identificacao','Preenchendo os dados da certidao de Congonhal...')
        await fill_certificate_cnpj(page,cnpj)
        await choose_certificate_options(page)
        await fill_requester(page,requester,required=True)
        await fill_purpose(page,required=True)
        loop=asyncio.get_running_loop()
        future=loop.create_future()
        tasks=[]
        async def read_pdf(result):
            try:
                content=await result.body()
                if len(content)>MAX_PDF:
                    raise PortalError('O PDF excedeu o tamanho esperado.')
                if not future.done():
                    future.set_result(content)
            except Exception as error:
                if not future.done():
                    future.set_exception(error)
        def response_seen(result):
            content_type=result.headers.get('content-type','').lower()
            disposition=result.headers.get('content-disposition','').lower()
            if result.url.startswith(f'https://{HOST}/') and ('application/pdf' in content_type or '.pdf' in disposition):
                tasks.append(asyncio.create_task(read_pdf(result)))
        page.context.on('response',response_seen)
        try:
            progress('emissao','Emitindo a CND municipal de Congonhal...')
            result_page=await submit_certificate_form(page)
            submitted=True
            if result_page is not page:
                page=result_page
            printed,download=await click_print_if_available(page)
            if download:
                try:
                    content=await read_download_pdf(download)
                except PortalError:
                    content=await wait_for_pdf(page,future,timeout=12 if printed else 45)
            else:
                content=await wait_for_pdf(page,future,timeout=12 if printed else 45)
        finally:
            page.context.remove_listener('response',response_seen)
            if tasks:
                await asyncio.gather(*tasks,return_exceptions=True)
            if not future.done():
                future.cancel()
        certificate=parse_pdf(content,cnpj)
        valid=datetime.fromisoformat(certificate['valid_until']).date()>=datetime.now().date()
        return {'status':'encontrada','message':'CND municipal de Congonhal obtida automaticamente. '+('Confira o PDF e a validade abaixo.' if valid else 'O documento retornado esta vencido.'),
                'evidence':f"{certificate['name']}\nCNPJ: {formatted_cnpj(cnpj)}\nTipo: {certificate['type']}\nNumero: {certificate['number'] or certificate['control']}\nControle: {certificate['control']}\nEmissao: {datetime.fromisoformat(certificate['issued_at']).strftime('%d/%m/%Y %H:%M:%S')}\nValida ate: {datetime.fromisoformat(certificate['valid_until']).strftime('%d/%m/%Y')}",
                'submitted':True,'searched':True,'stage':'concluida','certificate':certificate,'_pdf':content}
    except Exception as error:
        if not isinstance(error,PortalError):
            logging.getLogger(__name__).warning('Consulta Congonhal: etapa=%s, %s: %s',stage,type(error).__name__,str(error).splitlines()[0][:240])
        status=error.status if isinstance(error,PortalError) else 'indisponivel'
        message=str(error) if isinstance(error,PortalError) else 'Nao foi possivel concluir esta etapa no portal de Congonhal.'
        return {'status':status,'message':message,'evidence':getattr(error,'evidence',''),
                'diagnostic':f'Etapa: {stage}'+('' if isinstance(error,PortalError) else f' · {type(error).__name__}'),
                'submitted':submitted,'searched':submitted and stage in ('emissao','concluida'),'stage':stage}
    finally:
        if not page.is_closed():
            await page.close()
        if root_page is not page and not root_page.is_closed():
            await root_page.close()
