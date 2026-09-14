"""Tentativa automatica da Certidao Negativa de Debitos Trabalhistas no TST."""
import asyncio
import io
import re
import tempfile
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

HOST = 'cndt-certidao.tst.jus.br'
URL = f'https://{HOST}/gerarCertidao'
MAX_PDF = 5 * 1024 * 1024
HUMAN_CAPTCHA_TIMEOUT = 180


class TrabalhistaError(Exception):
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
        raise TrabalhistaError('A certidao trabalhista contem uma data invalida.')


def parse_certificate_text(text, cnpj):
    """Confere identidade, tipo, numero e validade da certidao trabalhista."""
    normalized = re.sub(r'\s+', ' ', fold(text)).replace(chr(186), 'o').replace(chr(176), 'o').strip()
    if cnpj not in compact_cnpj(text):
        raise TrabalhistaError('A certidao trabalhista nao corresponde ao CNPJ solicitado.')
    if 'certidao' not in normalized or 'debitos trabalhistas' not in normalized:
        raise TrabalhistaError('O documento retornado nao foi identificado como certidao trabalhista.')
    if 'banco nacional de devedores trabalhistas' not in normalized:
        raise TrabalhistaError('A declaracao da certidao trabalhista nao foi reconhecida.')

    number = re.search(
        r'certidao\s*(?:n(?:o|umero)?\.?|numero)?\s*[:o.\-]*\s*([0-9]{4,}(?:[./-][0-9]{2,4})?)',
        normalized,
    )
    validity = re.search(r'validade:\s*(\d{2}/\d{2}/\d{4})', normalized)
    issue = re.search(r'expedicao:\s*(\d{2}/\d{2}/\d{4})', normalized)
    if not number or not validity:
        raise TrabalhistaError('Nao foi possivel identificar numero e validade da certidao trabalhista.')

    valid_until = parse_date(validity[1])
    issued_at = parse_date(issue[1]) if issue else None
    if issued_at and issued_at > valid_until:
        raise TrabalhistaError('A certidao trabalhista contem um periodo de validade inconsistente.')

    kind = 'Certidao Negativa de Debitos Trabalhistas'
    if 'positiva com efeito' in normalized or 'positiva de debitos trabalhistas com efeito' in normalized:
        kind = 'Certidao Positiva de Debitos Trabalhistas com Efeito de Negativa'
    elif 'certidao positiva' in normalized:
        kind = 'Certidao Positiva de Debitos Trabalhistas'

    name = re.search(r'(?:nome|razao social):\s*(.+?)\s+(?:cnpj|cpf):', normalized)
    return {
        'cnpj': cnpj,
        'name': name[1].strip().upper() if name else '',
        'type': kind,
        'control': number[1],
        'issued_at': issued_at.isoformat() if issued_at else '',
        'valid_until': valid_until.isoformat(),
        'issuer': 'Tribunal Superior do Trabalho',
    }


def parse_cndt_pdf(content, cnpj, expected_control=None):
    from pypdf import PdfReader
    if not content.startswith(b'%PDF-') or not 500 < len(content) <= MAX_PDF:
        raise TrabalhistaError('O TST nao devolveu um PDF valido dentro do limite de tamanho.')
    try:
        reader = PdfReader(io.BytesIO(content))
        if not 1 <= len(reader.pages) <= 5:
            raise ValueError('Quantidade de paginas inesperada')
        text = '\n'.join(page.extract_text() or '' for page in reader.pages)
    except Exception as error:
        raise TrabalhistaError(f'Nao foi possivel ler o PDF trabalhista ({type(error).__name__}).')
    certificate = parse_certificate_text(text, cnpj)
    if expected_control and certificate['control'] != str(expected_control):
        raise TrabalhistaError('O PDF trabalhista nao corresponde a certidao exibida pelo TST.')
    return certificate


async def read_download_content(download):
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / 'cndt-trabalhista.pdf'
        await download.save_as(str(target))
        return target.read_bytes()


def is_captcha_page(text):
    normalized = fold(text)
    return any(term in normalized for term in (
        'digite os caracteres exibidos', 'captcha', 'codigo de seguranca', 'nao sou um robo'
    ))


