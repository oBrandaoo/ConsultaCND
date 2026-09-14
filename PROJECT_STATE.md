# Estado do projeto

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
