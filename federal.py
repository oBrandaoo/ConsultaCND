"""Emissão ou segunda via da CND federal pelo fluxo público oficial."""
import asyncio
import base64
import binascii
import io
import re
import time
import unicodedata
from datetime import datetime
from urllib.parse import urlsplit

HOST='servicos.receitafederal.gov.br'
ROOT_API='/servico/certidoes/api'
API=ROOT_API+'/consulta'
EMISSION=ROOT_API+'/Emissao'
URL=f'https://{HOST}/servico/certidoes/#/home/cnpj'
MAX_PDF=4*1024*1024


class FederalError(Exception):
    def __init__(self,message,status='manual',evidence=''):
        super().__init__(message)
        self.status=status
        self.evidence=evidence[:1800]


def outcome(status,message,evidence='',**extra):
    return {'status':status,'message':message,'evidence':evidence[:4000],**extra}


def fold(value):
    return ''.join(character for character in unicodedata.normalize('NFD',value.casefold())
                   if not unicodedata.combining(character))


def message_text(body):
    message=body.get('mensagem') if isinstance(body,dict) else None
    if isinstance(message,dict):message=message.get('texto')
    return re.sub(r'\s+',' ',message).strip()[:800] if isinstance(message,str) else ''


def validation_failure(item):
    body=item.get('body')
    if not isinstance(body,dict):
        return FederalError('A Receita devolveu uma resposta não reconhecida.','indisponivel')
    validation=body.get('statusValidacao')
    code=body.get('codigo')
    evidence=f"HTTP {item['status']}"+(f' · Código {str(code)[:40]}' if code else '')
    if validation in ('CaptchaFalhaValidacao','CaptchaTokenNaoInformado'):
        return FederalError('A validação automática invisível da Receita não foi aceita. Tente novamente em uma nova consulta.',
                            'captcha',evidence+f' · {validation}')
    if item['status']>=400:
        return FederalError('A Receita interrompeu a consulta. Nenhuma certidão foi confirmada.',
                            'indisponivel',evidence+(f' · {str(validation)[:100]}' if validation else ''))
    return None


def parse_response(status,body,stage):
    """Interpreta respostas de consulta sem deduzir regularidade de uma falha."""
    item={'status':status,'body':body}
    failure=validation_failure(item)
    if failure:return outcome(failure.status,str(failure),failure.evidence)
    if stage!='pesquisa':return None
    state=body.get('statusConsulta')
    if state=='CertidaoNaoEncontrada':
        return outcome('sem_certidao','A Receita não localizou certidões no período pesquisado. Isso não comprova dívida ou irregularidade.')
    if state not in ('Sucesso','SucessoMais300'):
        return outcome('indisponivel' if state in ('SistemaIndisponivel','BaseIndisponivel') else 'manual',
                       'A Receita não retornou uma lista de certidões confirmada.',f'Retorno: {str(state)[:120]}')
    certs=body.get('certidoes')
    if not isinstance(certs,list) or not certs:
        return outcome('manual','A resposta da Receita não contém certidões identificáveis.')
    lines=[]
    for cert in certs[:300]:
        if not isinstance(cert,dict):continue
        control,kind,issued=(cert.get(key) for key in ('numeroControle','tipoCertidao','dataEmissao'))
        if not all(isinstance(value,str) and value.strip() for value in (control,kind,issued)):continue
        try:datetime.fromisoformat(issued.replace('Z','+00:00'))
        except ValueError:continue
        parts=[]
        for key,label in [('numeroControle','Controle'),('tipoCertidao','Tipo'),('dataEmissao','Emissão'),('dataValidade','Validade'),('situacao','Situação')]:
            value=cert.get(key)
            if isinstance(value,str) and value:parts.append(f'{label}: {value[:160]}')
        lines.append('\n'.join(parts))
    if not lines:return outcome('manual','Os registros retornados pela Receita não puderam ser identificados com segurança.')
    return outcome('encontrada','A Receita retornou certidões para este CNPJ.','\n\n'.join(lines[:5]),certificate_count=len(lines))


