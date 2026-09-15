# Estado do projeto

## Atualizacao - 2026-09-14 - Municipal Congonhal

### Concluido

- Ajuste desta rodada: corrigido o portal de Congonhal para `https://congonhal-mg.prefeituramoderna.com.br/meuiptu/index.php#`, conforme validacao manual do usuario.
- Ajuste desta rodada: corrigido o fluxo de navegacao de Congonhal para abrir a opcao interna `Emissao de Certidao` e aguardar a tela `Emitir Certidao de Debito`, sem autenticar primeiro no bloco de IPTU e Outros Debitos.
- Ajuste desta rodada: apos nova imagem do portal, o clique de Congonhal passou a mirar explicitamente o item lateral `Servicos > Emissao de Certidao` por texto exato normalizado, evitando botoes/links genericos e o botao `Acessar Site` da autenticacao.
- Ajuste desta rodada: o conector preenche os campos reais da tela de emissao: `CPF/CNPJ da Certidao`, `Nome do Requerente`, `Numero do CPF` e `Finalidade`; `Observacao` permanece disponivel e sem preenchimento obrigatorio.
- Ajuste desta rodada: apos HTML real enviado pelo usuario, o conector passou a usar diretamente os nomes reais do formulario Prefeitura Moderna: `nrcpfcnpj`, `nmrequerente`, `nrdocumento`, `finalidade`, `observacao`, com POST em `imprime_certidao.php`.
- Ajuste desta rodada: apos erro real `O NUMERO DO CPF/CNPJ DO REQUERENTE E INVALIDO` ao abrir `imprime_certidao.php?` diretamente, a tentativa direta foi revertida.
- Ajuste desta rodada: o fluxo automatico volta a iniciar em `index.php#`, clica no menu lateral `Emissao de Certidao`, preenche o formulario na mesma pagina e deixa o submit abrir a janela/popup `imprime_certidao.php?`.
- Ajuste desta rodada: o clique no menu lateral passou a usar `locator.get_by_text(...).click()` do Playwright, em vez de `element.click()` via JavaScript, para contar como gesto real do navegador e permitir abertura da popup.
- Ajuste desta rodada: apos nova confirmacao do usuario, o popup de `imprime_certidao.php?` passou a ser tratado como etapa posterior ao submit, com clique no botao `Imprimir` e captura do PDF por resposta `application/pdf` ou download.
- Ajuste desta rodada: removido o fallback por `page.pdf()` porque o Docker roda Chromium headed em Xvfb; se o botao `Imprimir` so abrir dialogo nativo sem PDF/download, o fluxo retorna erro rastreavel em vez de produzir arquivo artificial.
- Ajuste desta rodada: testes simulados de Congonhal agora cobrem o fluxo real `index.php# -> menu lateral -> formulario na mesma pagina -> popup imprime_certidao.php? -> botao Imprimir -> PDF`, sem acionar autenticacao do IPTU.
- Ajuste desta rodada: limite de `nome_usuario` alinhado ao `maxlength=50` real de `nmrequerente`, evitando envio truncado pelo portal.
- Ajuste desta rodada: Congonhal agora exige e valida `nome_usuario` e `cpf_usuario`; o frontend mostra os campos somente quando `municipal_congonhal` esta selecionado e o backend guarda esses dados apenas em `_inputs` durante a consulta.
- Ajuste desta rodada: ampliada a cobertura em `tests/test_app.py`, `tests/test_congonhal.py` e `tests/browser_smoke.py` para CPF invalido, campos extras, contrato de repasse para `consult_congonhal`, erro sem nome/CPF, fluxo Playwright simulado e exibicao/ocultacao dos campos de Congonhal.
- Ajuste desta rodada: Reader mapeou os pontos de alteracao, Writer revisou lacunas de cobertura e Reviewer revisou a integracao final; a revisao final do fluxo popup/download terminou sem bloqueantes novos.

- Implementada a tentativa automatica da CND municipal de Congonhal como servico `municipal_congonhal`.
- Criado `congonhal.py` com acesso ao portal Prefeitura Moderna/IPTU e Outros Debitos, preenchimento de CNPJ, busca da emissao de certidao, captura de resposta PDF e validacao com `pypdf`.
- A validacao do PDF de Congonhal confere CNPJ, municipio, tipo/declaração negativa, numero ou controle, emissao e validade antes de liberar o documento.
- Integrados backend/API/download em `consultations.py` e `app.py`, incluindo escopo, prefixo `cnd-congonhal` e URL do portal oficial.
- Atualizados frontend, smoke test, Dockerfile, README e `docs/escopo.md` para exibir Congonhal junto das demais certidoes.
- Writer criou `tests/test_congonhal.py` com PDF sintetico, rejeicoes de documento invalido/divergente e fluxo Playwright simulado.
- Reviewer revisou a integracao e nao encontrou bloqueantes; apontou riscos operacionais do portal real, principalmente formatos alternativos de PDF/download que precisam de validacao manual.

### Validacao

- `node --check static/app.js` executou com sucesso.
- `git diff --check` nos arquivos modificados executou sem erros; houve apenas avisos esperados de LF/CRLF.
- `git diff --no-index --check` em `congonhal.py` e `tests/test_congonhal.py` executou sem erros; houve apenas avisos esperados de LF/CRLF.
- `python -m unittest discover -s tests -v`, `py -3 -m unittest discover -s tests -v` e `python tests/browser_smoke.py` nao puderam rodar porque `python` e `py` nao estao no PATH desta sessao.
- `docker compose config` e `docker compose build` nao puderam rodar porque `docker` nao esta no PATH desta sessao.

