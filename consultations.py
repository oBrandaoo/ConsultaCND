"""Consultas pontuais: resultados temporários, sem carteira nem credenciais."""
import asyncio
import copy
import os
import queue
import re
import secrets
import sys
import threading
import time
import traceback
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
if (ROOT / '.tools').exists():
    sys.path.insert(0, str(ROOT / '.tools'))
SERVICES = {
    'federal': {'label':'CND federal', 'issuer':'Receita Federal / PGFN', 'url':'https://servicos.receitafederal.gov.br/servico/certidoes/#/home/cnpj', 'mode':'Nacional · emissão ou segunda via automática com PDF'},
    'fgts': {'label':'CRF do FGTS', 'issuer':'Caixa Econômica Federal', 'url':'https://consulta-crf.caixa.gov.br/consultacrf/pages/consultaEmpregador.jsf', 'mode':'Nacional · consulta pública automática com PDF'},
    'trabalhista': {'label':'CNDT trabalhista', 'issuer':'Tribunal Superior do Trabalho', 'url':'https://cndt-certidao.tst.jus.br/gerarCertidao', 'mode':'Nacional · automática; CAPTCHA pode ser concluído no Edge local'},
    'falencia': {'label':'CND falência e concordata', 'issuer':'Tribunal de Justiça de Minas Gerais', 'url':'https://rupe.tjmg.jus.br/rupe/justica/publico/certidoes/criarSolicitacaoCertidao.rupe?solicitacaoPublica=true', 'mode':'Minas Gerais · tentativa automática em Chromium, sem Edge'},
    'estadual_mg': {'label':'CDT estadual MG', 'issuer':'Secretaria de Estado de Fazenda de Minas Gerais', 'url':'https://www2.fazenda.mg.gov.br/sol/', 'mode':'Minas Gerais · tentativa automática em Chromium, sem Edge'},
    'estadual_sp': {'label':'CND estadual SP', 'issuer':'Secretaria da Fazenda e Planejamento de São Paulo', 'url':'https://www10.fazenda.sp.gov.br/CertidaoNegativaDeb/Pages/EmissaoCertidaoNegativa.aspx', 'mode':'São Paulo · eCND não inscritos em Chromium, sem Edge'},
    'municipal': {'label':'CND municipal', 'issuer':'Prefeitura de Santa Rita do Sapucaí', 'url':'https://servicoswebsantaritasapucai.sgpcloud.net:8443/servicosweb/home.jsf', 'mode':'Santa Rita do Sapucaí · automática com PDF'},
}
STATUS = {'aguardando':'Aguardando','consultando':'Consultando','encontrada':'Certidão localizada',
    'sem_certidao':'Nenhuma certidão localizada','login':'Login necessário','captcha':'Validação do portal recusada',
    'bloqueado':'Acesso bloqueado','indisponivel':'Não foi possível consultar','manual':'Concluir no portal',
    'aguardando_usuario':'Aguardando você no Edge'}
PENDING = {'aguardando','consultando','aguardando_usuario'}

class ValidationError(Exception):
    pass

def timestamp():
    return datetime.now().isoformat(timespec='seconds')

def normalize_cnpj(value):
    if not isinstance(value,str):
        raise ValidationError('Informe um CNPJ válido.')
    value=re.sub(r'[.\-/\s]','',value).upper()
    if not re.fullmatch(r'[A-Z0-9]{12}[0-9]{2}',value) or len(set(value))==1:
        raise ValidationError('Confira o CNPJ e os dígitos verificadores.')
    numbers=[ord(c)-48 for c in value]
    for size,weights in [(12,[5,4,3,2,9,8,7,6,5,4,3,2]),(13,[6,5,4,3,2,9,8,7,6,5,4,3,2])]:
        remainder=sum(n*w for n,w in zip(numbers[:size],weights))%11
        if numbers[size]!=(0 if remainder<2 else 11-remainder):
            raise ValidationError('CNPJ inválido. Confira os dígitos verificadores.')
    return value

def formatted_cnpj(v):
    return f'{v[:2]}.{v[2:5]}.{v[5:8]}/{v[8:12]}-{v[12:]}'

def fold(value):
    return ''.join(c for c in unicodedata.normalize('NFD',value.casefold()) if not unicodedata.combining(c))

def portal_url(service,city=None):
    return SERVICES[service]['url']

