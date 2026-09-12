"""Consulta e impressão do Certificado de Regularidade do FGTS no portal público da Caixa."""
import io
import re
import time
import unicodedata
from datetime import datetime
from urllib.parse import urlsplit

HOST = 'consulta-crf.caixa.gov.br'
URL = f'https://{HOST}/consultacrf/pages/consultaEmpregador.jsf'
MAX_PDF = 4 * 1024 * 1024


class FGTSError(Exception):
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


def parse_certificate_text(text, cnpj):
    """Confere identidade, declaração de regularidade, validade e número do CRF."""
    normalized = re.sub(r'\s+', ' ', fold(text)).strip()
    if cnpj not in compact_cnpj(text):
        raise FGTSError('O certificado do FGTS não corresponde ao CNPJ solicitado.')
    if 'certificado de regularidade do fgts' not in normalized:
        raise FGTSError('O documento retornado não foi identificado como CRF do FGTS.')
    if any(term in normalized for term in ('nao esta regular', 'nao se encontra regular')):
        raise FGTSError('O documento não contém uma declaração positiva de regularidade do FGTS.')
    if not all(term in normalized for term in (
            'empresa acima identificada', 'regular perante o fundo de garantia', 'fgts')):
        raise FGTSError('A declaração de regularidade não foi reconhecida no certificado do FGTS.')

    validity = re.search(r'validade:\s*(\d{2}/\d{2}/\d{4})\s+a\s+(\d{2}/\d{2}/\d{4})', normalized)
    number = re.search(r'certifica(?:do|cao)\s+n.{0,3}mero:\s*(\d{18,30})', normalized)
    name = re.search(r'ra.{0,3}o social:\s*(.+?)\s+endere.{0,3}o:', normalized)
    if not all((validity, number, name)):
        raise FGTSError('Não foi possível identificar razão social, validade e número do CRF.')
    try:
        valid_from = datetime.strptime(validity[1], '%d/%m/%Y').date()
        valid_until = datetime.strptime(validity[2], '%d/%m/%Y').date()
    except ValueError:
        raise FGTSError('O certificado do FGTS contém uma data inválida.')
    if valid_from > valid_until:
        raise FGTSError('O certificado do FGTS contém um período de validade inconsistente.')
    return {
        'cnpj': cnpj,
        'name': name[1].strip().upper(),
        'type': 'Certificado de Regularidade do FGTS',
        'control': number[1],
        'valid_from': valid_from.isoformat(),
        'valid_until': valid_until.isoformat(),
        'issuer': 'Caixa Econômica Federal',
    }


def parse_crf_pdf(content, cnpj, expected_control=None):
    from pypdf import PdfReader
    if not content.startswith(b'%PDF-') or not 500 < len(content) <= MAX_PDF:
        raise FGTSError('A Caixa não devolveu um PDF válido dentro do limite de tamanho.')
    try:
        reader = PdfReader(io.BytesIO(content))
        if not 1 <= len(reader.pages) <= 5:
            raise ValueError('Quantidade de páginas inesperada')
        text = '\n'.join(page.extract_text() or '' for page in reader.pages)
    except Exception as error:
        raise FGTSError(f'Não foi possível ler o PDF do FGTS ({type(error).__name__}).')
    certificate = parse_certificate_text(text, cnpj)
    if expected_control and certificate['control'] != str(expected_control):
        raise FGTSError('O PDF do FGTS não corresponde ao certificado exibido pela Caixa.')
    return certificate


def security_evidence(text):
    lines = [re.sub(r'\s+', ' ', line).strip() for line in text.splitlines() if line.strip()]
    selected = [line for line in lines if any(term in fold(line) for term in (
        'comportamento malicioso', 'nao podemos processar', 'incident id', 'acesso bloqueado'
    ))]
    return '\n'.join(selected[:4])[:1800]


def is_security_block(text, url):
    normalized = fold(text)
    host = urlsplit(url).hostname or ''
    return host.endswith('perfdrive.com') or any(term in normalized for term in (
        'comportamento malicioso', 'nao podemos processar sua requisicao', 'shieldsquare block'
    ))


async def body_text(page):
    try:
        return await page.locator('body').inner_text(timeout=2000)
    except Exception:
        return ''


async def wait_for_form(page, assisted=False, update=None, timeout=40):
    deadline = time.monotonic() + timeout
    block = ''
    announced = False
    field = page.locator('#mainForm\\:txtInscricao1')
    while time.monotonic() < deadline:
        if await field.is_visible(timeout=400):
            if announced and update:
                update(status='consultando', message='Acesso liberado. Consultando o CRF na Caixa…', evidence='')
            return field
        text = await body_text(page)
        if is_security_block(text, page.url):
            block = security_evidence(text) or 'A Caixa redirecionou o acesso para a proteção antifraude.'
            if assisted and update and not announced:
                update(status='aguardando_usuario', message=(
                    'A Caixa está validando o acesso. Aguarde a liberação no Edge; '
                    'se necessário, atualize a página uma vez.'), evidence=block)
                announced = True
        await page.wait_for_timeout(400)
    if block:
        raise FGTSError('A proteção antifraude da Caixa bloqueou esta tentativa. Nenhum CRF foi confirmado.',
                        'bloqueado', block)
    raise FGTSError('O formulário público do FGTS não ficou disponível no prazo.', 'indisponivel')


