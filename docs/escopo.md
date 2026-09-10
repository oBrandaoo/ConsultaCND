# Escopo atual — consulta de CNDs

Atualizado em 10/09/2026: a ferramenta deve servir somente para consultar certidões. O usuário aceitou começar por uma certidão automática e depois solicitou Pouso Alegre. O MVP agora cobre, sem custo, as **CNDs municipais de Santa Rita do Sapucaí e Pouso Alegre**. O escopo anterior de gestão da carteira foi substituído.

## Fluxo

1. Informar o CNPJ. Santa Rita do Sapucaí e Municipal vêm selecionados; Pouso Alegre pode ser escolhido no seletor.
2. Clicar em Consultar selecionadas.
3. A ferramenta consulta o contribuinte, solicita a CND e captura e confere o PDF.
4. Conferir tipo, controle e validade no resultado e baixar o documento.

As outras opções permanecem disponíveis, com suas limitações explicitadas. Login ou conclusão manual nessas opções não contam como entrega da automação pretendida.

Municípios: Santa Rita do Sapucaí, Pouso Alegre e Itajubá, MG.

## Restrições confirmadas pelo usuário

- Sem custo de APIs ou serviços de consulta. Não contratar Serpro, agregadores ou serviços de CAPTCHA.
- O objetivo continua sendo concluir as consultas com um clique, após informar os dados necessários. Abrir links ou solicitar conclusão manual não satisfaz esse objetivo.
- Usar os portais oficiais gratuitos. O aplicativo continua local; não foi solicitada hospedagem paga.
- A automação completa sem intervenção foi demonstrada para Santa Rita com FINATEL e para Pouso Alegre com FUVS. Em Pouso, uma janela temporária do Edge aparece, executa o CAPTCHA invisível normal do portal e fecha sozinha. As outras certidões não precisam estar automáticas para este MVP.

Sessões válidas podem ser avaliadas para reduzir logins, mas seu reaproveitamento ainda não foi implementado nem comprovado nestes portais. Não presumir que uma autenticação elimina desafios futuros.

Não fazem parte do produto atual: cadastro de empresas, importação de carteira, gestão/upload de PDFs, histórico permanente, alertas e agendamentos. Cartão CNPJ também não aparece como certidão fiscal.

## Implementação e limite atual

A interface e a API são exclusivamente de consultas. O conector municipal de Santa Rita foi validado ao vivo com CNPJ 24.492.886/0001-04 (FINATEL), sem login nem CAPTCHA: retornou CND negativa e PDF, válido até 09/12/2026. Confere a identidade antes da emissão e compara CNPJ, nome, controle e datas do PDF com a tela.

O conector de Pouso Alegre foi validado ao vivo com CNPJ 23.951.916/0001-22 (FUVS), sem login ou ação do usuário na janela do portal. A consulta final retornou a CND 64217/2026, controle `WGT211201-000-SYXKELIVAQOLQZ-2`, emitida em 10/09/2026 e válida por 90 dias, até 09/12/2026. A aplicação verifica no PDF a prefeitura, declaração negativa, CNPJ, nome, número, controle, emissão e validade. Nenhuma senha é pedida. Os PDFs permanecem apenas na memória pelo prazo da consulta, salvo se o usuário fizer download.

O conector federal distingue a validação inicial do CNPJ da segunda etapa de pesquisa por período. Executa essa pesquisa quando a Receita permite avançar e lê a resposta estruturada vinculada ao CNPJ solicitado. A captura federal de certidão real ainda não foi validada ao vivo.

Após uma falha federal, a opção **Validar no Edge e consultar** abre o portal com o CNPJ preenchido e aguarda intervenção humana por até 3 minutos. O usuário resolve a validação diretamente no portal; a ferramenta retoma a pesquisa e a leitura do resultado. Fechar a janela encerra a tentativa. Isso não equivale a automação sem intervenção.

