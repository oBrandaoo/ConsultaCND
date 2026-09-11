# Certifica — consulta de CNDs

Ferramenta local dedicada a consultas pontuais. **CND municipal automática, com PDF, para Santa Rita do Sapucaí. Pouso Alegre tem o fluxo implementado, mas permanece incompleta no ambiente relatado pelo usuário devido ao bloqueio do portal.** Santa Rita e a certidão municipal vêm selecionadas: informe o CNPJ e clique em Consultar selecionadas. Para Pouso Alegre, altere o município no seletor. Não há cadastro de empresas, carteira, importação, upload de documentos, histórico permanente ou agenda.

Sem API paga, serviço de CAPTCHA ou hospedagem contratada. A consulta roda no computador com Python e Edge.

## Executar

Requer Python 3.11+ e Microsoft Edge instalado.

```powershell
python -m pip install --user -r requirements.txt
python app.py
```

O uso de `--user` instala as dependências no mesmo ambiente do Python que inicia o servidor e evita que terminais com configuração diferente deixem de encontrar `playwright.async_api`.

Abra **http://127.0.0.1:8000**. Para outra porta, use `python app.py --port 8001`. Encerre com Ctrl+C.

## O que está implementado

- Validação de CNPJ numérico/alfanumérico e seleção das cinco certidões.
- **Municipal de Santa Rita:** acessa o formulário público Contribuinte → Pessoa Jurídica, preenche o CNPJ, confere o contribuinte, obtém a CND e captura o PDF de Imprimir Certidão. Confere CNPJ, nome, controle, emissão e validade entre tela e PDF antes de apresentar o documento. O usuário recebe tipo, validade, controle e botão de download, sem concluir etapas no portal.
- **Municipal de Pouso Alegre:** abre uma janela temporária do Edge, escolhe emissão por CPF/CNPJ, preenche CNPJ e finalidade, obtém o PDF e fecha a janela sozinha quando o portal permite avançar. Confere prefeitura, tipo negativo, CNPJ, nome, número, controle, emissão e validade antes de liberar o download. A sessão temporária pode ser recusada mesmo quando o formulário abre normalmente no Edge habitual do usuário.
- Consulta federal experimental: preenche e confere o CNPJ, valida o contribuinte e, quando liberado pela Receita, executa a segunda etapa com o período padrão do portal (último ano por data de emissão). Lê a resposta estruturada da pesquisa, vinculada ao CNPJ enviado pelo formulário.
- **Validar no Edge e consultar**: após uma falha federal, abre uma janela temporária do Edge com o CNPJ preenchido. O usuário clica em Consultar Certidão e resolve a validação no próprio portal; a ferramenta acompanha o resultado por até 3 minutos. Fechar essa janela encerra a tentativa. Esse modo depende de intervenção humana e ainda não confirmou uma certidão real nos testes.
- Nos demais órgãos e municípios, verifica o acesso ao portal e aponta login, CAPTCHA, bloqueio, indisponibilidade ou necessidade de consulta manual. **Isso não equivale a consultar a situação fiscal.**
- Resultados temporários na tela, com horário, distinção entre envio da consulta e verificação de acesso, e mensagem do órgão quando identificada.
- Link explícito para continuar manualmente no portal e botão para copiar CNPJ.
- Uma consulta por vez, com no máximo dois acessos aos órgãos em paralelo e sem repetição automática de submissões.

A consulta federal procura certidões já emitidas e ainda não entrega PDF. A integração municipal de Santa Rita solicita o documento pelo fluxo público da prefeitura e disponibiliza seu PDF original. Certidões localizadas podem estar vencidas; a data retornada sempre aparece no resultado.

## Situação das integrações em 10/09/2026

