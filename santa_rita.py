"""CND municipal gratuita de Santa Rita do Sapucaí, pelo formulário público SIA."""
import asyncio
import base64
import io
import logging
import re
import time
import unicodedata
from datetime import datetime

CITY = 'Santa Rita do Sapucaí'
HOST = 'servicoswebsantaritasapucai.sgpcloud.net'
URL = f'https://{HOST}:8443/servicosweb/home.jsf'
PRINT_PATH = '/servicosweb/paginas/public/contribuinte/formCertidaoNegativa.jsf'
MAX_PDF = 5 * 1024 * 1024


class PortalError(Exception):
    def __init__(self,message,status='manual'):
        super().__init__(message)
        self.status=status


def fold(text):
    return ''.join(c for c in unicodedata.normalize('NFD',text.casefold()) if not unicodedata.combining(c))


def check_identity(text,cnpj):
    match=re.search(r'CPF/CNPJ:\s*([A-Z0-9./-]+)',text,re.I)
    if not match or re.sub(r'[./-]','',match[1]).upper()!=cnpj:
        raise PortalError('O contribuinte retornado pelo portal não corresponde ao CNPJ solicitado.')


def parse_certificate(text,cnpj):
    check_identity(text,cnpj)
    normalized=fold(text)
    if 'certidao negativa de debitos' not in normalized or 'encontra-se quite com o erario municipal' not in normalized:
        raise PortalError('O portal não retornou uma declaração de certidão negativa reconhecida.')
    record=re.search(r'codigo de controle da certidao/numero:\s*emitida as:\s*valida ate:\s*'
                     r'([a-z0-9-]{6,64})\s+(\d{2}:\d{2}:\d{2}) do dia (\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})',normalized)
    name=re.search(r'(?m)^Nome:\s*([^\r\n]+)',text)
    if not record or not name:
        raise PortalError('Não foi possível identificar controle, emissão e validade da certidão.')
    try:
        issued=datetime.strptime(record[3]+' '+record[2],'%d/%m/%Y %H:%M:%S')
        expires=datetime.strptime(record[4],'%d/%m/%Y')
    except ValueError:
        raise PortalError('A certidão retornou uma data não reconhecida.')
    if expires.date()<issued.date():
        raise PortalError('As datas da certidão são inconsistentes.')
    return {'cnpj':cnpj,'name':name[1].strip(),'type':'Negativa','issuer':'Prefeitura Municipal de Santa Rita do Sapucaí',
            'control':record[1].upper(),'issued_at':issued.isoformat(),'valid_until':expires.date().isoformat()}


def validate_pdf(content,certificate):
    from pypdf import PdfReader
    if not isinstance(content,bytes) or not content.startswith(b'%PDF-') or len(content)>MAX_PDF:
        raise PortalError('O portal não entregou um PDF válido dentro do limite de tamanho.')
    try:
        reader=PdfReader(io.BytesIO(content))
        if not 1<=len(reader.pages)<=5: raise ValueError('Quantidade de páginas inesperada')
        text='\n'.join(page.extract_text() or '' for page in reader.pages)
    except Exception:
        raise PortalError('Não foi possível ler o PDF retornado pelo portal.')
    compact=re.sub(r'[^A-Z0-9]','',text.upper())
    normalized=fold(text)
    if certificate['cnpj'] not in compact or certificate['control'] not in compact:
        raise PortalError('O PDF não corresponde ao CNPJ e ao controle exibidos pelo portal.')
    if 'santa rita do sapucai' not in normalized or 'certidao negativa' not in normalized:
        raise PortalError('Não foi possível identificar a prefeitura e o tipo da certidão no PDF.')
    issued=datetime.fromisoformat(certificate['issued_at']).strftime('%d/%m/%Y')
    expires=datetime.fromisoformat(certificate['valid_until']).strftime('%d/%m/%Y')
    if issued not in text or expires not in text or fold(certificate['name']) not in normalized:
        raise PortalError('O nome ou as datas no PDF não correspondem à certidão exibida pelo portal.')


async def wait_for_portal(page,target,timeout=25):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if await target.is_visible(): return
        messages=await page.locator('.ui-messages-error-summary:visible, .ui-message-error-detail:visible, .ui-growl-title:visible').all_inner_texts()
        if messages: raise PortalError('Retorno da prefeitura: '+'; '.join(messages)[:1000])
        if await page.locator('input[type=password]:visible').count():
            raise PortalError('O portal passou a exigir autenticação. A consulta automática não foi concluída.','login')
        if await page.locator('iframe[title*="challenge" i]:visible, iframe[title*="desafio" i]:visible').count():
            raise PortalError('O portal exigiu validação humana nesta tentativa.','captcha')
        await asyncio.sleep(.3)
    raise PortalError('O portal não concluiu esta etapa no prazo.','indisponivel')


