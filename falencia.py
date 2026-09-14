"""Tentativa automatica de certidao judicial de falencia e concordata no TJMG."""
import asyncio
import io
import re
import tempfile
import time
import unicodedata
from datetime import datetime
from pathlib import Path

HOST = 'rupe.tjmg.jus.br'
URL = f'https://{HOST}/rupe/justica/publico/certidoes/criarSolicitacaoCertidao.rupe?solicitacaoPublica=true'
MAX_PDF = 5 * 1024 * 1024


class FalenciaError(Exception):
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
        raise FalenciaError('A certidao judicial contem uma data invalida.')


def parse_certificate_text(text, cnpj):
    """Confere identidade, conteudo negativo, comarca, numero e validade."""
    normalized = re.sub(r'\s+', ' ', fold(text)).replace(chr(186), 'o').replace(chr(176), 'o').strip()
    if cnpj not in compact_cnpj(text):
        raise FalenciaError('A certidao judicial nao corresponde ao CNPJ solicitado.')
    if not all(term in normalized for term in ('certidao', 'falencia')):
        raise FalenciaError('O documento retornado nao foi identificado como certidao de falencia.')
    if not any(term in normalized for term in ('concordata', 'recuperacao judicial')):
        raise FalenciaError('A certidao nao menciona concordata ou recuperacao judicial.')
    if not any(term in normalized for term in (
            'nada consta', 'nao consta', 'negativa', 'inexistem distribuicoes', 'nao foram encontradas')):
        raise FalenciaError('A declaracao negativa de falencia e concordata nao foi reconhecida.')

    control = re.search(r'(?:certidao|solicitacao|controle)\s*(?:n(?:o|umero)?\.?|numero)?\s*[:o.\-]*\s*([A-Z0-9./-]{5,})',
                        normalized)
    validity = re.search(r'validade:\s*(\d{2}/\d{2}/\d{4})', normalized)
    issue = re.search(r'(?:data\s+de\s+)?(?:emissao|expedicao):\s*(\d{2}/\d{2}/\d{4})', normalized)
    comarca = re.search(r'comarca:\s*(.+?)\s+(?:cnpj|validade|emissao|expedicao|certidao|solicitacao):', normalized)
    if not control or not validity or not comarca:
        raise FalenciaError('Nao foi possivel identificar comarca, numero e validade da certidao judicial.')

    valid_until = parse_date(validity[1])
    issued_at = parse_date(issue[1]) if issue else None
    if issued_at and issued_at > valid_until:
        raise FalenciaError('A certidao judicial contem um periodo de validade inconsistente.')

    return {
        'cnpj': cnpj,
        'type': 'Certidao Negativa de Falencia e Concordata',
        'control': control[1].upper(),
        'comarca': comarca[1].strip().title() if comarca else '',
        'issued_at': issued_at.isoformat() if issued_at else '',
        'valid_until': valid_until.isoformat(),
        'issuer': 'Tribunal de Justica de Minas Gerais',
    }


def parse_falencia_pdf(content, cnpj, expected_control=None):
    from pypdf import PdfReader
    if not content.startswith(b'%PDF-') or not 500 < len(content) <= MAX_PDF:
        raise FalenciaError('O TJMG nao devolveu um PDF valido dentro do limite de tamanho.')
    try:
        reader = PdfReader(io.BytesIO(content))
        if not 1 <= len(reader.pages) <= 5:
            raise ValueError('Quantidade de paginas inesperada')
        text = '\n'.join(page.extract_text() or '' for page in reader.pages)
    except Exception as error:
        raise FalenciaError(f'Nao foi possivel ler o PDF judicial ({type(error).__name__}).')
    certificate = parse_certificate_text(text, cnpj)
    if expected_control and certificate['control'] != str(expected_control).upper():
        raise FalenciaError('O PDF judicial nao corresponde a certidao exibida pelo TJMG.')
    return certificate


def is_captcha_or_required_data(text):
    normalized = fold(text)
    return any(term in normalized for term in (
        'codigo de verificacao', 'captcha', 'digite os numeros', 'dados do solicitante',
        'confirmacao e-mail', 'consulta por nome exatamente igual', 'comarca'
    ))


def is_certificate_text(text, cnpj):
    normalized = fold(text)
    return cnpj in compact_cnpj(text) and 'certidao' in normalized and 'falencia' in normalized


def pending_result(text, assisted=False):
    evidence = next((re.sub(r'\s+', ' ', line).strip() for line in text.splitlines()
                     if any(term in fold(line) for term in (
                         'codigo de verificacao', 'dados do solicitante', 'comarca',
                         'consulta por nome', 'email', 'e-mail'
                     ))), '')
    normalized = fold(text)
    status = 'captcha' if any(term in normalized for term in ('captcha', 'codigo de verificacao', 'digite os numeros')) else 'manual'
    return outcome(status,
                   'O TJMG exige dados complementares ou codigo de verificacao para solicitar a certidao judicial.',
                   evidence, submitted=False, searched=False, stage='captcha')


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


async def select_text_option(locator, pattern):
    count = await locator.count()
    for index in range(count):
        select = locator.nth(index)
        try:
            options = await select.locator('option').all_inner_texts()
            for option in options:
                if re.search(pattern, fold(option)):
                    await select.select_option(label=option)
                    return True
        except Exception:
            pass
    return False


