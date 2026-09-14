"""Tentativa automatica da eCND estadual de SP para debitos nao inscritos."""
import io
import re
import tempfile
import time
import unicodedata
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

HOST = 'www10.fazenda.sp.gov.br'
URL = f'https://{HOST}/CertidaoNegativaDeb/Pages/EmissaoCertidaoNegativa.aspx'
MAX_PDF = 5 * 1024 * 1024
HUMAN_CAPTCHA_TIMEOUT = 180


class SPCndError(Exception):
    def __init__(self, message, status='manual', evidence=''):
        super().__init__(message)
        self.status = status
        self.evidence = evidence[:1800]


def outcome(status, message, evidence='', **extra):
    return {'status': status, 'message': message, 'evidence': evidence[:4000], **extra}


def fold(value):
    return ''.join(character for character in unicodedata.normalize('NFD', value.casefold())
                   if not unicodedata.combining(character))


def compact_cnpj(value):
    return re.sub(r'[^A-Z0-9]', '', value.upper())


def parse_date(value):
    try:
        return datetime.strptime(value, '%d/%m/%Y').date()
    except ValueError:
        raise SPCndError('A eCND estadual de SP contem uma data invalida.')


def parse_certificate_text(text, cnpj):
    """Confere identidade, orgao emissor, declaracao, numero e validade da eCND/SP."""
    normalized = re.sub(r'\s+', ' ', fold(text)).replace(chr(186), 'o').replace(chr(176), 'o').strip()
    if cnpj not in compact_cnpj(text):
        raise SPCndError('A eCND estadual de SP nao corresponde ao CNPJ solicitado.')
    if not any(term in normalized for term in (
            'secretaria da fazenda e planejamento do estado de sao paulo',
            'secretaria da fazenda do estado de sao paulo',
            'fazenda e planejamento')):
        raise SPCndError('O documento retornado nao foi identificado como certidao estadual de SP.')
    if 'certidao' not in normalized or not any(term in normalized for term in (
            'debitos tributarios', 'debitos nao inscritos', 'nao inscritos na divida ativa')):
        raise SPCndError('O documento retornado nao foi identificado como eCND estadual de SP.')
    if 'positiva com efeito' not in normalized and re.search(r'certifica-se\s+que\s+constam?\s+debitos?', normalized):
        raise SPCndError('A eCND estadual de SP retornou debitos e exige conferencia manual.')
    if not any(term in normalized for term in (
            'nao constam debitos', 'nada consta', 'certidao negativa',
            'positiva com efeito de negativa', 'positiva com efeitos de negativa')):
        raise SPCndError('A declaracao negativa da eCND estadual de SP nao foi reconhecida.')

    control = re.search(
        r'(?:(?:certidao)\s*(?:n(?:o|umero)?\.?|numero)|protocolo|controle)\s*[:o.\-]*\s*([a-z0-9./-]{5,})',
        normalized,
    )
    validity = re.search(r'(?:validade|valida\s+ate)\s*[:.\-]*\s*(\d{2}/\d{2}/\d{4})', normalized)
    issue = re.search(r'(?:data\s+de\s+)?(?:emissao|expedicao)\s*[:.\-]*\s*(\d{2}/\d{2}/\d{4})', normalized)
    if not control or not validity:
        raise SPCndError('Nao foi possivel identificar numero e validade da eCND estadual de SP.')

    valid_until = parse_date(validity[1])
    issued_at = parse_date(issue[1]) if issue else None
    if issued_at and issued_at > valid_until:
        raise SPCndError('A eCND estadual de SP contem um periodo de validade inconsistente.')
    if valid_until < date.today():
        raise SPCndError('A eCND estadual de SP retornada esta vencida.')

    kind = 'Certidao Negativa de Debitos Tributarios Nao Inscritos Estadual SP'
    if 'positiva com efeito' in normalized:
        kind = 'Certidao Positiva com Efeito de Negativa de Debitos Tributarios Estadual SP'
    return {
        'cnpj': cnpj,
        'type': kind,
        'control': control[1].upper(),
        'issued_at': issued_at.isoformat() if issued_at else '',
        'valid_until': valid_until.isoformat(),
        'issuer': 'Secretaria da Fazenda e Planejamento do Estado de Sao Paulo',
    }


