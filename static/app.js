'use strict';
const $=s=>document.querySelector(s);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const formatCnpj=v=>v.replace(/^(.{2})(.{3})(.{3})(.{4})(.{2})$/,'$1.$2.$3/$4-$5');
const shorts={federal:'RF',fgts:'FG',trabalhista:'JT',municipal:'SR'};
let config,run,pollTimer,toastTimer,pollFailures=0;
const pending=s=>['aguardando','consultando','aguardando_usuario'].includes(s);
const tone=s=>s==='encontrada'?'good':['bloqueado','indisponivel'].includes(s)?'bad':['login','captcha','manual','sem_certidao'].includes(s)?'warning':s==='consultando'?'info':'';
function toast(text){clearTimeout(toastTimer);$('#toast').textContent=text;$('#toast').hidden=false;toastTimer=setTimeout(()=>$('#toast').hidden=true,3500);}
function error(text){$('#form-error').textContent=text;$('#form-error').hidden=false;}
async function fetchJson(url,options={}){const response=await fetch(url,options);const body=await response.json();if(!response.ok)throw new Error(body.error||'Não foi possível consultar.');return body;}
function render(){
  $('#query-summary').hidden=false;
  $('#query-summary').innerHTML='<div><strong>'+esc(formatCnpj(run.cnpj))+'</strong><small>'+esc(run.scope)+'</small></div><button class="text-button" data-action="copy">Copiar CNPJ</button>';
  const results=Object.values(run.results),finished=results.filter(r=>!pending(r.status)).length,found=results.filter(r=>r.status==='encontrada').length;
  const waiting=results.some(r=>r.status==='aguardando_usuario');
  const queued=run.phase==='queued';
  const summary=waiting?'Uma consulta aguarda uma etapa no Edge.':queued?'Consulta recebida e aguardando o worker.':run.running?finished+' de '+results.length+' consultas concluídas.':found?found+' certidão(ões) localizada(s). Confira o retorno.':'Consultas encerradas sem certidão confirmada.';
  $('#progress-label').textContent=queued?'Na fila':run.running?'Consulta em andamento':'Verificação encerrada';
  $('#run-announcement').textContent=summary;
  $('#results').innerHTML='<p class="status-summary">'+esc(summary)+'</p>'+results.map(r=>{
    const service=config.services[r.service],label=config.statuses[r.status];
    const at=r.checked_at?new Date(r.checked_at).toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit',second:'2-digit'}):'';
    const stage=r.searched?'Pesquisa de certidões enviada':r.submitted?'CNPJ enviado ao órgão':'Consulta de CNPJ não enviada';
    const download=r.status==='encontrada'&&r.document_url?'<p><a class="button primary" href="'+esc(r.document_url)+'" download>Baixar certidão em PDF ↓</a></p>':'';
    return '<article class="result-card"><div class="result-top"><div class="result-identity"><span class="result-icon">'+shorts[r.service]+'</span><div><h3>'+esc(service.label)+'</h3><small>'+esc(service.issuer)+'</small></div></div><span class="badge '+tone(r.status)+(r.status==='consultando'?' spinning':'')+'">'+esc(label)+'</span></div><p>'+esc(r.message)+'</p>'+(r.evidence?'<div class="evidence-label">RETORNO DO ÓRGÃO</div><blockquote class="evidence">'+esc(r.evidence)+'</blockquote>':'')+(r.diagnostic?'<p class="result-diagnostic">'+esc(r.diagnostic)+'</p>':'')+download+(!pending(r.status)?'<div class="result-footer"><span>'+esc(stage+' · '+at)+'</span><a class="button secondary" href="'+esc(r.url)+'" target="_blank" rel="noopener noreferrer">Abrir portal ↗</a></div>':'')+'</article>';
  }).join('');
  $('#query-fields').disabled=run.running;
  $('#submit').innerHTML=run.running?'Consultando…':'Consultar selecionadas <span>→</span>';
}
async function poll(){
  try{run=await fetchJson('/api/consultations/'+run.id);pollFailures=0;$('#connection-error').hidden=true;render();if(run.running)pollTimer=setTimeout(poll,1500);}
  catch(e){pollFailures++;$('#connection-error').textContent=e.message+' A consulta pode continuar no servidor. '+(pollFailures<5?'Tentando recuperar o retorno…':'Recarregue a página.');$('#connection-error').hidden=false;if(pollFailures<5)pollTimer=setTimeout(poll,3000);else{$('#query-fields').disabled=false;$('#submit').innerHTML='Consultar selecionadas <span>→</span>';}}
}
$('#query-form').addEventListener('submit',async event=>{
  event.preventDefault();if(!config||run?.running)return;$('#form-error').hidden=true;
  const services=[...document.querySelectorAll('input[name=service]:checked')].map(input=>input.value);
  if(!services.length){error('Selecione pelo menos uma certidão.');return;}
  $('#query-fields').disabled=true;$('#submit').textContent='Enviando consulta…';clearTimeout(pollTimer);
  try{run=await fetchJson('/api/consultations',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':config.token},body:JSON.stringify({cnpj:$('#cnpj').value,services})});pollFailures=0;sessionStorage.setItem('certifica-consulta',run.id);render();if(run.running)pollTimer=setTimeout(poll,1000);}
  catch(e){error(e.message);$('#query-fields').disabled=false;$('#submit').innerHTML='Consultar selecionadas <span>→</span>';}
});
$('#query-summary').addEventListener('click',async event=>{if(event.target.closest('[data-action=copy]')){try{await navigator.clipboard.writeText(run.cnpj);toast('CNPJ copiado.');}catch{toast('Copie o CNPJ exibido na consulta.');}}});
async function init(){
  try{
    config=await fetchJson('/api/config');
    $('#services').innerHTML=Object.entries(config.services).map(([key,service])=>'<label class="service-choice"><input type="checkbox" name="service" value="'+key+'" '+(config.default_services.includes(key)?'checked':'')+'><span><strong>'+esc(service.label)+'</strong><small>'+esc(service.mode)+'</small></span><span class="service-short">'+shorts[key]+'</span></label>').join('');
    $('#query-fields').disabled=false;
    const previous=sessionStorage.getItem('certifica-consulta');
    if(previous){try{run=await fetchJson('/api/consultations/'+previous);$('#cnpj').value=formatCnpj(run.cnpj);document.querySelectorAll('input[name=service]').forEach(input=>input.checked=input.value in run.results);render();if(run.running)pollTimer=setTimeout(poll,1000);}catch{sessionStorage.removeItem('certifica-consulta');}}
  }catch(e){error(e.message+' Confira se o servidor está em execução.');}
}
init();