Nos demais órgãos e em Itajubá, a ferramenta verifica o acesso ao portal, mas ainda não submete consulta por CNPJ. Cada cartão informa quando a conclusão é manual. Não há tentativa de contornar CAPTCHA ou bloqueios. Em Pouso Alegre, o CAPTCHA invisível roda normalmente numa janela visível; se o portal retornar atividade incomum (`EST-000549`), a consulta termina como validação humana, sem inferência fiscal. A automação municipal não garante emissão para CNPJs sem cadastro ou com restrições, nem foi validada com toda a carteira de 50–100 empresas.

Resultados são temporários, mantidos em memória. O banco da versão anterior de gestão permanece intacto e não é utilizado.

## Evidência do teste autorizado

CNPJ fornecido pelo usuário: 18.192.898/0001-02, Santa Rita do Sapucaí.

Teste de 07/09/2026:

- Federal: CNPJ submetido corretamente; retorno do órgão informou que não foi possível concluir a ação, código 023. Nenhuma certidão confirmada.
- FGTS: acesso automatizado bloqueado pela CAIXA antes da consulta.
- Estadual: portal CDT acessível, exige autenticação gov.br.
- Municipal de Santa Rita: endereço identificado não respondeu neste ambiente.
- TJMG: formulário público acessível; pedido exige dados complementares e segue manual.

Uma falha técnica não informa regularidade ou dívida. Ausência de certidão também não deve ser classificada como positiva.

Em 10/09/2026, novas tentativas com 24.492.886/0001-04 e 00.662.065/0001-00 retornaram o aviso 023 antes da pesquisa. Para o segundo CNPJ, a resposta da etapa `validar-contribuinte` informou explicitamente `CaptchaFalhaValidacao` (HTTP 400). A aplicação agora apresenta essa causa, sem deduzi-la apenas do código 023. A falta de segunda submissão e a leitura incorreta da tabela foram corrigidas e verificadas com respostas controladas; nenhuma certidão real foi obtida nessa verificação.

## Correção sobre MG

A orientação antiga de emissão sem login estava desatualizada. O link da página de CDT da SEF/MG encaminha agora ao catálogo atual, que informa autenticação gov.br obrigatória inclusive para certidão negativa.

Fontes: [página de CDT](https://www.fazenda.mg.gov.br/empresas/certidao_debitos/), [orientação atual](https://atendimento2.fazenda.mg.gov.br/csm?sys_kb_id=3c9a4c69fb344b90a41cf40d4eefdc5c&id=kb_article_view), [portal CDT](https://cdt.fazenda.mg.gov.br/).

Outros portais: [Receita](https://servicos.receitafederal.gov.br/servico/certidoes/#/home/cnpj), [CAIXA](https://consulta-crf.caixa.gov.br/consultacrf/pages/consultaEmpregador.jsf), [TJMG](https://www.tjmg.jus.br/portal-tjmg/processos/certidao-judicial/), [Santa Rita](https://servicoswebsantaritasapucai.sgpcloud.net:8443/servicosweb/home.jsf), [Pouso Alegre](https://pousoalegre.atende.net/atende.php?pg=autoatendimento), [Itajubá](https://sistemassonner.itajuba.mg.gov.br/portalcidadao/).

Correção em 10/09: o endereço funcional de Santa Rita é [o portal na porta 8443](https://servicoswebsantaritasapucai.sgpcloud.net:8443/servicosweb/home.jsf), indicado na página 11 do [edital municipal 001/2026](https://arquivos.pmsrs.mg.gov.br/wp-content/uploads/2026/05/Edital_001-2026_-PNAB_ciclo2.pdf). O fluxo público Contribuinte → Pessoa Jurídica → Certidão Negativa de Débitos → Imprimir Certidão permitiu obter o PDF real. O teste anterior usava endereço incompleto.

Consulte o [README](../README.md) para executar a aplicação e conhecer o estado real das integrações.