### Pendente

- Para corrigir eventual divergencia restante do portal real de Congonhal, pedir ao usuario Network sanitizado do clique em `Imprimir` no popup apenas se o portal nao retornar PDF/download; remover CPF/CNPJ, nome, cookies e tokens.
- Rodar a suite automatizada em ambiente com Python/Playwright disponivel, incluindo `python -m unittest tests.test_congonhal tests.test_app -v`.
- Rodar `python tests/browser_smoke.py` em ambiente com navegador Playwright disponivel.
- Rodar `docker compose config` e `docker compose build` em ambiente com Docker.
- Validar manualmente a emissao real de Congonhal no modo servidor/Chromium; se o portal emitir PDF por popup, download ou host alternativo, ajustar a captura.

## Atualizacao - 2026-09-14 - Docker servidor

### Concluido

- Ajustada a configuracao Docker para empacotar todos os modulos Python usados pelos servicos atuais.
- `Dockerfile` agora copia `trabalhista.py`, `falencia.py`, `estadual_mg.py`, `estadual_sp.py` e `pouso_alegre.py`, alem dos arquivos ja copiados anteriormente.
- `.dockerignore` agora exclui `.env` e `.env.*` do contexto de build, preservando `.env.example`.
- Reader confirmou que os imports ativos de `consultations.py` estao cobertos pela imagem; `pouso_alegre.py` fica como modulo extra nao bloqueante.
- Writer confirmou os comandos/padroes de validacao do projeto e recomendou proteger `.env` no contexto.
- Reviewer aprovou o diff para seguir para validacao Docker; riscos restantes sao operacionais, nao bloqueantes do ajuste.

### Validacao

- `git diff --check -- Dockerfile .dockerignore compose.yaml` executou sem erros; houve apenas avisos esperados de LF/CRLF.
- Busca textual confirmou que os imports sob demanda de `consultations.py` estao presentes no `Dockerfile`.
- `docker compose config` e `docker compose build` nao puderam rodar porque `docker` nao esta no PATH desta sessao.
- `python -m unittest discover -s tests -v`, `py -3 -m unittest discover -s tests -v` e `python tests/browser_smoke.py` nao puderam rodar porque `python` e `py` nao estao no PATH desta sessao.

### Pendente

- Rodar em ambiente com Docker: `docker compose config`, `docker compose build` e `docker compose up -d`.
- Rodar em ambiente com Python/Playwright: `python -m unittest discover -s tests -v` e `python tests/browser_smoke.py`.
- Preencher `CERTIFICA_BASIC_USER`, `CERTIFICA_BASIC_PASSWORD` e `CERTIFICA_ALLOWED_HOSTS` no `.env` antes de publicar fora de localhost.

## Atualizacao - 2026-09-14 - Estadual SP

### Concluido

- Melhorado o fluxo da eCND estadual SP para assistencia humana no CAPTCHA quando o projeto roda em `local-edge`.
- `consultations.py` agora considera `estadual_sp` no modo assistido local e abre a Sefaz/SP no Edge do computador; em modo `server`, SP continua no Chromium do servidor.
- `estadual_sp.py` agora publica `aguardando_usuario` quando a Sefaz/SP pede CAPTCHA, mantem a pagina aberta por ate 180 segundos, aguarda o operador preencher a validacao e clicar em emitir/consultar, e depois captura/valida o PDF gerado.
- Se o formulario inicial ja exibir campo de CNPJ junto com texto de CAPTCHA, o conector preenche o CNPJ e envia antes de aguardar a etapa humana.
- Pendencias de e-CNPJ, e-CPF, SIPET, login/certificado ou PGE/SP continuam sendo retornadas como `login`/`manual`, sem tentativa de contornar autenticacao.
- `tests/test_estadual.py` recebeu cobertura simulada para SP assistido: espera humana, retomada com PDF, nova tentativa apos CAPTCHA invalido, timeout sem PDF e CAPTCHA presente no formulario inicial.
- `README.md` e `docs/escopo.md` documentam a diferenca entre o modo Windows `local-edge` assistido e o modo servidor/Docker para SP.
- Reader mapeou o fluxo existente; Writer criou testes simulados; Reviewer apontou o risco do CAPTCHA inicial com campo CNPJ e a classificacao de bloqueios nao-CAPTCHA, ambos corrigidos.

### Validacao

- `git diff --check` executou sem erros; houve apenas avisos esperados de LF/CRLF.
- `python -m unittest discover -s tests -v`, `python tests/browser_smoke.py` e `py -3 -m unittest discover -s tests -v` nao puderam rodar porque `python` e `py` nao estao no PATH desta sessao.
- `docker compose config` nao pode rodar porque `docker` nao esta no PATH desta sessao.

### Pendente

- Rodar a suite automatizada em ambiente com Python/Playwright disponivel.
- Validar manualmente a eCND estadual SP real em Windows `local-edge`: a Sefaz/SP deve abrir no Edge, permitir preenchimento humano do CAPTCHA, continuar apos o operador clicar em emitir/consultar e liberar o PDF somente apos validacao.
- Validar manualmente a eCND estadual SP real em modo `server`: se a Sefaz/SP exigir CAPTCHA, login/certificado, e-CNPJ/e-CPF, SIPET ou PGE/SP, a tentativa deve encerrar com status identificado, sem PDF.