def decode_pdf(body):
    encoded=body.get('pdf') if isinstance(body,dict) else None
    if not isinstance(encoded,str) or not encoded:
        raise FederalError('A Receita não devolveu o arquivo da certidão.')
    try:content=base64.b64decode(encoded,validate=True)
    except (ValueError,binascii.Error):raise FederalError('O arquivo devolvido pela Receita não está em um formato reconhecido.')
    if not content.startswith(b'%PDF-') or not 500<len(content)<=MAX_PDF:
        raise FederalError('A Receita não devolveu um PDF válido dentro do limite de tamanho.')
    return content


def parse_federal_pdf(content,cnpj,expected_control=None):
    from pypdf import PdfReader
    try:
        reader=PdfReader(io.BytesIO(content))
        if not 1<=len(reader.pages)<=5:raise ValueError('Quantidade de páginas inesperada')
        text='\n'.join(page.extract_text() or '' for page in reader.pages)
    except Exception as error:
        raise FederalError(f'Não foi possível ler o PDF federal ({type(error).__name__}).')
    compact=re.sub(r'[^A-Z0-9]','',text.upper())
    normalized=re.sub(r'\s+',' ',fold(text)).strip()
    if cnpj not in compact:
        raise FederalError('O PDF federal não corresponde ao CNPJ solicitado.')
    if not all(term in normalized for term in ('secretaria da receita federal do brasil','procuradoria-geral da fazenda nacional','certidao')):
        raise FederalError('O arquivo não contém a identificação esperada da Receita e da PGFN.')
    control=re.search(r'codigo de controle da certidao:\s*([a-z0-9.]+)',normalized)
    issued=re.search(r'emitida\s+as\s+(\d{2}:\d{2}:\d{2})\s+do\s+dia\s+(\d{2}/\d{2}/\d{4})',normalized)
    valid=re.search(r'valida\s+ate\s*:?\s*(\d{2}/\d{2}/\d{4})',normalized)
    name=re.search(r'nome:\s*(.+?)\s+cnpj:',normalized)
    if not all((control,issued,valid,name)):
        raise FederalError('Não foi possível identificar contribuinte, controle, emissão e validade no PDF federal.')
    if expected_control and re.sub(r'\W','',control[1]).upper()!=re.sub(r'\W','',expected_control).upper():
        raise FederalError('O PDF federal não corresponde à certidão selecionada.')
    kind=('Positiva com efeitos de negativa' if 'certidao positiva com efeitos de negativa' in normalized else
          'Negativa' if 'certidao negativa de debitos' in normalized else
          'Positiva' if 'certidao positiva de debitos' in normalized else None)
    if not kind:raise FederalError('O tipo da certidão federal não foi reconhecido.')
    try:
        issued_at=datetime.strptime(issued[2]+' '+issued[1],'%d/%m/%Y %H:%M:%S')
        valid_until=datetime.strptime(valid[1],'%d/%m/%Y').date()
    except ValueError:raise FederalError('O PDF federal contém data de emissão ou validade inválida.')
    return {'cnpj':cnpj,'name':name[1].strip().upper(),'type':kind,'control':control[1].upper(),
            'issued_at':issued_at.isoformat(),'valid_until':valid_until.isoformat(),
            'issuer':'Receita Federal / PGFN'}


class ResponseInbox:
    """Lê apenas corpos JSON da API oficial; não guarda cabeçalhos, cookies ou tokens."""
    def __init__(self,cnpj):
        self.cnpj=cnpj;self.items=[];self.used=set();self.event=asyncio.Event();self.tasks=set()

    def response(self,response):
        parsed=urlsplit(response.url)
        if parsed.scheme!='https' or parsed.hostname!=HOST or not parsed.path.startswith(ROOT_API+'/'):return
        task=asyncio.create_task(self._read(response,parsed.path));self.tasks.add(task);task.add_done_callback(self.tasks.discard)

    async def _read(self,response,path):
        try:
            length=int(response.headers.get('content-length','0') or 0)
            body=None if length>MAX_PDF*2 else await asyncio.wait_for(response.json(),10)
        except Exception:body=None
        ni=kind=None
        if response.request.method=='POST':
            try:data=response.request.post_data_json
            except Exception:data=None
            if isinstance(data,dict):
                ni=data.get('ni');kind=data.get('tipoContribuinte') or data.get('tipoContribuinteEnum')
        self.items.append({'path':path,'status':response.status,'body':body,'ni':ni,'kind':kind})
        self.event.set()

    async def wait(self,predicate,timeout=45):
        deadline=time.monotonic()+timeout
        while True:
            for index,item in enumerate(self.items):
                if index not in self.used and predicate(item):
                    self.used.add(index)
                    if item['ni'] is not None and re.sub(r'[^A-Z0-9]','',str(item['ni']).upper())!=self.cnpj:
                        raise FederalError('O CNPJ enviado pelo portal foi alterado. Inicie uma nova consulta.')
                    return item
            remaining=deadline-time.monotonic()
            if remaining<=0:raise FederalError('A Receita não concluiu esta etapa no prazo.','indisponivel')
            self.event.clear()
            try:await asyncio.wait_for(self.event.wait(),remaining)
            except asyncio.TimeoutError:raise FederalError('A Receita não concluiu esta etapa no prazo.','indisponivel')

    async def close(self):
        for task in list(self.tasks):task.cancel()
        await asyncio.gather(*self.tasks,return_exceptions=True)


