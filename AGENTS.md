
# CND Automático

Objetivo

Sistema de geração de CNDs automático.

## Tecnologias

### Frontend

- HTML5
- CSS3
- JavaScript (ES6+), sem framework ou etapa de build
- Fetch API e Web Storage (`sessionStorage`)

### Backend

- Python 3
- Servidor HTTP da biblioteca padrão (`ThreadingHTTPServer`)
- Concorrência com `asyncio`, threads e fila em memória
- Playwright para automação do Chromium e do Microsoft Edge
- `pypdf` para leitura e validação de certidões em PDF
- Persistência temporária em memória, sem banco de dados

### Infraestrutura e testes

- Docker e Docker Compose
- Xvfb para executar o Chromium em modo completo no container Linux
- `unittest` para testes automatizados
- PowerShell para os scripts de prévia local no Windows

## Estrutura

- `app.py`: servidor HTTP, API e entrega dos arquivos estáticos
- `consultations.py`: validação, fila em memória e coordenação das consultas
- `browser_worker.py`: inicialização e gerenciamento do Chromium ou Edge
- `federal.py`, `fgts.py` e `santa_rita.py`: automação e validação de cada portal
- `static/`: frontend em HTML, CSS e JavaScript
- `tests/`: testes unitários, de integração e smoke test do navegador
- `scripts/`: scripts PowerShell e CMD para iniciar ou encerrar a prévia no Windows
- `docs/`: documentação complementar do projeto
- `Dockerfile` e `compose.yaml`: empacotamento e execução em container

## Comandos de validação

### Testes automatizados

- `python -m unittest discover -s tests -v`

### Smoke test no navegador

- `python tests/browser_smoke.py`

### Container

- `docker compose config`
- `docker compose build`

## Regras

- Não modificar arquivos fora do escopo atribuído.
- Não criar migrations destrutivas sem aprovação.
- Não remover código existente para esconder erros.
- Preservar os padrões encontrados no projeto.
- Executar lint, build e testes relacionados antes de concluir.
- Não incluir senhas, tokens ou arquivos `.env` em commits.

## Coordenação

- O Maestro distribui as tarefas.
- O Bulk Reader nunca modifica arquivos.
- O Code Writer só modifica destinos autorizados.
- O Reviewer inicialmente apenas revisa.
- Dois agentes não devem editar o mesmo arquivo simultaneamente.