def unavailable_result(text, submitted=True):
    normalized = fold(text)
    evidence = next((re.sub(r'\s+', ' ', line).strip() for line in text.splitlines()
                     if any(term in fold(line) for term in (
                         'captcha', 'codigo', 'nao foi possivel', 'invalido', 'indisponivel'
                     ))), '')
    if is_captcha_page(text):
        return outcome('captcha',
                       'O TST exige a digitacao dos caracteres exibidos na imagem antes de emitir a CNDT.',
                       evidence, submitted=submitted, searched=False, stage='captcha')
    if any(term in normalized for term in ('nao foi possivel', 'servico indisponivel', 'tente novamente')):
        return outcome('indisponivel',
                       'O TST nao concluiu a emissao da certidao trabalhista. Tente novamente mais tarde.',
                       evidence, submitted=submitted, searched=False, stage='resultado')
    return outcome('manual',
                   'A emissao foi enviada, mas o retorno do TST nao permitiu confirmar a certidao automaticamente.',
                   evidence, submitted=submitted, searched=False, stage='resultado')


def captcha_wait_message():
    return ('O TST pediu os caracteres da imagem. Preencha o CAPTCHA na janela do Edge, '
            'clique em Emitir Certidao e aguarde; a consulta continuara automaticamente.')


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
        page.get_by_label(re.compile('CNPJ|CPF', re.I)),
        page.locator('input[id*="cpf" i], input[name*="cpf" i], input[id*="cnpj" i], input[name*="cnpj" i]'),
        page.locator('input[type="text"], input:not([type])'),
    ]
    for candidate in candidates:
        if await visible(candidate):
            return candidate.first
    raise TrabalhistaError('O formulario de emissao da CNDT nao ficou disponivel no prazo.', 'indisponivel')


async def click_emit(page):
    candidates = [
        page.get_by_role('button', name=re.compile('Emitir', re.I)),
        page.locator('input[type="submit"], input[type="button"], button').filter(has_text=re.compile('Emitir', re.I)),
        page.locator('input[value*="Emitir" i]'),
    ]
    for candidate in candidates:
        if await visible(candidate):
            await candidate.first.click()
            return True
    return False


async def wait_for_certificate(page, cnpj, download_future=None, response_future=None, popup_future=None,
                               timeout=30, assisted=False, update=None):
    deadline = time.monotonic() + timeout
    captcha_seen = False
    while time.monotonic() < deadline:
        if download_future and download_future.done():
            content = await read_download_content(download_future.result())
            certificate = parse_cndt_pdf(content, cnpj)
            return certificate, content
        if response_future and response_future.done():
            content = await response_future.result().body()
            certificate = parse_cndt_pdf(content, cnpj)
            return certificate, content
        if popup_future and popup_future.done():
            popup = popup_future.result()
            if not popup.is_closed():
                text = await body_text(popup)
                normalized_popup = fold(text)
                if cnpj in compact_cnpj(text) and 'certidao' in normalized_popup and 'debitos trabalhistas' in normalized_popup:
                    certificate = parse_certificate_text(text, cnpj)
                    await popup.emulate_media(media='print')
                    content = await popup.pdf(format='A4', print_background=True)
                    certificate = parse_cndt_pdf(content, cnpj, certificate['control'])
                    return certificate, content
        text = await body_text(page)
        normalized = fold(text)
        if cnpj in compact_cnpj(text) and 'certidao' in normalized and 'debitos trabalhistas' in normalized:
            certificate = parse_certificate_text(text, cnpj)
            await page.emulate_media(media='print')
            content = await page.pdf(format='A4', print_background=True)
            certificate = parse_cndt_pdf(content, cnpj, certificate['control'])
            return certificate, content
        if is_captcha_page(text):
            blocked = unavailable_result(text)
            if assisted:
                if not captcha_seen and update:
                    update(status='aguardando_usuario', message=captcha_wait_message(),
                           evidence=blocked.get('evidence', ''), submitted=True,
                           searched=False, stage='captcha')
                captcha_seen = True
            else:
                raise TrabalhistaError(blocked['message'], blocked['status'], blocked.get('evidence', ''))
        if any(term in normalized for term in ('nao foi possivel', 'servico indisponivel', 'captcha invalido')):
            blocked = unavailable_result(text)
            if not (assisted and blocked['status'] == 'captcha'):
                raise TrabalhistaError(str(blocked['message']), blocked['status'], blocked['evidence'])
        await page.wait_for_timeout(400)
    if captcha_seen:
        raise TrabalhistaError('O CAPTCHA da CNDT nao foi concluido no Edge dentro de 3 minutos.',
                               'captcha', 'Aguardando caracteres da imagem no TST.')
    raise TrabalhistaError('O TST nao concluiu a emissao da CNDT no prazo.', 'indisponivel')