| Órgão                 | Estado real da implementação                                                                                                                                                                           |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Receita / PGFN          | Fluxo experimental com validação e pesquisa por período; opção de validação humana no Edge. Nos testes reais, a Receita recusou a validação antes da pesquisa. Com 00.662.065/0001-00, a resposta foi HTTP 400, código 023, `statusValidacao: CaptchaFalhaValidacao`. Nenhuma certidão real foi confirmada. |
| CAIXA / FGTS            | Acesso automatizado bloqueado no ambiente de teste. Consulta por CNPJ ainda não integrada.                                                                                                              |
| SEF/MG                  | Portal atual CDT exige login gov.br. A ferramenta abre o link para conclusão manual; não captura credenciais.                                                                                          |
| Santa Rita do Sapucaí  | **CND e PDF obtidos automaticamente para FINATEL, 24.492.886/0001-04, sem login ou CAPTCHA no teste real de 10/09/2026. Validade: 09/12/2026.** O endereço correto usa a porta 8443. |
| Pouso Alegre           | **Integração incompleta no ambiente do usuário: bloqueio `EST-000549` reproduzido antes de liberar o formulário.** Há registro de emissão anterior para FUVS (64217/2026), mas isso não comprova funcionamento contínuo. O usuário informou que o formulário abre no Edge habitual; a sessão temporária do conector foi recusada, inclusive com abertura direta pelo CDP. |
| Itajubá                | Acesso ao portal; consulta por CNPJ ainda não integrada nem validada. |
| TJMG                    | Formulário público requer dados complementares. Pedido e emissão ainda manuais.                                                                                                                       |

O usuário reduziu o MVP inicialmente a **uma consulta automática**; há conectores para duas prefeituras, mas Pouso Alegre ainda não atende de forma confiável ao objetivo de emissão com um clique. Não existe resultado simulado no aplicativo; as simulações são exclusivas dos testes. O sucesso com FINATEL e FUVS não garante emissão para todo CNPJ: ausência de cadastro municipal, restrições do contribuinte, bloqueios temporários ou mudanças nos portais podem impedir o documento. A carteira de 50–100 CNPJs ainda não foi validada.