async def submit_period(page,cnpj):
    if not urlsplit(page.url).fragment.rstrip('/').endswith('/cnpj/consultar'):raise FederalError('A Receita não abriu a pesquisa de certidões.')
    metadata=await page.locator('#metadados').inner_text()
    if cnpj not in re.sub(r'[^A-Z0-9]','',metadata.upper()):raise FederalError('CNPJ divergente na pesquisa federal.')
    values=[]
    for name in ('dataInicial','dataFinal'):
        value=await page.locator(f'br-date-picker[formcontrolname="{name}"] input').first.input_value()
        values.append(datetime.strptime(value,'%d/%m/%Y'))
    if values[0]>values[1]:raise FederalError('O portal apresentou um período de pesquisa inválido.')
    await page.get_by_role('button',name='Consultar Certidão',exact=True).click()
    return f'Período: {values[0].strftime("%d/%m/%Y")} a {values[1].strftime("%d/%m/%Y")}'


def pdf_result(content,cnpj,source,expected_control=None,certificate_count=1):
    certificate=parse_federal_pdf(content,cnpj,expected_control)
    evidence=(f"{certificate['name']}\nCNPJ: {cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}\n"
              f"Tipo: {certificate['type']}\nControle: {certificate['control']}\n"
              f"Emissão: {datetime.fromisoformat(certificate['issued_at']).strftime('%d/%m/%Y %H:%M:%S')}\n"
              f"Válida até: {datetime.fromisoformat(certificate['valid_until']).strftime('%d/%m/%Y')}")
    return outcome('encontrada','Certidão federal obtida automaticamente. O PDF está disponível para download.',
                   evidence,submitted=True,searched=True,stage=source,certificate=certificate,
                   certificate_count=certificate_count,_pdf=content)


