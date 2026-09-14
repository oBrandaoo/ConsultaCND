# Estado do projeto - 2026-09-13

## Atualizacao - 2026-09-14

### Concluido

- Melhorado o fluxo da CNDT trabalhista para assistencia humana no CAPTCHA quando o projeto roda em `local-edge`.
- `consultations.py` agora considera `trabalhista` no modo assistido local e abre o portal do TST no Edge do computador; em modo `server`, a CNDT continua no Chromium do servidor.
- `trabalhista.py` agora publica `aguardando_usuario` quando o TST pede os caracteres da imagem, mantem a pagina aberta por ate 180 segundos, aguarda o operador preencher o CAPTCHA e clicar em emitir, e depois captura/valida o PDF gerado.
- A protecao visual do TST nao e resolvida nem contornada automaticamente; sem janela interativa ou apos timeout, o resultado final continua sendo `captcha`, sem PDF.
- `tests/test_trabalhista.py` recebeu cobertura simulada para espera humana, retomada com PDF apos acao do operador, nova tentativa apos CAPTCHA invalido e expiracao curta sem falso positivo.
- `README.md` e `docs/escopo.md` documentam a diferenca entre o modo Windows `local-edge` assistido e o modo servidor/Docker.

### Validacao

- `git diff --check` executou sem erros; houve apenas avisos esperados de LF/CRLF.
- `python -m unittest discover -s tests -v`, `python tests/browser_smoke.py` e `py -3 -m unittest discover -s tests -v` nao puderam rodar porque `python` e `py` nao estao no PATH desta sessao.
- `docker compose config` nao pode rodar porque `docker` nao esta no PATH desta sessao.

### Pendente

- Rodar a suite automatizada em ambiente com Python/Playwright disponivel.
- Validar manualmente a CNDT real em Windows `local-edge`: o TST deve abrir no Edge, pedir os caracteres, continuar apos o operador clicar em emitir e liberar o PDF somente apos validacao.
- Validar manualmente a CNDT real em modo `server`: se o TST exigir CAPTCHA, a tentativa deve encerrar com status `captcha`, sem abrir Edge e sem PDF.

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

## Atualizacao - 2026-09-14 - Previa PDF no site

### Concluido

- Confirmado com Reader que todos os conectores atuais ja retornam PDF validado quando a certidao e obtida: Federal e Santa Rita capturam PDF oficial; FGTS, CNDT, falencia/concordata e estaduais MG/SP imprimem a pagina/popup HTML com `page.pdf()` quando necessario e revalidam o PDF.
- `static/app.js` agora exibe uma previa embutida do PDF para qualquer resultado `encontrada` com `document_url`, mantendo o botao de download.
- `static/styles.css` recebeu estilos responsivos para a previa PDF em desktop e mobile.
- `tests/browser_smoke.py` foi ampliado para verificar que sete certidoes simuladas encontradas exibem sete iframes de previa PDF.
- `README.md` e `docs/escopo.md` documentam que a certidao validada aparece na propria pagina e tambem fica disponivel para download.
- Writer mapeou a cobertura existente de PDF/captura; Reviewer revisou XSS, gating por `document_url`, download e layout responsivo sem findings bloqueantes.

### Validacao

- `git diff --check` executou sem erros; houve apenas avisos esperados de LF/CRLF.
- `node --check static/app.js` executou com sucesso apos permissao fora do sandbox; a tentativa no sandbox falhou por `EPERM` ao resolver o caminho do OneDrive.
- `python -m unittest discover -s tests -v`, `python tests/browser_smoke.py` e `py -3 -m unittest discover -s tests -v` nao puderam rodar porque `python` e `py` nao estao no PATH desta sessao.
- `docker compose config` e `docker compose build` nao puderam rodar porque `docker` nao esta no PATH desta sessao.

### Pendente

- Rodar a suite automatizada e o smoke test em ambiente com Python/Playwright disponivel.
- Validar visualmente em navegador real que a previa embutida abre os PDFs dos sete servicos sem quebrar o layout mobile.

## Concluido

