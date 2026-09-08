'use strict';
const $=s=>document.querySelector(s);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const shorts={federal:'RF',fgts:'FG',estadual:'MG',municipal:'PM',judicial:'TJ'};
const formatCnpj=v=>v.replace(/^(.{2})(.{3})(.{3})(.{4})(.{2})$/,'$1.$2.$3/$4-$5');
let config,run,pollTimer,toastTimer,pollFailures=0;
const pending=s=>['aguardando','consultando'].includes(s);
const tone=s=>s==='encontrada'?'good':['bloqueado','indisponivel'].includes(s)?'bad':['login','captcha','manual','sem_certidao'].includes(s)?'warning':s==='consultando'?'info':'';
function toast(text){clearTimeout(toastTimer);$('#toast').textContent=text;$('#toast').hidden=false;toastTimer=setTimeout(()=>$('#toast').hidden=true,3500);}
function error(text){$('#form-error').textContent=text;$('#form-error').hidden=false;}
async function fetchJson(url,options={}){const response=await fetch(url,options);const body=await response.json();if(!response.ok)throw new Error(body.error||'Não foi possível consultar.');return body;}
function render(){
  $('#query-summary').hidden=false;
  $('#query-summary').innerHTML='<div><strong>'+esc(formatCnpj(run.cnpj))+'</strong><small>'+esc(run.city)+' · MG</small></div><button class="text-button" data-action="copy">Copiar CNPJ</button>';
  const results=Object.values(run.results),finished=results.filter(r=>!pending(r.status)).length,found=results.filter(r=>r.status==='encontrada').length;
  $('#progress-label').textContent=run.running?finished+' de '+results.length+' retornos':'Verificação encerrada';
  const summary=run.running?'Consultando os órgãos selecionados…':found?found+' órgão(s) retornaram certidão. Confira tipo e validade.':'Nenhuma certidão foi confirmada automaticamente. Veja o retorno de cada órgão.';
  $('#run-announcement').textContent=summary;
  $('#results').innerHTML='<p class="status-summary">'+summary+'</p>'+results.map(r=>{
    const service=config.services[r.service];
    const label=config.statuses[r.status];
    const at=r.checked_at?new Date(r.checked_at).toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit',second:'2-digit'}):'';
    return '<article class="result-card"><div class="result-top"><div class="result-identity"><span class="result-icon">'+shorts[r.service]+'</span><div><h3>'+esc(service.label)+'</h3><small>'+esc(r.service==='municipal'?run.city:service.issuer)+'</small></div></div><span class="badge '+tone(r.status)+(r.status==='consultando'?' spinning':'')+'">'+esc(label)+'</span></div><p>'+esc(r.message)+'</p>'+(r.evidence?'<div class="evidence-label">RETORNO DO ÓRGÃO</div><blockquote class="evidence">'+esc(r.evidence)+'</blockquote>':'')+(!pending(r.status)?'<div class="result-footer"><span>'+esc(r.submitted?'Consulta enviada · '+at:'Tentativa de acesso · '+at)+'</span><a class="button secondary" href="'+esc(r.url)+'" target="_blank" rel="noopener noreferrer">Abrir portal (manual) ↗</a></div>':'')+'</article>';
  }).join('');
  $('#query-fields').disabled=run.running;
  $('#submit').innerHTML=run.running?'Consultando…':'Consultar selecionadas <span>→</span>';
}
async function poll(){
  try{run=await fetchJson('/api/consultations/'+run.id);pollFailures=0;$('#connection-error').hidden=true;render();if(run.running)pollTimer=setTimeout(poll,1500);}
  catch(e){pollFailures++;$('#connection-error').textContent=e.message+' A consulta pode continuar no servidor. '+(pollFailures<5?'Tentando recuperar o retorno…':'Recarregue a página.');$('#connection-error').hidden=false;if(pollFailures<5)pollTimer=setTimeout(poll,3000);else{$('#query-fields').disabled=false;$('#submit').textContent='Consultar selecionadas';}}
}
$('#query-form').addEventListener('submit',async event=>{
  event.preventDefault();if(!config||run?.running)return;$('#form-error').hidden=true;
  const services=[...document.querySelectorAll('input[name=service]:checked')].map(i=>i.value);
  if(!services.length){error('Selecione pelo menos uma certidão.');return;}
  const data={cnpj:$('#cnpj').value,city:$('#city').value,services};
  $('#query-fields').disabled=true;$('#submit').textContent='Iniciando consulta…';clearTimeout(pollTimer);
  try{run=await fetchJson('/api/consultations',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':config.token},body:JSON.stringify(data)});pollFailures=0;sessionStorage.setItem('certifica-consulta',run.id);render();if(run.running)pollTimer=setTimeout(poll,1000);}
  catch(e){error(e.message);$('#query-fields').disabled=false;$('#submit').innerHTML='Consultar selecionadas <span>→</span>';}
});
$('#select-all').addEventListener('click',()=>{
  const checks=[...document.querySelectorAll('input[name=service]')],all=checks.every(c=>c.checked);
  checks.forEach(c=>c.checked=!all);$('#select-all').textContent=all?'Selecionar todas':'Desmarcar todas';
});
$('#query-summary').addEventListener('click',async event=>{
  if(event.target.closest('[data-action=copy]')){try{await navigator.clipboard.writeText(run.cnpj);toast('CNPJ copiado.');}catch{toast('Copie o CNPJ exibido na consulta.');}}
});
async function init(){
  try{
    config=await fetchJson('/api/config');
    $('#city').innerHTML='<option value="">Selecione o município</option>'+config.cities.map(c=>'<option>'+esc(c)+'</option>').join('');
    $('#services').innerHTML=Object.entries(config.services).map(([key,s])=>'<label class="service-choice"><input type="checkbox" name="service" value="'+key+'" checked><span><strong>'+esc(s.label)+'</strong><small>'+esc(s.mode)+'</small></span><span class="service-short">'+shorts[key]+'</span></label>').join('');
    $('#select-all').textContent='Desmarcar todas';$('#query-fields').disabled=false;
    const previous=sessionStorage.getItem('certifica-consulta');
    if(previous){try{run=await fetchJson('/api/consultations/'+previous);$('#cnpj').value=formatCnpj(run.cnpj);$('#city').value=run.city;document.querySelectorAll('input[name=service]').forEach(c=>c.checked=c.value in run.results);render();if(run.running)pollTimer=setTimeout(poll,1000);}catch{sessionStorage.removeItem('certifica-consulta');}}
  }catch(e){error(e.message+' Confira se o servidor está em execução.');}
}
init();


