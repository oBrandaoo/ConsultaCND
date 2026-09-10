"""Fluxo público da Receita, incluindo validação e pesquisa por período.

Observa somente respostas às requisições feitas pelo próprio formulário.
Não reutiliza tokens, não chama APIs à parte e não resolve CAPTCHA.
"""
import asyncio
import re
import time
from datetime import datetime
from urllib.parse import urlsplit

HOST = 'servicos.receitafederal.gov.br'
API = '/servico/certidoes/api/consulta'
URL = f'https://{HOST}/servico/certidoes/#/home/cnpj'


def outcome(status, message, evidence='', **extra):
    return {'status': status, 'message': message, 'evidence': evidence[:4000], **extra}


def parse_response(status, body, stage):
    """Interpreta o contrato usado pelo frontend oficial, sem deduzir regularidade."""
    if not isinstance(body, dict):
        return outcome('manual', 'A Receita devolveu uma resposta não reconhecida.')
    validation = body.get('statusValidacao')
    code = body.get('codigo')
    evidence = f'HTTP {status}' + (f' · Código {str(code)[:40]}' if code else '')
    if validation in ('CaptchaFalhaValidacao', 'CaptchaTokenNaoInformado'):
        return outcome('captcha', 'A Receita não aceitou a validação CAPTCHA. Use a consulta com validação humana no Edge.',
                       evidence + f' · {validation}')
    if status >= 400:
        return outcome('indisponivel', 'A Receita interrompeu a consulta. Nenhuma certidão foi confirmada.',
                       evidence + (f' · {str(validation)[:120]}' if validation else ''))
    if stage != 'pesquisa':
        if body.get('status') in ('SistemaIndisponivel', 'BaseIndisponivel'):
            return outcome('indisponivel', 'A Receita não concluiu a validação do contribuinte.')
        return None  # Validar o CNPJ não é pesquisar certidões.
    state = body.get('statusConsulta')
    if state == 'CertidaoNaoEncontrada':
        return outcome('sem_certidao', 'A Receita não localizou certidões no período pesquisado. Isso não comprova dívida ou irregularidade.')
    if state not in ('Sucesso', 'SucessoMais300'):
        return outcome('indisponivel' if state in ('SistemaIndisponivel','BaseIndisponivel') else 'manual',
                       'A Receita não retornou uma lista de certidões confirmada.', f'Retorno: {str(state)[:120]}')
    certs = body.get('certidoes')
    if not isinstance(certs, list) or not certs:
        return outcome('manual', 'A resposta da Receita não contém certidões que a ferramenta consiga identificar.')
    lines = []
    for cert in certs[:300]:
        if not isinstance(cert, dict): continue
        control, kind, issued = (cert.get(k) for k in ('numeroControle','tipoCertidao','dataEmissao'))
        if not all(isinstance(v,str) and v.strip() for v in (control,kind,issued)): continue
        try: datetime.fromisoformat(issued.replace('Z','+00:00'))
        except ValueError: continue
        parts = []
        for key,label in [('numeroControle','Controle'),('tipoCertidao','Tipo'),('dataEmissao','Emissão'),('dataValidade','Validade'),('situacao','Situação')]:
            value = cert.get(key)
            if isinstance(value,str) and value: parts.append(f'{label}: {value[:160]}')
        lines.append('\n'.join(parts))
    if not lines:
        return outcome('manual', 'Os registros retornados pela Receita não puderam ser identificados com segurança.')
    return outcome('encontrada', 'A Receita retornou certidões para este CNPJ. Confira tipo, validade e situação; podem existir documentos vencidos ou anulados.',
                   '\n\n'.join(lines[:5]), certificate_count=len(lines))


class FederalTrace:
    """Guarda apenas resultado e diagnóstico; nunca cabeçalhos, cookies ou tokens."""
    def __init__(self, cnpj):
        self.cnpj = cnpj
        self.stage = 'acesso'
        self.submitted = False
        self.searched = False
        self.result = None
        self.period = ''
        self.current_request = None
        self.tasks = set()

    def request(self, request):
        url = urlsplit(request.url)
        if url.scheme != 'https' or url.hostname != HOST or request.method != 'POST': return
        if url.path not in (API, API+'/validar-contribuinte'): return
        try: data = request.post_data_json
        except Exception: return
        self.current_request = request
        self.result = None
        self.stage = 'pesquisa' if url.path == API else 'validacao'
        if not isinstance(data,dict) or data.get('ni') != self.cnpj or data.get('tipoContribuinte') != 'PJ':
            self.result = outcome('manual', 'O CNPJ consultado no portal foi alterado. Inicie outra consulta com o CNPJ desejado.')
            return
        self.submitted = True
        self.searched = self.stage == 'pesquisa'
        if self.searched:
            start, end = data.get('periodoInicio'), data.get('periodoFim')
            if isinstance(start,str) and isinstance(end,str):
                self.period = f'Período: {start[:10]} a {end[:10]} · {str(data.get("tipoPesquisa",""))[:30]}'

    def response(self, response):
        if response.request != self.current_request or self.result is not None: return
        task = asyncio.create_task(self._read(response))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _read(self, response):
        request, stage = response.request, self.stage
        try: body = await response.json()
        except Exception: body = None
        if request != self.current_request: return
        self.result = parse_response(response.status, body, stage)

    def decorate(self, result):
        evidence = result.get('evidence','')
        return {**result, 'evidence': '\n'.join(s for s in (self.period,evidence) if s),
                'submitted': self.submitted, 'searched': self.searched, 'stage': self.stage}

    async def close(self):
        for task in list(self.tasks): task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)