def assess_page(service,cnpj,text,url,submitted=False,rows=None,challenge=False,login=False):
    """Formulário, falha e bloqueio nunca são convertidos em regularidade fiscal."""
    normalized=fold(text)
    host=urlsplit(url).hostname or ''
    def result(status,message,evidence=''):
        return {'status':status,'message':message,'evidence':evidence[:1800],'submitted':submitted}
    if any(s in normalized for s in ['comportamento malicioso','acesso bloqueado','access denied','request blocked','forbidden']) or host.endswith('perfdrive.com'):
        return result('bloqueado','O portal bloqueou o acesso automatizado. Nenhuma conclusão sobre a situação fiscal foi obtida.')
    if any(s in normalized for s in ['nao foi possivel concluir a acao','tente novamente dentro de alguns minutos','servico indisponivel','temporariamente indisponivel','service unavailable','bad gateway']):
        evidence=next((line for line in text.splitlines() if any(s in fold(line) for s in ['nao foi possivel','tente novamente','indisponivel','unavailable','bad gateway'])),'')
        return result('indisponivel','O órgão não concluiu a consulta. Tente novamente mais tarde.',evidence)
    if login or host in ('sso.acesso.gov.br','acesso.gov.br'):
        return result('login','Conclua a autenticação diretamente no portal oficial. A ferramenta não solicita nem armazena sua senha.')
    if challenge or any(s in normalized for s in ['confirme que voce e humano','verify you are human','nao sou um robo','codigo de seguranca']):
        return result('captcha','O portal exige validação humana antes de continuar. A consulta ainda não foi concluída.')
    if service=='federal' and submitted:
        if any(s in normalized for s in ['nenhuma certidao encontrada','nao foram encontradas certidoes','nao existem certidoes','nenhuma certidao foi encontrada']):
            return result('sem_certidao','A pesquisa não localizou certidões emitidas. Isso não comprova dívida ou irregularidade.',next((line for line in text.splitlines() if 'certid' in fold(line) and ('nenhuma' in fold(line) or 'nao ' in fold(line))),''))
        identity=cnpj in re.sub(r'[^A-Z0-9]','',text.upper())
        certificates=[r for r in (rows or []) if re.search(r'\d{2}/\d{2}/\d{4}',r) and re.search(r'negativa|positiva',fold(r))]
        if identity and certificates:
            return result('encontrada','A Receita retornou certidão(ões) para este CNPJ. Confira tipo e validade abaixo; o retorno pode incluir documentos vencidos.','\n\n'.join(certificates[:5]))
        return result('manual','A consulta foi enviada, mas o retorno não permitiu confirmar uma certidão automaticamente. Confira no portal.')
    if service=='estadual':
        return result('login','A emissão de CDT no portal atual da SEF/MG exige conta gov.br. Continue no portal para autenticar e consultar.')
    if service=='judicial':
        return result('manual','O TJMG exige o preenchimento do pedido, incluindo comarca e dados do solicitante. Continue no formulário oficial.')
    return result('manual','O portal está acessível, mas a consulta por CNPJ ainda não está integrada. Continue no site oficial.')

async def inspect_result(page,service,cnpj,submitted):
    text=await page.locator('body').inner_text(timeout=5000)
    rows=await page.locator('tbody tr').all_inner_texts()
    challenge=False
    for selector in ['iframe[title*="challenge" i]','iframe[title*="desafio" i]','iframe[title*="checkbox" i]','iframe[title*="recaptcha" i]']:
        loc=page.locator(selector)
        for i in range(min(await loc.count(),3)):
            if await loc.nth(i).is_visible():
                challenge=True
    login=await page.locator('input[type=password]:visible').count()>0
    return assess_page(service,cnpj,text,page.url,submitted,rows,challenge,login)

async def run_portal(browser,service,cnpj,city,assisted=False,update=None,inputs=None):
    if service=='municipal':
        from santa_rita import consult_santa_rita
        return await consult_santa_rita(browser,cnpj,update)
    if service=='federal':
        from federal import consult_federal
        return await consult_federal(browser,cnpj,assisted,update)
    if service=='fgts':
        from fgts import consult_fgts
        return await consult_fgts(browser,cnpj,assisted,update)
    if service=='trabalhista':
        from trabalhista import consult_trabalhista
        return await consult_trabalhista(browser,cnpj,assisted,update)
    if service=='falencia':
        from falencia import consult_falencia
        return await consult_falencia(browser,cnpj,assisted,update,(inputs or {}).get('falencia') or {})
    if service=='estadual_mg':
        from estadual_mg import consult_estadual_mg
        return await consult_estadual_mg(browser,cnpj,assisted,update)
    if service=='estadual_sp':
        from estadual_sp import consult_estadual_sp
        return await consult_estadual_sp(browser,cnpj,assisted,update)
    raise ValidationError('Esta versão consulta somente as CNDs federal, FGTS, trabalhista, falência/concordata, estaduais MG/SP ou municipal de Santa Rita.')