- Implementada a integracao da CNDT trabalhista como servico `trabalhista`.
- Criado `trabalhista.py` com tentativa automatica no Chromium do servidor, deteccao de CAPTCHA, captura de PDF por download, resposta PDF, popup ou impressao da pagina, e validacao com `pypdf`.
- Atualizados `consultations.py` e `app.py` para listar, executar e servir PDFs da CNDT.
- Atualizada a interface em `static/app.js` e `static/index.html` para exibir a CNDT trabalhista.
- Criados testes controlados em `tests/test_trabalhista.py` e ampliados `tests/test_app.py` e `tests/browser_smoke.py`.
- Atualizados `README.md` e `docs/escopo.md` com o novo escopo e a dependencia de validacao visual no TST.
- Bulk Reader analisou pontos de extensao; Code Writer criou o teste inicial; Reviewer revisou e apontou ajustes de download/import, ja incorporados.
- Implementada a CND de falencia e concordata como servico `falencia`, com tentativa automatica no RUPE/TJMG.
- Criado `falencia.py` com preenchimento seguro do CNPJ e dos dados judiciais opcionais informados no formulario, captura de PDF por download/resposta/popup ou impressao da pagina, e validacao com `pypdf`.
- Criados testes controlados em `tests/test_falencia.py` e ampliados `tests/test_app.py` e `tests/browser_smoke.py` para o novo servico.
- Atualizados `README.md`, `docs/escopo.md`, `static/app.js` e `static/index.html` para exibir o servico judicial e documentar os dados obrigatorios do RUPE/TJMG.
- Reader revisou o contrato do RUPE/TJMG; Writer criou os testes iniciais; Reviewer apontou que `aguardando_usuario` nao podia encerrar o browser, e o fluxo foi corrigido para aguardar o PDF antes de finalizar.
- Ajustados `trabalhista` e `falencia` para nao abrirem Edge local: ambos rodam no Chromium do servidor; CAPTCHA/dados faltantes encerram com status identificado.
- Adicionados campos opcionais no frontend para comarca, nome exato, solicitante, CPF, e-mail e codigo de verificacao do RUPE/TJMG; esses dados ficam em `_inputs` interno e sao removidos do retorno da API.
- Implementadas as CNDs estaduais como servicos `estadual_mg` e `estadual_sp`, ambos executados no Chromium do servidor sem abrir Edge local.
- Criados `estadual_mg.py` e `estadual_sp.py` com preenchimento de CNPJ, deteccao de CAPTCHA/login/indisponibilidade, captura de PDF por download/resposta/popup ou impressao da pagina, e validacao com `pypdf`.
- Integrados MG/SP em `consultations.py`, `app.py`, `static/app.js`, `static/index.html`, `tests/test_app.py` e `tests/browser_smoke.py`.
- Criado `tests/test_estadual.py` com parsers MG/SP, rejeicoes controladas, fluxo Playwright simulado em Chromium e bloqueio de CAPTCHA.
- Reader mapeou os portais oficiais MG/SP; Writer criou o teste inicial; Reviewer apontou riscos de seletores genericos e captura de PDF ampla, ajustados com seletores mais restritos, filtro de host e consumo de multiplos PDFs.

## Validacao

- `git diff --check` executado nos arquivos alterados sem erros; apenas avisos esperados de LF/CRLF.
- `python`, `py` e `python3` nao estao disponiveis no PATH desta sessao, entao a suite `unittest`, o smoke test Playwright e comandos Docker nao puderam ser executados localmente.
- Para falencia/concordata, `git diff --check` tambem foi executado sem erros; `docker` tambem nao esta disponivel no PATH desta sessao.
- Para estaduais MG/SP, `git diff --check -- app.py consultations.py estadual_mg.py estadual_sp.py static/app.js static/index.html tests/test_estadual.py tests/test_app.py tests/browser_smoke.py README.md docs/escopo.md` executou sem erros, com apenas avisos LF/CRLF.
- `python -m unittest discover -s tests -v` e `python tests/browser_smoke.py` foram executados, mas falharam porque `python` nao esta no PATH desta sessao.
- `docker compose config` foi executado, mas falhou porque `docker` nao esta no PATH desta sessao.

## Pendente

- Rodar `python -m unittest discover -s tests -v` em ambiente com Python.
- Rodar `python tests/browser_smoke.py` em ambiente com Playwright/Edge disponivel para cobrir a interface completa.
- Validar manualmente a tentativa real da CNDT nos modos `local-edge` e `server`, conforme a atualizacao de 2026-09-14.
- Validar manualmente a tentativa real do RUPE/TJMG no Chromium do servidor com os dados judiciais preenchidos, confirmando que dados faltantes ou codigo invalido encerram sem abrir Edge.
- Validar manualmente as tentativas reais da CDT MG e da eCND SP no Chromium do servidor; CAPTCHA, SIARE, certificado, e-CNPJ/e-CPF ou SIPET devem encerrar com status identificado, sem abrir Edge.
- Se o cliente exigir a certidao de divida ativa da PGE/SP, criar um servico separado para esse portal.
