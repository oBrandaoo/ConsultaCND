# Estado do projeto - 2026-09-13

## Concluido

- Implementada a integracao da CNDT trabalhista como servico `trabalhista`.
- Criado `trabalhista.py` com fluxo Playwright assistido para o portal do TST, deteccao de CAPTCHA, captura de PDF por download, resposta PDF, popup ou impressao da pagina, e validacao com `pypdf`.
- Atualizados `consultations.py` e `app.py` para listar, executar e servir PDFs da CNDT.
- Atualizada a interface em `static/app.js` e `static/index.html` para exibir a CNDT trabalhista.
- Criados testes controlados em `tests/test_trabalhista.py` e ampliados `tests/test_app.py` e `tests/browser_smoke.py`.
- Atualizados `README.md` e `docs/escopo.md` com o novo escopo e a dependencia de validacao visual no TST.
- Bulk Reader analisou pontos de extensao; Code Writer criou o teste inicial; Reviewer revisou e apontou ajustes de download/import, ja incorporados.
- Implementada a CND de falencia e concordata como servico `falencia`, com fluxo assistido no RUPE/TJMG.
- Criado `falencia.py` com preenchimento seguro do que pode ser inferido pelo CNPJ, espera ativa para usuario completar comarca/nome/solicitante/codigo de verificacao no Edge, captura de PDF por download/resposta/popup ou impressao da pagina, e validacao com `pypdf`.
- Criados testes controlados em `tests/test_falencia.py` e ampliados `tests/test_app.py` e `tests/browser_smoke.py` para o novo servico.
- Atualizados `README.md`, `docs/escopo.md`, `static/app.js` e `static/index.html` para exibir o servico judicial e documentar os dados obrigatorios do RUPE/TJMG.
- Reader revisou o contrato do RUPE/TJMG; Writer criou os testes iniciais; Reviewer apontou que `aguardando_usuario` nao podia encerrar o browser, e o fluxo foi corrigido para aguardar o PDF antes de finalizar.

## Validacao

- `git diff --check` executado nos arquivos alterados sem erros; apenas avisos esperados de LF/CRLF.
- `python`, `py` e `python3` nao estao disponiveis no PATH desta sessao, entao a suite `unittest`, o smoke test Playwright e comandos Docker nao puderam ser executados localmente.
- Para falencia/concordata, `git diff --check` tambem foi executado sem erros; `docker` tambem nao esta disponivel no PATH desta sessao.

## Pendente

- Rodar `python -m unittest discover -s tests -v` em ambiente com Python.
- Rodar `python tests/browser_smoke.py` em ambiente com Playwright/Edge disponivel.
- Validar manualmente o fluxo real da CNDT no modo `local-edge`, resolvendo o CAPTCHA do TST no Edge.
- Validar manualmente o fluxo real do RUPE/TJMG no modo `local-edge`, completando comarca, nome exato, dados do solicitante e codigo de verificacao ate a geracao do PDF.
