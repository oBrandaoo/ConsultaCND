"""Consultas pontuais: resultados temporários, sem carteira nem credenciais."""
import asyncio
import copy
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
CITIES = {
    'Santa Rita do Sapucaí': 'https://servicoswebsantaritasapucai.sgpcloud.net:8443/servicosweb/home.jsf',
    'Pouso Alegre': 'https://pousoalegre.atende.net/autoatendimento/servicos/certidao-negativa-de-debitos/detalhar/1',
    'Itajubá': 'https://sistemassonner.itajuba.mg.gov.br/portalcidadao/',
}
SERVICES = {
    'federal': {'label':'Federal', 'issuer':'Receita Federal / PGFN', 'url':'https://servicos.receitafederal.gov.br/servico/certidoes/#/home/cnpj', 'mode':'Experimental · pode exigir validação humana'},
    'fgts': {'label':'FGTS', 'issuer':'CAIXA', 'url':'https://consulta-crf.caixa.gov.br/consultacrf/pages/consultaEmpregador.jsf', 'mode':'Consulta automática não implementada'},
    'estadual': {'label':'Estadual MG', 'issuer':'SEF/MG', 'url':'https://cdt.fazenda.mg.gov.br/', 'mode':'Consulta automática não implementada · gov.br'},
    'municipal': {'label':'Municipal', 'issuer':'Prefeitura', 'url':'', 'mode':'Automática com PDF em Santa Rita e Pouso Alegre'},
    'judicial': {'label':'Falência e concordata', 'issuer':'TJMG', 'url':'https://rupe.tjmg.jus.br/rupe/justica/publico/certidoes/criarSolicitacaoCertidao.rupe?solicitacaoPublica=true', 'mode':'Consulta automática não implementada'},
}
STATUS = {'aguardando':'Aguardando','consultando':'Consultando','encontrada':'Certidão localizada',
    'sem_certidao':'Nenhuma certidão localizada','login':'Login necessário','captcha':'Validação humana',
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

def portal_url(service,city):
    return CITIES[city] if service=='municipal' else SERVICES[service]['url']

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

async def run_portal(browser,service,cnpj,city,assisted=False,update=None):
    if service=='municipal' and city=='Santa Rita do Sapucaí':
        from santa_rita import consult_santa_rita
        return await consult_santa_rita(browser,cnpj,update)
    if service=='municipal' and city=='Pouso Alegre':
        from pouso_alegre import consult_pouso_alegre
        return await consult_pouso_alegre(browser,cnpj,update)
    if service=='federal':
        from federal import consult_federal
        return await consult_federal(browser,cnpj,assisted,update)
    page=await browser.new_page(locale='pt-BR')
    page.set_default_timeout(12000)
    submitted=False
    try:
        response=await page.goto(portal_url(service,city),wait_until='domcontentloaded',timeout=25000)
        if response and response.status>=400:
            return {'status':'bloqueado' if response.status in (401,403,429) else 'indisponivel','message':f'O portal respondeu HTTP {response.status}. A consulta fiscal não foi concluída.','evidence':'','submitted':False}
        await page.wait_for_timeout(2000)
        return await inspect_result(page,service,cnpj,submitted)
    except Exception as error:
        label='O portal demorou a responder.' if 'Timeout' in type(error).__name__ else 'Não foi possível acessar o portal neste ambiente.'
        return {'status':'indisponivel','message':label+' Nenhum resultado fiscal foi confirmado.','evidence':'','submitted':submitted}
    finally:
        await page.close()

class Consultations:
    def __init__(self,runner=None):
        self.lock=threading.RLock()
        self.runs={}
        self.runner=runner or self._run

    def config(self):
        return {'cities':list(CITIES),'services':SERVICES,'statuses':STATUS,
                'default_city':'Santa Rita do Sapucaí','default_services':['municipal']}

    def start(self,data):
        cnpj=normalize_cnpj(data.get('cnpj'))
        city,services=data.get('city'),data.get('services')
        assisted=data.get('assisted',False)
        if not isinstance(assisted,bool) or (assisted and services!=['federal']):
            raise ValidationError('A validação humana está disponível apenas para uma consulta federal por vez.')
        if not isinstance(city,str) or city not in CITIES:
            raise ValidationError('Selecione o município da consulta.')
        if not isinstance(services,list) or not services or len(services)>5 or any(not isinstance(s,str) or s not in SERVICES for s in services) or len(set(services))!=len(services):
            raise ValidationError('Selecione pelo menos uma das cinco certidões, sem repetições.')
        with self.lock:
            self._expire()
            if any(r['running'] for r in self.runs.values()):
                raise ValidationError('Aguarde a consulta em andamento antes de iniciar outra.')
            rid=secrets.token_urlsafe(18)
            self.runs[rid]={'id':rid,'cnpj':cnpj,'city':city,'assisted':assisted,'started_at':timestamp(),'created':time.monotonic(),'running':True,
                'results':{s:{'service':s,'status':'aguardando','message':'Aguardando acesso ao órgão.','evidence':'','submitted':False,'url':portal_url(s,city),'checked_at':None} for s in services}}
            threading.Thread(target=self._execute,args=(rid,),daemon=True).start()
            return self.get(rid)

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
            for service,result in run['results'].items():
                content=result.pop('_pdf',None)
                if content:
                    result['document_url']=f'/api/consultations/{rid}/documents/{service}'
            return run

    def get_document(self,rid,service):
        with self.lock:
            self._expire()
            run=self.runs.get(rid)
            result=run['results'].get(service) if run else None
            if not result or result['status']!='encontrada' or not result.get('_pdf'):
                raise ValidationError('PDF não encontrado ou expirado. Inicie uma nova consulta.')
            return result['_pdf'],f'cnd-{service}-{run["cnpj"]}.pdf'

    def update(self,rid,service,**changes):
        with self.lock:
            self.runs[rid]['results'][service].update(changes)

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

    async def _run(self,rid):
        from playwright.async_api import async_playwright
        run=self.get(rid)
        async with async_playwright() as p:
            pouso=('municipal' in run['results'] and run['city']=='Pouso Alegre')
            pouso_browser=pouso_process=pouso_profile=browser=None
            try:
                if pouso:
                    from pouso_alegre import launch_pouso_browser
                    pouso_browser,pouso_process,pouso_profile=await launch_pouso_browser(p)
                regular=any(not (service=='municipal' and pouso) for service in run['results'])
                browser=await p.chromium.launch(channel='msedge',headless=not run['assisted']) if regular else None
                semaphore=asyncio.Semaphore(2)
                async def consult(service):
                    async with semaphore:
                        self.update(rid,service,status='consultando',message='Acessando o portal oficial…')
                        selected_browser=pouso_browser if service=='municipal' and pouso else browser
                        result=await run_portal(selected_browser,service,run['cnpj'],run['city'],run['assisted'],
                                                lambda **changes:self.update(rid,service,**changes))
                        self.update(rid,service,**result,checked_at=timestamp())
                await asyncio.gather(*(consult(s) for s in run['results']))
            finally:
                if browser:await browser.close()
                if pouso_browser:
                    from pouso_alegre import close_pouso_browser
                    await close_pouso_browser(pouso_browser,pouso_process,pouso_profile)