async def consult_trabalhista(browser, cnpj, assisted=False, update=None,
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
    loop = asyncio.get_running_loop()
    download_future = loop.create_future()
    response_future = loop.create_future()
    popup_future = loop.create_future()

    def on_download(download):
        if not download_future.done():
            download_future.set_result(download)

    def on_response(response):
        content_type = response.headers.get('content-type', '').lower()
        if not response_future.done() and ('application/pdf' in content_type or response.url.lower().endswith('.pdf')):
            response_future.set_result(response)

    def on_popup(popup):
        if not popup_future.done():
            popup_future.set_result(popup)

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
            raise TrabalhistaError(f'O portal trabalhista respondeu HTTP {response.status}.',
                                   'bloqueado' if response.status in (401, 403, 429) else 'indisponivel',
                                   f'HTTP {response.status}')
        field = await find_cnpj_field(page)
        stage = 'formulario'
        progress('Preenchendo o CNPJ no portal da Certidao Trabalhista...', evidence='')
        await field.fill(cnpj)
        if cnpj not in compact_cnpj(await field.input_value()):
            raise TrabalhistaError('Nao foi possivel preencher o CNPJ no portal trabalhista.')

        text = await body_text(page)
        if is_captcha_page(text):
            if not assisted:
                return unavailable_result(text, submitted=False)
            stage = 'captcha'
            blocked = unavailable_result(text, submitted=False)
            if update:
                update(status='aguardando_usuario', message=captcha_wait_message(),
                       evidence=blocked.get('evidence', ''), submitted=False,
                       searched=False, stage=stage)
            certificate, content = await wait_for_certificate(
                page, cnpj, download_future, response_future, popup_future,
                timeout=captcha_timeout, assisted=True, update=update
            )
        else:
            stage = 'emissao'
            submitted = await click_emit(page)
            if not submitted:
                raise TrabalhistaError('Nao foi localizado o botao de emissao da certidao trabalhista.')
            certificate, content = await wait_for_certificate(
                page, cnpj, download_future, response_future, popup_future,
                timeout=captcha_timeout if assisted else 30, assisted=assisted, update=update
            )

        evidence = (
            f"{certificate['type']}\n"
            f"CNPJ: {cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}\n"
            f"Validade: {datetime.fromisoformat(certificate['valid_until']).strftime('%d/%m/%Y')}\n"
            f"Certidao: {certificate['control']}"
        )
        return outcome('encontrada',
                       'Certidao trabalhista obtida automaticamente. O PDF esta disponivel para download.',
                       evidence, submitted=True, searched=True, stage=stage,
                       certificate=certificate, _pdf=content)
    except TrabalhistaError as error:
        return outcome(error.status, str(error), error.evidence,
                       submitted=submitted, searched=submitted, stage=stage)
    except Exception as error:
        reason = 'Tempo de resposta excedido.' if 'Timeout' in type(error).__name__ else 'Nao foi possivel concluir esta etapa do TST.'
        return outcome('indisponivel', reason + ' Nenhuma certidao trabalhista foi confirmada.',
                       f'Etapa: {stage} - {type(error).__name__}',
                       submitted=submitted, searched=submitted, stage=stage)
    finally:
        if not page.is_closed():
            await page.close()