async def wait_for_search_result(page, cnpj, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = await body_text(page)
        normalized = fold(text)
        if is_security_block(text, page.url):
            raise FGTSError('A proteção antifraude da Caixa interrompeu a consulta. Nenhum CRF foi confirmado.',
                            'bloqueado', security_evidence(text))
        negative = any(term in normalized for term in ('nao localizado', 'inscricao invalida'))
        if (('situacao de regularidade do empregador' in normalized and
                (cnpj in compact_cnpj(text) or negative)) or negative):
            return text
        await page.wait_for_timeout(300)
    raise FGTSError('A Caixa não concluiu a pesquisa do CNPJ no prazo.', 'indisponivel')


def unavailable_result(text, submitted=True):
    normalized = fold(text)
    negative = any(term in normalized for term in (
        'nao esta regular', 'nao se encontra regular', 'nao foi localizado', 'nao localizado',
        'inscricao invalida', 'nao possui certificado', 'nao possui crf'
    ))
    evidence = next((re.sub(r'\s+', ' ', line).strip() for line in text.splitlines()
                     if any(term in fold(line) for term in ('nao ', 'regular', 'localiz', 'inscricao'))), '')
    if negative:
        return outcome('sem_certidao',
                       'A Caixa não disponibilizou um CRF para este CNPJ nesta consulta. Isso não comprova dívida ou irregularidade.',
                       evidence, submitted=submitted, searched=True, stage='resultado')
    return outcome('manual',
                   'A pesquisa foi enviada, mas o retorno da Caixa não permitiu confirmar um CRF.',
                   evidence, submitted=submitted, searched=True, stage='resultado')


async def consult_fgts(browser, cnpj, assisted=False, update=None):
    contexts = getattr(browser, 'contexts', [])
    if contexts:
        context = contexts[0]
        usable = [candidate for candidate in context.pages if candidate.url == 'about:blank']
        page = usable[0] if usable else await context.new_page()
    else:
        page = await browser.new_page(locale='pt-BR')
    page.set_default_timeout(15000)
    stage = 'acesso'
    submitted = searched = False

    def progress(message, **extra):
        if update:
            update(status='consultando', message=message, **extra)

    try:
        response = await page.goto(URL, wait_until='domcontentloaded', timeout=60000)
        if response and response.status >= 400:
            raise FGTSError(f'O portal do FGTS respondeu HTTP {response.status}.',
                            'bloqueado' if response.status in (401, 403, 429) else 'indisponivel',
                            f'HTTP {response.status}')
        field = await wait_for_form(page, assisted, update)
        stage = 'pesquisa'
        progress('Consultando a regularidade do FGTS na Caixa…', evidence='')
        await page.locator('#mainForm\\:tipoEstabelecimento').select_option('1')
        await page.locator('#mainForm\\:uf').select_option('')
        await field.fill(cnpj)
        if compact_cnpj(await field.input_value()) != cnpj:
            raise FGTSError('Não foi possível preencher o CNPJ no portal do FGTS.')
        await page.locator('#mainForm\\:btnConsultar').click()
        submitted = searched = True
        result_text = await wait_for_search_result(page, cnpj)
        if cnpj not in compact_cnpj(result_text):
            negative = unavailable_result(result_text)
            if negative['status'] == 'sem_certidao':
                return negative
            raise FGTSError('A Caixa devolveu um resultado sem confirmar o CNPJ pesquisado.')
        normalized = fold(result_text)
        if any(term in normalized for term in ('nao esta regular', 'nao se encontra regular')):
            return unavailable_result(result_text)
        if not ('empresa abaixo identificada' in normalized and 'esta regular no fgts' in normalized):
            return unavailable_result(result_text)

        stage = 'certificado'
        progress('Regularidade confirmada. Preparando o CRF em PDF…')
        link = page.locator('a').filter(has_text=re.compile('Certificado de Regularidade do FGTS', re.I)).first
        await link.click()
        await page.locator('#mainForm\\:btnVisualizar').wait_for(state='visible', timeout=30000)
        certificate_text = await body_text(page)
        certificate = parse_certificate_text(certificate_text, cnpj)
        await page.emulate_media(media='print')
        content = await page.pdf(format='A4', print_background=True)
        certificate = parse_crf_pdf(content, cnpj, certificate['control'])
        evidence = (
            f"{certificate['name']}\n"
            f"CNPJ: {cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}\n"
            f"Validade: {datetime.fromisoformat(certificate['valid_from']).strftime('%d/%m/%Y')} a "
            f"{datetime.fromisoformat(certificate['valid_until']).strftime('%d/%m/%Y')}\n"
            f"Certificado: {certificate['control']}"
        )
        return outcome('encontrada', 'CRF do FGTS obtido automaticamente. O PDF está disponível para download.',
                       evidence, submitted=True, searched=True, stage=stage,
                       certificate=certificate, _pdf=content)
    except FGTSError as error:
        return outcome(error.status, str(error), error.evidence,
                       submitted=submitted, searched=searched, stage=stage)
    except Exception as error:
        reason = 'Tempo de resposta excedido.' if 'Timeout' in type(error).__name__ else 'Não foi possível concluir esta etapa da Caixa.'
        return outcome('indisponivel', reason + ' Nenhum CRF foi confirmado.',
                       f'Etapa: {stage} · {type(error).__name__}',
                       submitted=submitted, searched=searched, stage=stage)
    finally:
        if not page.is_closed():
            await page.close()