O [portal municipal correto](https://servicoswebsantaritasapucai.sgpcloud.net:8443/servicosweb/home.jsf) está indicado na página 11 do [edital municipal 001/2026](https://arquivos.pmsrs.mg.gov.br/wp-content/uploads/2026/05/Edital_001-2026_-PNAB_ciclo2.pdf). O endereço sem porta usado anteriormente não respondeu. A captura do PDF usa a sessão temporária do Edge e o submit de Imprimir, sem desativar a verificação TLS nem repetir a submissão.

O diagnóstico de 10/09 identificou também que a versão anterior parava após a validação inicial, sem executar a pesquisa por período, e procurava uma tabela HTML que não correspondia à tabela do portal atual. O conector agora observa as respostas produzidas pelo formulário oficial, distingue CAPTCHA de indisponibilidade e informa se houve apenas validação do CNPJ ou pesquisa de certidões. Não chama endpoints fora do fluxo do portal nem guarda tokens de CAPTCHA.

Correção do levantamento anterior: a [página antiga da SEF/MG](https://www.fazenda.mg.gov.br/empresas/certidao_debitos/) ainda descrevia emissão sem login, mas seu link de serviço encaminha à [orientação atual de CDT](https://atendimento2.fazenda.mg.gov.br/csm?sys_kb_id=3c9a4c69fb344b90a41cf40d4eefdc5c&id=kb_article_view), que informa autenticação gov.br obrigatória, e ao [portal CDT](https://cdt.fazenda.mg.gov.br/). Não usar a orientação antiga para planejar essa integração.

As regras de dígito verificador seguem o [manual da Receita Federal](https://www.gov.br/receitafederal/pt-br/centrais-de-conteudo/publicacoes/documentos-tecnicos/cnpj/manual-dv-cnpj.pdf). Validar os dígitos não confirma a existência ou a situação cadastral.

## Operação

O aplicativo escuta apenas em 127.0.0.1 e usa proteção de origem nas escritas. Não tem autenticação multiusuário e não deve ser exposto por túnel ou servidor público.

Os resultados e PDFs ficam em memória por até 30 minutos (máximo de 20 consultas recentes) e somem ao reiniciar o servidor. O navegador guarda apenas o identificador temporário da consulta em sessionStorage para recuperar a tela após recarregar. O PDF só é gravado no computador quando o usuário o baixa; a aplicação não cria arquivo permanente. Não há armazenamento de senhas ou certificados digitais. A sessão de consulta ao portal é descartada ao terminar. O banco da versão anterior não é acessado nem alterado.

Pouso Alegre executa o CAPTCHA invisível normal do próprio portal em uma janela visível. A ferramenta não resolve, reutiliza ou contorna tokens. Se o portal retornar atividade incomum (`EST-000549`), o resultado informa **Acesso bloqueado** e preserva a mensagem original em **RETORNO DO ÓRGÃO**. A etapa interna aparece separadamente. Esse aviso não confirma que exista um desafio para resolver manualmente, nem que todas as sessões da rede estejam bloqueadas. Uma falha antes do clique de emissão não é marcada como pesquisa enviada.

A espera pelo formulário dura até 60 segundos após o acesso inicial. Se um aviso de segurança aparecer durante essa espera, a janela continua aberta e a mensagem já aparece no aplicativo. O conector acompanha a mesma página, sem recarregar ou repetir pedidos. Só preenche os dados quando o aviso desaparecer e o formulário estiver disponível. Se a restrição persistir até o prazo, encerra com o retorno do órgão. Fechar a janela manualmente encerra a tentativa. Essa espera corrige o fechamento imediato; não garante que o portal libere a sessão.

Na verificação real dessa espera, o aviso apareceu após aproximadamente 10 segundos. A janela permaneceu aberta durante os 60 segundos e o bloqueio persistiu até o término. Não houve envio de CNPJ ou emissão de documento nesse teste.

### Se a janela do Edge não iniciar em Pouso Alegre

Feche janelas temporárias de testes anteriores, encerre o servidor com Ctrl+C e execute novamente `python app.py`. O inicializador usa uma porta local dinâmica indicada pelo próprio Edge, evitando conflitos com outras instâncias. Se a conexão direta do Windows não estiver disponível, tenta automaticamente a abertura visível pelo Playwright. Se aparecer `EST-000549`, o portal recusou a sessão usada na tentativa. O portal recomenda aguardar, mas não fornece prazo de liberação. Se o formulário abrir no Edge habitual e falhar no aplicativo, isso é uma diferença entre as sessões; não há evidência suficiente para atribuir o problema à rede inteira ou garantir que esperar resolva. Se o aviso também ocorrer diretamente no portal, procure o atendimento da prefeitura com o código da mensagem.

A versão anterior de gestão foi preservada em `.runtime/gestao-anterior/` durante a correção de escopo. Esse diretório é local e ignorado pelo Git.

## Testes

```powershell
python -m unittest discover -s tests -v
python tests/browser_smoke.py
```

Os testes automatizados usam respostas controladas e não consultam terceiros. Cobrem o fluxo federal, o fluxo municipal completo até a impressão, envio único dos campos originais do formulário, rejeição de PDF incorreto e contribuinte divergente, download temporário e expiração. Os PDFs dos testes são sintéticos e marcados como teste. A interface também é verificada no Edge, incluindo layout móvel e recuperação após recarga.

Separadamente, o conector municipal foi executado no portal real e obteve um PDF de 46.010 bytes para a FINATEL em 10/09/2026, controle `51FADF48AABBCAE5`, válido até 09/12/2026. Cada nova consulta obtém um novo retorno da prefeitura; não reutiliza esse documento como resultado para outros CNPJs. Falhas de acesso não são resultados fiscais, e nenhuma certidão é declarada negativa apenas por carregar um formulário.

O teste completo pela interface local também passou: preenchimento do CNPJ e um clique, retorno real `encontrada`, download do PDF, conferência do documento, recuperação após recarga e layout móvel. Consulta de 10/09/2026 às 12:34:42, controle `07A6F8488C317CD9`, validade 09/12/2026; o teste levou aproximadamente 22 segundos. Uma tentativa anterior falhou na etapa de emissão; o prazo de navegação foi ampliado para 40 segundos, sem repetição automática do pedido.

Pouso Alegre foi validado separadamente pela interface local com a FUVS: um clique após selecionar o município, retorno real `encontrada`, PDF conferido e download disponível em aproximadamente 17 segundos. A emissão final de 10/09/2026 gerou a certidão 64217/2026, controle `WGT211201-000-SYXKELIVAQOLQZ-2`, válida até 09/12/2026. O portal gerou também a certidão 64202/2026 durante o mapeamento inicial. Cada teste solicitou o documento uma única vez na etapa final.

Na validação anterior, os **36 testes controlados** e os testes de interface passaram, incluindo os cinco casos originais de Pouso Alegre. Esses testes não comprovam que o portal aceitará uma nova sessão real.

Na investigação do bloqueio relatado pelo usuário, em 10/09/2026, a página externa respondeu HTTP 200, mas o formulário embutido retornou `EST-000549`, sem envio de CNPJ. O bloqueio ocorreu tanto na abertura alternativa pelo Playwright quanto no Edge iniciado diretamente e conectado por CDP fora do isolamento de testes. Nenhuma nova certidão foi emitida nessa investigação. A correção preserva o retorno original, distingue bloqueio de validação humana e corrige o indicador de envio; ela **não elimina a recusa do portal**.
