# Escopo atual — consulta de CNDs

Atualizado em 07/09/2026 após correção explícita do usuário: a ferramenta deve servir somente para consultar certidões. O escopo anterior de gestão da carteira foi substituído.

## Fluxo

1. Informar CNPJ e município.
2. Selecionar Federal, FGTS, Estadual MG, Municipal e/ou Falência e Concordata.
3. Iniciar a consulta e acompanhar o retorno de cada órgão.
4. Quando o acesso exigir login, validação humana ou dados adicionais, continuar no portal oficial.

Municípios: Santa Rita do Sapucaí, Pouso Alegre e Itajubá, MG.

Não fazem parte do produto atual: cadastro de empresas, importação de carteira, gestão/upload de PDFs, histórico permanente, alertas e agendamentos. Cartão CNPJ também não aparece como certidão fiscal.

## Implementação e limite atual

A interface e a API são exclusivamente de consultas. O conector federal acessa o formulário, preenche e confere o CNPJ, e submete a pesquisa de certidões já emitidas. A captura de resultados positivos depende do formato do retorno e não foi validada ao vivo com uma certidão encontrada.

Nos demais órgãos, a ferramenta verifica o acesso ao portal, mas ainda não submete consulta por CNPJ. Cada cartão informa quando a conclusão é manual. Não há tentativa de contornar CAPTCHA ou bloqueios.

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

## Correção sobre MG

A orientação antiga de emissão sem login estava desatualizada. O link da página de CDT da SEF/MG encaminha agora ao catálogo atual, que informa autenticação gov.br obrigatória inclusive para certidão negativa.

Fontes: [página de CDT](https://www.fazenda.mg.gov.br/empresas/certidao_debitos/), [orientação atual](https://atendimento2.fazenda.mg.gov.br/csm?sys_kb_id=3c9a4c69fb344b90a41cf40d4eefdc5c&id=kb_article_view), [portal CDT](https://cdt.fazenda.mg.gov.br/).

Outros portais: [Receita](https://servicos.receitafederal.gov.br/servico/certidoes/#/home/cnpj), [CAIXA](https://consulta-crf.caixa.gov.br/consultacrf/pages/consultaEmpregador.jsf), [TJMG](https://www.tjmg.jus.br/portal-tjmg/processos/certidao-judicial/), [Santa Rita](https://servicoswebsantaritasapucai.sgpcloud.net/), [Pouso Alegre](https://pousoalegre.atende.net/atende.php?pg=autoatendimento), [Itajubá](https://sistemassonner.itajuba.mg.gov.br/portalcidadao/).

O endereço de Santa Rita foi identificado em [documento oficial municipal](https://sapl.santaritadosapucai.mg.leg.br/media/sapl/public/documentoacessorio/2025/1705/oficio_no_055_-_2025_-_poder_executivo.pdf); sua falha de acesso neste ambiente não comprova indisponibilidade para todos os usuários.

Consulte o [README](../README.md) para executar a aplicação e conhecer o estado real das integrações.