def parse_sp_pdf(content, cnpj, expected_control=None):
    from pypdf import PdfReader
    if not content.startswith(b'%PDF-') or not 500 < len(content) <= MAX_PDF:
        raise SPCndError('A Sefaz/SP nao devolveu um PDF valido dentro do limite de tamanho.')
    try:
        reader = PdfReader(io.BytesIO(content))
        if not 1 <= len(reader.pages) <= 5:
            raise ValueError('Quantidade de paginas inesperada')
        text = '\n'.join(page.extract_text() or '' for page in reader.pages)
    except Exception as error:
        raise SPCndError(f'Nao foi possivel ler o PDF da eCND estadual de SP ({type(error).__name__}).')
    certificate = parse_certificate_text(text, cnpj)
    if expected_control and certificate['control'] != str(expected_control).upper():
        raise SPCndError('O PDF estadual de SP nao corresponde a certidao exibida pela Sefaz/SP.')
    return certificate


async def read_download_content(download):
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / 'cnd-estadual-sp.pdf'
        await download.save_as(str(target))
        return target.read_bytes()


def is_blocked_or_manual(text):
    normalized = fold(text)
    if any(term in normalized for term in (
            'captcha', 'codigo de seguranca', 'nao sou um robo', 'digite os caracteres')):
        return 'captcha'
    if any(term in normalized for term in (
            'login', 'senha', 'certificado digital', 'sipet', 'ecpf', 'ecnpj')):
        return 'login'
    if any(term in normalized for term in (
            'servico indisponivel', 'temporariamente indisponivel', 'tente novamente')):
        return 'indisponivel'
    return ''


def pending_result(text, submitted=False):
    status = is_blocked_or_manual(text) or 'manual'
    evidence = next((re.sub(r'\s+', ' ', line).strip() for line in text.splitlines()
                     if any(term in fold(line) for term in (
                         'captcha', 'codigo', 'login', 'senha', 'certificado',
                         'sipet', 'indisponivel', 'tente novamente'
                     ))), '')
    messages = {
        'captcha': 'A Sefaz/SP exige validacao humana antes de emitir a eCND estadual.',
        'login': 'A Sefaz/SP exige e-CNPJ, e-CPF ou SIPET para continuar esta emissao.',
        'indisponivel': 'A Sefaz/SP nao concluiu a consulta. Tente novamente mais tarde.',
        'manual': 'A consulta foi enviada, mas o retorno da Sefaz/SP nao permitiu confirmar a eCND automaticamente.',
    }
    return outcome(status, messages[status], evidence, submitted=submitted, searched=submitted, stage='resultado')


def captcha_wait_message():
    return ('A Sefaz/SP pediu validacao humana. Preencha o CAPTCHA na janela do Edge, '
            'clique em emitir/consultar e aguarde; a consulta continuara automaticamente.')


async def body_text(page):
    try:
        return await page.locator('body').inner_text(timeout=2000)
    except Exception:
        return ''


async def visible(locator, timeout=400):
    try:
        return await locator.count() > 0 and await locator.first.is_visible(timeout=timeout)
    except Exception:
        return False


async def find_cnpj_field(page):
    candidates = [
        page.get_by_label(re.compile('CNPJ|CPF/CNPJ', re.I)),
        page.locator('input[id*="cnpj" i], input[name*="cnpj" i], input[id*="cpf" i], input[name*="cpf" i]'),
        page.locator('input[id*="documento" i], input[name*="documento" i]'),
    ]
    for candidate in candidates:
        if await visible(candidate):
            return candidate.first
    raise SPCndError('O formulario da eCND estadual de SP nao ficou disponivel no prazo.', 'manual')


