# Estado do projeto - 2026-09-13

## Concluido

- Implementada a integracao da CNDT trabalhista como servico `trabalhista`.
- Criado `trabalhista.py` com fluxo Playwright assistido para o portal do TST, deteccao de CAPTCHA, captura de PDF por download, resposta PDF, popup ou impressao da pagina, e validacao com `pypdf`.
- Atualizados `consultations.py` e `app.py` para listar, executar e servir PDFs da CNDT.
- Atualizada a interface em `static/app.js` e `static/index.html` para exibir a CNDT trabalhista.
- Criados testes controlados em `tests/test_trabalhista.py` e ampliados `tests/test_app.py` e `tests/browser_smoke.py`.
- Atualizados `README.md` e `docs/escopo.md` com o novo escopo e a dependencia de validacao visual no TST.
- Bulk Reader analisou pontos de extensao; Code Writer criou o teste inicial; Reviewer revisou e apontou ajustes de download/import, ja incorporados.

## Validacao

- `git diff --check` executado nos arquivos alterados sem erros; apenas avisos esperados de LF/CRLF.
- `python`, `py` e `python3` nao estao disponiveis no PATH desta sessao, entao a suite `unittest`, o smoke test Playwright e comandos Docker nao puderam ser executados localmente.

## Pendente

- Rodar `python -m unittest discover -s tests -v` em ambiente com Python.
- Rodar `python tests/browser_smoke.py` em ambiente com Playwright/Edge disponivel.
- Validar manualmente o fluxo real da CNDT no modo `local-edge`, resolvendo o CAPTCHA do TST no Edge.