async def consult_federal(browser,cnpj,assisted=False,update=None):
    contexts=getattr(browser,'contexts',[])
    if contexts:
        context=contexts[0]
        usable=[candidate for candidate in context.pages if candidate.url=='about:blank']
        page=usable[0] if usable else await context.new_page()
    else:
        page=await browser.new_page(locale='pt-BR');context=page.context
    page.set_default_timeout(15000)
    inbox=ResponseInbox(cnpj);context.on('response',inbox.response)
    stage='acesso';submitted=False;searched=False
    def progress(message):
        if update:update(status='consultando',message=message)
    try:
        response=await page.goto(URL,wait_until='domcontentloaded',timeout=40000)
        if response and response.status>=400:
            raise FederalError(f'O portal respondeu HTTP {response.status}.',
                               'bloqueado' if response.status in (401,403,429) else 'indisponivel')
        field=page.locator('input[name="niContribuinte"]');await field.wait_for(state='visible')
        await page.wait_for_timeout(3500)
        accept=page.get_by_role('button',name='Aceitar',exact=True)
        if await accept.is_visible():await accept.click()
        formatted=f'{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}'
        await field.click();await field.press('Control+A');await field.press_sequentially(formatted,delay=60);await field.press('Tab')
        if re.sub(r'[^A-Z0-9]','',await field.input_value()).upper()!=cnpj:
            raise FederalError('Não foi possível preencher o CNPJ de forma confiável.')

        stage='verificacao';progress('Verificando se já existe uma certidão federal válida…')
        await page.get_by_role('button',name='Emitir Certidão',exact=True).click()
        verify=await inbox.wait(lambda item:item['path']==EMISSION+'/verificar',30);submitted=True
        failure=validation_failure(verify)
        if failure:raise failure
        state=verify['body'].get('status')

        if state=='Emitida':
            progress('Certidão válida encontrada. Obtendo a segunda via em PDF…')
            modal=page.get_by_role('button',name='Emitir Nova Certidão',exact=True)
            await modal.wait_for(state='visible',timeout=20000)
            await page.get_by_role('button',name='Consultar Certidão',exact=True).last.click()
            validation=await inbox.wait(lambda item:item['path']==API+'/validar-contribuinte',60)
            failure=validation_failure(validation)
            if failure:raise failure
            await page.wait_for_url('**/cnpj/consultar',timeout=20000)
            stage='pesquisa';period=await submit_period(page,cnpj);searched=True
            search=await inbox.wait(lambda item:item['path']==API,45)
            failure=validation_failure(search)
            if failure:raise failure
            parsed=parse_response(search['status'],search['body'],'pesquisa')
            if parsed['status']!='encontrada':return {**parsed,'submitted':True,'searched':True,'stage':stage}
            certs=search['body'].get('certidoes',[])
            candidates=[(index,cert) for index,cert in enumerate(certs[:5]) if isinstance(cert,dict) and cert.get('hasSegundaVia') is not False]
            if not candidates:raise FederalError('A Receita listou certidões, mas não liberou uma segunda via em PDF.')
            valid=[pair for pair in candidates if fold(str(pair[1].get('situacao','')))=='valida']
            index,selected=(valid or candidates)[0]
            await page.wait_for_url('**/cnpj/consultar/resultado',timeout=20000)
            buttons=page.locator('button[title="Segunda via"]');await buttons.first.wait_for(state='visible',timeout=15000)
            if index>=await buttons.count():index=0;selected=candidates[0][1]
            await buttons.nth(index).click()
            copy=await inbox.wait(lambda item:item['path'].startswith(API+'/seg-via/'),45)
            failure=validation_failure(copy)
            if failure:raise failure
            content=decode_pdf(copy['body'])
            result=pdf_result(content,cnpj,'segunda_via',selected.get('numeroControle'),len(certs))
            result['evidence']=period+'\n'+result['evidence']
            return result

        if state not in ('NaoEmitida','ContinuarEmissao'):
            detail=message_text(verify['body'])
            raise FederalError(detail or 'A Receita não liberou a emissão da certidão.',
                               'indisponivel' if state=='SistemaIndisponivel' else 'manual',f'Retorno: {str(state)[:80]}')

        stage='emissao';progress('Emitindo uma nova certidão federal e preparando o PDF…')
        await page.wait_for_url('**/cnpj/resultado',timeout=20000)
        deadline=time.monotonic()+45
        while True:
            emission=await inbox.wait(lambda item:item['path']==EMISSION,max(1,deadline-time.monotonic()))
            failure=validation_failure(emission)
            if failure:raise failure
            state=emission['body'].get('statusEmissao')
            if state!='EmProcessamento':break
        if state!='Sucesso':
            detail=message_text(emission['body'])
            raise FederalError(detail or 'A Receita não emitiu a certidão.',
                               'indisponivel' if state=='SistemaIndisponivel' else 'manual',f'Retorno: {str(state)[:80]}')
        return pdf_result(decode_pdf(emission['body']),cnpj,'emissao')
    except FederalError as error:
        return outcome(error.status,str(error),error.evidence,submitted=submitted,searched=searched,stage=stage)
    except Exception as error:
        reason='Tempo de resposta excedido.' if 'Timeout' in type(error).__name__ else 'Não foi possível concluir esta etapa do portal.'
        return outcome('indisponivel',reason+' Nenhuma certidão foi confirmada.',f'Etapa: {stage} · {type(error).__name__}',
                       submitted=submitted,searched=searched,stage=stage)
    finally:
        context.remove_listener('response',inbox.response);await inbox.close()
        if not page.is_closed():await page.close()