async def submit_period(page, cnpj):
    """A segunda tela inicia com o último ano por data de emissão."""
    if not urlsplit(page.url).fragment.rstrip('/').endswith('/cnpj/consultar'): return False
    metadata = await page.locator('#metadados').inner_text()
    if cnpj not in re.sub(r'[^A-Z0-9]','',metadata.upper()):
        raise ValueError('CNPJ divergente na segunda etapa')
    dates = []
    for name in ('dataInicial','dataFinal'):
        field = page.locator(f'br-date-picker[formcontrolname="{name}"] input').first
        dates.append(datetime.strptime(await field.input_value(), '%d/%m/%Y'))
    if dates[0] > dates[1]: raise ValueError('Período inválido')
    await page.get_by_role('button',name='Consultar Certidão',exact=True).click()
    return True


async def consult_federal(browser, cnpj, assisted=False, update=None):
    page = await browser.new_page(locale='pt-BR')
    page.set_default_timeout(12000)
    trace = FederalTrace(cnpj)
    page.on('request', trace.request)
    page.on('response', trace.response)
    last_notice = None
    def notice(message):
        nonlocal last_notice
        if update and message != last_notice:
            update(status='aguardando_usuario', message=message)
            last_notice = message
    try:
        response = await page.goto(URL,wait_until='domcontentloaded',timeout=25000)
        if response and response.status >= 400:
            return trace.decorate(outcome('bloqueado' if response.status in (401,403,429) else 'indisponivel',
                                          f'O portal respondeu HTTP {response.status}.'))
        field = page.locator('input[name="niContribuinte"]')
        await field.wait_for(state='visible')
        await page.wait_for_timeout(2500)
        accept = page.get_by_role('button',name='Aceitar',exact=True)
        if await accept.is_visible(): await accept.click()
        formatted = f'{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}'
        await field.fill(formatted)
        await field.press('Tab')
        if re.sub(r'[.\-/\s]','',await field.input_value()).upper() != cnpj:
            return trace.decorate(outcome('manual','Não foi possível preencher o CNPJ de forma confiável.'))
        if assisted:
            await page.bring_to_front()
            notice('No Edge aberto, clique em Consultar Certidão e conclua a validação humana. A ferramenta aguarda por até 3 minutos; feche essa janela para encerrar.')
        else:
            await page.get_by_role('button',name='Consultar Certidão',exact=True).click()
        deadline = time.monotonic() + (180 if assisted else 35)
        period_submitted = False
        while time.monotonic() < deadline:
            if page.is_closed():
                return trace.decorate(outcome('manual','A janela de consulta foi fechada antes de confirmar o resultado.'))
            if trace.result:
                if assisted and trace.result['status'] == 'captcha':
                    notice('A Receita recusou a validação. No Edge, feche o aviso e tente a validação manualmente. Nenhuma certidão foi confirmada.')
                else:
                    return trace.decorate(trace.result)
            if not period_submitted and not trace.searched and urlsplit(page.url).fragment.rstrip('/').endswith('/cnpj/consultar'):
                period_submitted = await submit_period(page,cnpj)
                if update: update(status='consultando',message='Pesquisando certidões no período exibido pela Receita…')
            # Somente um desafio visível é tratado como pendência humana.
            challenge = page.locator('iframe[title*="challenge" i]:visible, iframe[title*="desafio" i]:visible')
            if await challenge.count():
                if not assisted:
                    return trace.decorate(outcome('captcha','O portal exige validação humana. Use a consulta com validação humana no Edge.'))
                notice('Conclua o desafio de validação diretamente na janela do Edge. A leitura do resultado continuará automaticamente.')
            await asyncio.sleep(.5)
        return trace.decorate(outcome('captcha' if assisted else 'manual',
                                      'O prazo da consulta terminou sem confirmação de certidão. Inicie outra tentativa quando puder concluir a validação.' if assisted else
                                      'O portal não concluiu a consulta no prazo. Tente a consulta com validação humana no Edge.'))
    except Exception as error:
        reason = 'Tempo de resposta excedido.' if 'Timeout' in type(error).__name__ else 'Não foi possível concluir esta etapa do portal.'
        return trace.decorate(outcome('indisponivel',reason+' Nenhuma certidão foi confirmada.',f'Etapa: {trace.stage} · {type(error).__name__}'))
    finally:
        page.remove_listener('request', trace.request)
        page.remove_listener('response', trace.response)
        await trace.close()
        if not page.is_closed(): await page.close()