async def fill_first(locator, value):
    count = await locator.count()
    for index in range(count):
        field = locator.nth(index)
        try:
            if await field.is_visible(timeout=300):
                await field.fill(value)
                return True
        except Exception:
            pass
    return False


async def fill_by_labels(page, patterns, value):
    if not value:
        return False
    for pattern in patterns:
        try:
            await page.get_by_label(re.compile(pattern, re.I)).fill(value, timeout=800)
            return True
        except Exception:
            pass
    return False


async def prepare_form(page, cnpj, details=None):
    details = details or {}
    try:
        await page.get_by_label(re.compile('JUR', re.I)).check(timeout=800)
    except Exception:
        try:
            await page.locator('input[type="radio"][value*="J" i], input[type="radio"][value*="2"]').first.check(timeout=800)
        except Exception:
            pass
    await select_text_option(page.locator('select'), r'falencia|concordata|recuperacao')
    try:
        await page.get_by_label(re.compile('CPF/CNPJ|CNPJ', re.I)).fill(cnpj, timeout=800)
    except Exception:
        await fill_first(page.locator('input[id*="cnpj" i], input[name*="cnpj" i]'), cnpj)
    await fill_by_labels(page, ('comarca',), details.get('comarca'))
    await fill_by_labels(page, ('nome.*empresa|razao|parte|pesquisad',), details.get('nome_empresa'))
    await fill_by_labels(page, ('nome.*solicitante|solicitante',), details.get('solicitante_nome'))
    await fill_by_labels(page, ('cpf.*solicitante|cpf do solicitante',), details.get('solicitante_cpf'))
    await fill_by_labels(page, ('e-?mail|email',), details.get('solicitante_email'))
    await fill_by_labels(page, ('codigo.*verificacao|captcha|verificacao',), details.get('codigo_verificacao'))


async def read_download_content(download):
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / 'falencia-concordata.pdf'
        await download.save_as(str(target))
        return target.read_bytes()


async def wait_for_certificate(page, cnpj, download_future=None, response_future=None, popup_future=None, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if download_future and download_future.done():
            content = await read_download_content(download_future.result())
            certificate = parse_falencia_pdf(content, cnpj)
            return certificate, content
        if response_future and response_future.done():
            content = await response_future.result().body()
            certificate = parse_falencia_pdf(content, cnpj)
            return certificate, content
        pages = [page]
        if popup_future and popup_future.done() and not popup_future.result().is_closed():
            pages.append(popup_future.result())
        for candidate in pages:
            text = await body_text(candidate)
            if is_certificate_text(text, cnpj):
                certificate = parse_certificate_text(text, cnpj)
                await candidate.emulate_media(media='print')
                content = await candidate.pdf(format='A4', print_background=True)
                certificate = parse_falencia_pdf(content, cnpj, certificate['control'])
                return certificate, content
        await page.wait_for_timeout(500)
    raise FalenciaError('O TJMG nao concluiu a emissao da certidao judicial no prazo.', 'indisponivel')


async def consult_falencia(browser, cnpj, assisted=False, update=None, details=None):
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
            raise FalenciaError(f'O portal judicial respondeu HTTP {response.status}.',
                                'bloqueado' if response.status in (401, 403, 429) else 'indisponivel',
                                f'HTTP {response.status}')
        stage = 'formulario'
        progress('Abrindo o formulario de certidao judicial do TJMG...', evidence='')
        await prepare_form(page, cnpj, details or {})
        text = await body_text(page)
        if is_captcha_or_required_data(text):
            return pending_result(text)
        else:
            button = page.get_by_role('button', name=re.compile('Solicitar|Emitir|Gerar|Enviar', re.I))
            if await visible(button):
                await button.first.click()
                submitted = True
                await page.wait_for_timeout(300)
                text = await body_text(page)
                if is_captcha_or_required_data(text) and not is_certificate_text(text, cnpj):
                    return pending_result(text)
                else:
                    certificate, content = await wait_for_certificate(
                        page, cnpj, download_future, response_future, popup_future
                    )
            else:
                certificate, content = await wait_for_certificate(
                    page, cnpj, download_future, response_future, popup_future
                )
        evidence = (
            f"{certificate['type']}\n"
            f"CNPJ: {cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}\n"
            f"Comarca: {certificate['comarca'] or 'nao informada'}\n"
            f"Validade: {datetime.fromisoformat(certificate['valid_until']).strftime('%d/%m/%Y')}\n"
            f"Certidao: {certificate['control']}"
        )
        return outcome('encontrada',
                       'Certidao de falencia e concordata obtida no TJMG. O PDF esta disponivel para download.',
                       evidence, submitted=True, searched=True, stage=stage,
                       certificate=certificate, _pdf=content)
    except FalenciaError as error:
        return outcome(error.status, str(error), error.evidence,
                       submitted=submitted, searched=submitted, stage=stage)
    except Exception as error:
        reason = 'Tempo de resposta excedido.' if 'Timeout' in type(error).__name__ else 'Nao foi possivel concluir esta etapa do TJMG.'
        return outcome('indisponivel', reason + ' Nenhuma certidao judicial foi confirmada.',
                       f'Etapa: {stage} - {type(error).__name__}',
                       submitted=submitted, searched=submitted, stage=stage)
    finally:
        if not page.is_closed():
            await page.close()