class Consultations:
    def __init__(self,runner=None,max_queue=None):
        self.lock=threading.RLock()
        self.runs={}
        self.runner=runner or self._run
        try:
            self.max_queue=int(max_queue if max_queue is not None else os.environ.get('CERTIFICA_MAX_QUEUE','100'))
        except (TypeError,ValueError):
            raise ValueError('CERTIFICA_MAX_QUEUE deve ser um número inteiro.')
        if not 1<=self.max_queue<=500:
            raise ValueError('CERTIFICA_MAX_QUEUE deve ficar entre 1 e 500.')
        self.jobs=queue.Queue(maxsize=self.max_queue)
        self.worker=threading.Thread(target=self._worker_loop,daemon=True,name='certifica-worker')
        self.worker.start()

    def config(self):
        return {'services':SERVICES,'statuses':STATUS,'default_services':['federal']}

    def start(self,data):
        if set(data) - {'cnpj','services','falencia'}:
            raise ValidationError('Envie somente o CNPJ, as certidões selecionadas e os dados judiciais permitidos.')
        cnpj=normalize_cnpj(data.get('cnpj'))
        services=data.get('services')
        if (not isinstance(services,list) or not services or len(services)>len(SERVICES) or
                any(not isinstance(service,str) or service not in SERVICES for service in services) or
                len(set(services))!=len(services)):
            raise ValidationError('Selecione a CND federal, o CRF do FGTS, a CNDT trabalhista, a CND de falência/concordata, as estaduais MG/SP ou a municipal de Santa Rita, sem repetições.')
        from browser_worker import browser_mode
        selected=set(services)
        falencia_inputs=self._validate_falencia_inputs(data.get('falencia'), 'falencia' in selected)
        assisted=bool({'federal','fgts','trabalhista'} & selected) and browser_mode()=='local-edge'
        scope_parts=[]
        if {'federal','fgts','trabalhista'} & selected:
            scope_parts.append('Brasil')
        if {'falencia','estadual_mg'} & selected:
            scope_parts.append('Minas Gerais')
        if 'estadual_sp' in selected:
            scope_parts.append('São Paulo')
        if 'municipal' in selected:
            scope_parts.append('Santa Rita do Sapucaí · MG')
        scope=' + '.join(scope_parts) if scope_parts else 'Brasil'
        with self.lock:
            self._expire()
            rid=secrets.token_urlsafe(18)
            self.runs[rid]={'id':rid,'cnpj':cnpj,'scope':scope,'assisted':assisted,'started_at':timestamp(),
                'processing_started_at':None,'finished_at':None,'phase':'queued','created':time.monotonic(),'running':True,
                '_inputs':{'falencia':falencia_inputs},
                'results':{s:{'service':s,'status':'aguardando','message':'Consulta adicionada à fila do servidor.','evidence':'','submitted':False,'url':portal_url(s,None),'checked_at':None} for s in services}}
            try:
                self.jobs.put_nowait(rid)
            except queue.Full:
                del self.runs[rid]
                raise ValidationError('A fila está cheia. Aguarde algumas consultas terminarem e tente novamente.')
            return self.get(rid)

    def _worker_loop(self):
        while True:
            rid=self.jobs.get()
            try:
                with self.lock:
                    run=self.runs.get(rid)
                    if not run:
                        continue
                    run['phase']='running'
                    run['processing_started_at']=timestamp()
                self._execute(rid)
            finally:
                self.jobs.task_done()

    def _expire(self):
        for rid in list(self.runs):
            if not self.runs[rid]['running'] and time.monotonic()-self.runs[rid]['created']>1800:
                del self.runs[rid]
        finished=[rid for rid in self.runs if not self.runs[rid]['running']]
        for rid in finished[:-19]:
            del self.runs[rid]

    def get(self,rid):
        with self.lock:
            self._expire()
            if rid not in self.runs:
                raise ValidationError('Consulta não encontrada ou expirada. Inicie uma nova consulta.')
            run=copy.deepcopy(self.runs[rid])
            run.pop('created',None)
            run.pop('_inputs',None)
            for service,result in run['results'].items():
                content=result.pop('_pdf',None)
                if content:
                    result['document_url']=f'/api/consultations/{rid}/documents/{service}'
            return run

    def update(self,rid,service,**changes):
        with self.lock:
            self.runs[rid]['results'][service].update(changes)

    def _validate_falencia_inputs(self,value,selected):
        if value is None:
            return {}
        if not selected:
            raise ValidationError('Envie dados de falência/concordata somente quando a certidão judicial estiver selecionada.')
        if not isinstance(value,dict):
            raise ValidationError('Dados judiciais inválidos.')
        allowed={'comarca','nome_empresa','solicitante_nome','solicitante_cpf','solicitante_email','codigo_verificacao'}
        if set(value)-allowed:
            raise ValidationError('Envie somente os dados judiciais permitidos.')
        result={}
        for key,item in value.items():
            if item is None:
                continue
            if not isinstance(item,str):
                raise ValidationError('Dados judiciais devem ser textos.')
            item=re.sub(r'\s+',' ',item).strip()
            if not item:
                continue
            if len(item)>120:
                raise ValidationError('Dados judiciais acima do limite permitido.')
            result[key]=item
        return result

    def get_document(self,rid,service):
        with self.lock:
            self._expire()
            run=self.runs.get(rid)
            result=run['results'].get(service) if run else None
            if service not in SERVICES or not result or result['status']!='encontrada' or not result.get('_pdf'):
                raise ValidationError('PDF não encontrado ou expirado. Inicie uma nova consulta.')
            prefix={'federal':'cnd-federal','fgts':'crf-fgts','trabalhista':'cndt-trabalhista','falencia':'cnd-falencia-concordata','estadual_mg':'cdt-estadual-mg','estadual_sp':'cnd-estadual-sp','municipal':'cnd-santa-rita'}[service]
            return result['_pdf'],f'{prefix}-{run["cnpj"]}.pdf'

    def _execute(self,rid):
        try:
            asyncio.run(self.runner(rid))
        except Exception as error:
            print(f'Falha interna da consulta {rid}: {type(error).__name__}: {str(error).splitlines()[0][:300]}',file=sys.stderr,flush=True)
            traceback.print_exc()
            with self.lock:
                for result in self.runs[rid]['results'].values():
                    if result['status'] in PENDING:
                        result.update(status=getattr(error,'status','indisponivel'),
                                      message=str(error) if getattr(error,'status',None) else f'Não foi possível iniciar a consulta ({type(error).__name__}: {str(error).splitlines()[0][:240]}).',
                                      checked_at=timestamp())
        finally:
            with self.lock:
                self.runs[rid]['running']=False
                self.runs[rid]['phase']='finished'
                self.runs[rid]['finished_at']=timestamp()

    async def _run(self,rid):
        from playwright.async_api import async_playwright
        with self.lock:
            run=copy.deepcopy(self.runs[rid])
        async with async_playwright() as p:
            async def consult(service):
                browser=process=profile=None
                try:
                    from browser_worker import browser_mode
                    if service in ('federal','fgts') or (service=='trabalhista' and browser_mode()=='local-edge'):
                        from browser_worker import launch_federal_browser
                        browser,process,profile=await launch_federal_browser(p)
                        assisted=browser_mode()=='local-edge'
                        issuer={'federal':'Receita','fgts':'Caixa','trabalhista':'TST'}[service]
                        article='do' if service=='trabalhista' else 'da'
                        message=(f'Acessando o portal oficial {article} {issuer} no Edge deste computador…' if assisted else
                                 f'Acessando o portal oficial {article} {issuer} no navegador do servidor…')
                    elif service in ('trabalhista','falencia','estadual_mg','estadual_sp'):
                        from browser_worker import launch_server_browser
                        browser,process,profile=await launch_server_browser(p)
                        assisted=False
                        issuer={'trabalhista':'TST','falencia':'TJMG','estadual_mg':'SEF/MG','estadual_sp':'Sefaz/SP'}[service]
                        message=f'Acessando o portal oficial do {issuer} no Chromium do servidor…'
                    else:
                        from browser_worker import launch_municipal_browser
                        browser=await launch_municipal_browser(p)
                        message='Acessando o portal de Santa Rita do Sapucaí…'
                        assisted=False
                    self.update(rid,service,status='consultando',message=message)
                    result=await run_portal(browser,service,run['cnpj'],None,assisted,
                                            lambda **changes:self.update(rid,service,**changes),
                                            run.get('_inputs') or {})
                    self.update(rid,service,**result,checked_at=timestamp())
                except Exception as error:
                    self.update(rid,service,status=getattr(error,'status','indisponivel'),
                                message=f'Não foi possível iniciar esta consulta ({type(error).__name__}).',
                                evidence='',submitted=False,checked_at=timestamp())
                finally:
                    if browser:
                        from browser_worker import close_browser
                        await close_browser(browser,process,profile)
            # Serviços nacionais compartilham o mesmo perfil persistente do navegador.
            # A execução sequencial evita duas instâncias concorrentes sobre esse perfil.
            for service in run['results']:
                await consult(service)