async def wait_for_captcha_to_clear(page, timeout=HUMAN_CAPTCHA_TIMEOUT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = await body_text(page)
        blocked = is_blocked_or_manual(text)
        if not blocked:
            return
        if blocked != 'captcha':
            result = pending_result(text)
            raise SPCndError(str(result['message']), result['status'], result['evidence'])
        await page.wait_for_timeout(500)
    raise SPCndError('O CAPTCHA da eCND estadual de SP nao foi concluido no Edge dentro de 3 minutos.',
                     'captcha', 'Aguardando validacao humana da Sefaz/SP.')


async def click_emit(page):
    pattern = re.compile('Emitir(?: certidao)?|Gerar(?: certidao)?|Consultar(?: certidao)?', re.I)
    candidates = [
        page.get_by_role('button', name=pattern),
        page.locator('button').filter(has_text=pattern),
        page.locator('input[value*="Emitir" i], input[value*="Consultar" i], input[value*="Gerar" i]'),
    ]
    for candidate in candidates:
        if await visible(candidate):
            await candidate.first.click()
            return True
    return False


async def wait_for_certificate(page, cnpj, downloads=None, responses=None, popups=None,
                               timeout=45, assisted=False, update=None):
    deadline = time.monotonic() + timeout
    downloads = downloads if downloads is not None else []
    responses = responses if responses is not None else []
    popups = popups if popups is not None else []
    pdf_errors = []
    captcha_seen = False
    captcha_evidence = None
    while time.monotonic() < deadline:
        while downloads:
            try:
                content = await read_download_content(downloads.pop(0))
                certificate = parse_sp_pdf(content, cnpj)
                return certificate, content
            except SPCndError as error:
                pdf_errors.append(str(error))
        while responses:
            try:
                content = await responses.pop(0).body()
                certificate = parse_sp_pdf(content, cnpj)
                return certificate, content
            except SPCndError as error:
                pdf_errors.append(str(error))
        pages = [page] + [popup for popup in list(popups) if not popup.is_closed()]
        for candidate in pages:
            text = await body_text(candidate)
            normalized = fold(text)
            if cnpj in compact_cnpj(text) and 'certidao' in normalized and (
                    'debitos tributarios' in normalized or 'nao inscritos' in normalized):
                certificate = parse_certificate_text(text, cnpj)
                await candidate.emulate_media(media='print')
                content = await candidate.pdf(format='A4', print_background=True)
                certificate = parse_sp_pdf(content, cnpj, certificate['control'])
                return certificate, content
            if is_blocked_or_manual(text):
                blocked = pending_result(text)
                if assisted and blocked['status'] == 'captcha':
                    evidence = blocked.get('evidence', '')
                    if update and (not captcha_seen or evidence != captcha_evidence):
                        update(status='aguardando_usuario', message=captcha_wait_message(),
                               evidence=evidence, submitted=True,
                               searched=False, stage='captcha')
                    captcha_seen = True
                    captcha_evidence = evidence
                else:
                    raise SPCndError(str(blocked['message']), blocked['status'], blocked['evidence'])
        await page.wait_for_timeout(500)
    if captcha_seen:
        raise SPCndError('O CAPTCHA da eCND estadual de SP nao foi concluido no Edge dentro de 3 minutos.',
                         'captcha', 'Aguardando validacao humana da Sefaz/SP.')
    raise SPCndError('A Sefaz/SP nao concluiu a emissao da eCND estadual no prazo.', 'indisponivel',
                     '; '.join(pdf_errors[-2:]))


async def consult_estadual_sp(browser, cnpj, assisted=False, update=None,
                              captcha_timeout=HUMAN_CAPTCHA_TIMEOUT):
    contexts = getattr(browser, 'contexts', [])
    if contexts:
        context = contexts[0]
        usable = [candidate for candidate in context.pages if candidate.url == 'about:blank']
        page = usable[0] if usable else await context.new_page()
    else:
        page = await browser.new_page(locale='pt-BR')
    page.set_default_timeout(15000)
    stage = 'acesso'
    submitted = False
    downloads = []
    responses = []
    popups = []

    def on_download(download):
        downloads.append(download)

    def on_response(response):
        content_type = response.headers.get('content-type', '').lower()
        hostname = urlsplit(response.url).hostname or ''
        expected_host = hostname == HOST or hostname.endswith('.fazenda.sp.gov.br')
        if expected_host and ('application/pdf' in content_type or response.url.lower().endswith('.pdf')):
            responses.append(response)

    def on_popup(popup):
        popups.append(popup)

    page.on('download', on_download)
    page.on('response', on_response)
    page.on('popup', on_popup)
    if getattr(page, 'context', None):
        page.context.on('response', on_response)

    def progress(message, **extra):
        if update:
            update(status='consultando', message=message, **extra)

    try:
        response = await page.goto(URL, wait_until='domcontentloaded', timeout=60000)
        if response and response.status >= 400:
            raise SPCndError(f'O portal estadual de SP respondeu HTTP {response.status}.',
                             'bloqueado' if response.status in (401, 403, 429) else 'indisponivel',
                             f'HTTP {response.status}')
        text = await body_text(page)
        field = None
        blocked_status = is_blocked_or_manual(text)
        if blocked_status:
            if blocked_status == 'captcha':
                try:
                    field = await find_cnpj_field(page)
                except SPCndError:
                    field = None
            if field is None:
                blocked = pending_result(text)
                if not (assisted and blocked['status'] == 'captcha'):
                    return blocked
                stage = 'captcha'
                if update:
                    update(status='aguardando_usuario', message=captcha_wait_message(),
                           evidence=blocked.get('evidence', ''), submitted=False,
                           searched=False, stage=stage)
                await wait_for_captcha_to_clear(page, captcha_timeout)
                progress('Validacao concluida. Preenchendo o CNPJ no portal estadual de SP...', evidence='')
        stage = 'formulario'
        progress('Preenchendo o CNPJ no portal estadual de SP...', evidence='')
        if field is None:
            field = await find_cnpj_field(page)
        await field.fill(cnpj)
        if cnpj not in compact_cnpj(await field.input_value()):
            raise SPCndError('Nao foi possivel preencher o CNPJ no portal estadual de SP.')
        submitted = await click_emit(page)
        if not submitted:
            raise SPCndError('Nao foi localizado o botao de emissao da eCND estadual de SP.')
        certificate, content = await wait_for_certificate(
            page, cnpj, downloads, responses, popups,
            timeout=captcha_timeout if assisted else 45, assisted=assisted, update=update
        )
        evidence = (
            f"{certificate['type']}\n"
            f"CNPJ: {cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}\n"
            f"Validade: {datetime.fromisoformat(certificate['valid_until']).strftime('%d/%m/%Y')}\n"
            f"Certidao: {certificate['control']}"
        )
        return outcome('encontrada',
                       'eCND estadual de SP obtida automaticamente. O PDF esta disponivel para download.',
                       evidence, submitted=True, searched=True, stage=stage,
                       certificate=certificate, _pdf=content)
    except SPCndError as error:
        return outcome(error.status, str(error), error.evidence,
                       submitted=submitted, searched=submitted, stage=stage)
    except Exception as error:
        reason = 'Tempo de resposta excedido.' if 'Timeout' in type(error).__name__ else 'Nao foi possivel concluir esta etapa da Sefaz/SP.'
        return outcome('indisponivel', reason + ' Nenhuma eCND estadual de SP foi confirmada.',
                       f'Etapa: {stage} - {type(error).__name__}',
                       submitted=submitted, searched=submitted, stage=stage)
    finally:
        if not page.is_closed():
            await page.close()