async def capture_print_pdf(page):
    """Lê o PDF no próprio navegador, preservando sessão e validação TLS.

    No submit nativo de Imprimir, envia os mesmos campos uma única vez via
    fetch, para capturar o PDF antes de o visualizador do Edge consumi-lo.
    """
    button=page.get_by_role('button',name='Imprimir Certidão',exact=True)
    await button.evaluate('''(button, options) => {
      const form=button.form;
      window.__certificaPrint=new Promise(resolve => {
        form.addEventListener('submit', async event => {
          event.preventDefault();
          try {
            if (form.action!==options.url || form.method.toLowerCase()!=='post')
              throw new Error('Destino de impressão inesperado.');
            const response=await fetch(form.action, {
              method:'POST', body:new URLSearchParams(new FormData(form,event.submitter)),
              credentials:'same-origin', redirect:'error', signal:AbortSignal.timeout(30000)
            });
            if (response.status!==200 || !response.headers.get('content-type')?.includes('application/pdf'))
              throw new Error('A impressão não retornou um PDF.');
            if (Number(response.headers.get('content-length'))>options.limit)
              throw new Error('PDF acima do limite.');
            const reader=response.body.getReader(), chunks=[];
            let total=0;
            while (true) {
              const {done,value}=await reader.read();
              if(done) break;
              total+=value.length;
              if(total>options.limit) {await reader.cancel();throw new Error('PDF acima do limite.');}
              chunks.push(value);
            }
            let binary='';
            for(const chunk of chunks) for(let i=0;i<chunk.length;i+=8192)
              binary+=String.fromCharCode(...chunk.subarray(i,i+8192));
            resolve({pdf:btoa(binary)});
          } catch {resolve({error:true});}
        }, {once:true});
      });
    }''',{'url':f'https://{HOST}:8443{PRINT_PATH}','limit':MAX_PDF})
    try:
        await button.click()
        result=await asyncio.wait_for(page.evaluate('() => window.__certificaPrint'),35)
        if not result or result.get('error'):
            raise PortalError('Não foi possível obter o PDF da impressão.','indisponivel')
        return base64.b64decode(result['pdf'],validate=True)
    except asyncio.TimeoutError:
        raise PortalError('A impressão não terminou no prazo.','indisponivel')


async def consult_santa_rita(browser,cnpj,update=None):
    page=await browser.new_page(locale='pt-BR')
    page.set_default_timeout(15000)
    page.set_default_navigation_timeout(40000)
    stage='acesso'
    submitted=False
    def progress(value,message):
        nonlocal stage
        stage=value
        if update: update(status='consultando',message=message)
    try:
        response=await page.goto(URL,wait_until='domcontentloaded',timeout=35000)
        if response and response.status>=400:
            raise PortalError(f'O portal respondeu HTTP {response.status}.','indisponivel')
        module=page.get_by_text('Contribuinte',exact=True)
        await wait_for_portal(page,module)
        await module.click()
        person=page.get_by_text('Pessoa Jurídica',exact=True)
        await wait_for_portal(page,person)
        await person.click()
        # Aguarda o AJAX do próprio formulário antes de preencher a máscara de CNPJ.
        await page.wait_for_function('() => !window.PrimeFaces?.ajax?.Queue || window.PrimeFaces.ajax.Queue.isEmpty()',timeout=12000)
        field=page.locator('input[name="compInformarContribuinte:formNumero:itIdent"]')
        formatted=f'{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}'
        await field.fill(formatted)
        await field.press('Tab')
        if re.sub(r'[.\-/\s]','',await field.input_value()).upper()!=cnpj:
            raise PortalError('Não foi possível preencher o CNPJ de forma confiável.')
        progress('contribuinte','Consultando o CNPJ no cadastro municipal…')
        await page.get_by_role('button',name='OK',exact=True).click()
        submitted=True
        certificate_link=page.get_by_text('CERTIDÃO NEGATIVA DE DÉBITOS',exact=True)
        await wait_for_portal(page,certificate_link)
        check_identity(await page.locator('body').inner_text(),cnpj)
        progress('certidao','Obtendo a certidão municipal…')
        await certificate_link.click(timeout=40000)
        await wait_for_portal(page,page.get_by_role('button',name='Imprimir Certidão',exact=True),timeout=40)
        certificate=parse_certificate(await page.locator('body').inner_text(),cnpj)
        progress('pdf','Obtendo e conferindo o PDF da prefeitura…')
        content=await capture_print_pdf(page)
        validate_pdf(content,certificate)
        valid=datetime.fromisoformat(certificate['valid_until']).date()>=datetime.now().date()
        return {'status':'encontrada','message':'Certidão negativa municipal obtida automaticamente. '+('Confira o PDF e a validade abaixo.' if valid else 'O documento retornado está vencido.'),
                'evidence':f"{certificate['name']}\nCNPJ: {formatted}\nTipo: Negativa\nControle: {certificate['control']}\nEmissão: {datetime.fromisoformat(certificate['issued_at']).strftime('%d/%m/%Y %H:%M:%S')}\nVálida até: {datetime.fromisoformat(certificate['valid_until']).strftime('%d/%m/%Y')}",
                'submitted':True,'searched':True,'stage':'concluida','certificate':certificate,'_pdf':content}
    except Exception as error:
        if not isinstance(error,PortalError):
            logging.getLogger(__name__).warning('Consulta municipal: etapa=%s, %s: %s',stage,type(error).__name__,str(error).splitlines()[0][:240])
        message=str(error) if isinstance(error,PortalError) else 'Não foi possível concluir esta etapa no portal da prefeitura.'
        return {'status':error.status if isinstance(error,PortalError) else 'indisponivel','message':message,
                'evidence':f'Etapa: {stage}','submitted':submitted,'searched':stage in ('certidao','pdf'),'stage':stage}
    finally:
        await page.context.close()
