# Certifica — CND federal e Santa Rita

Aplicação web para emitir ou baixar a segunda via da certidão federal da Receita Federal/PGFN e emitir a CND municipal de Santa Rita do Sapucaí. O usuário informa o CNPJ, inicia a consulta e recebe o PDF na própria página.

## Prévia gratuita imediata no Windows

O script abaixo publica a aplicação por uma URL HTTPS temporária do `localhost.run`, sem cadastro. Ele inicia o servidor e o túnel como processos ocultos e grava a URL atual em `.runtime/preview-url.txt`:

```powershell
.\scripts\start-free-preview.cmd
```

Para encerrar os dois processos:

```powershell
.\scripts\stop-free-preview.cmd
```

O computador precisa permanecer ligado e conectado. A URL gratuita muda quando o túnel é reiniciado, tem velocidade limitada e deve ser usada somente para demonstração. A prévia não possui login: qualquer pessoa com o endereço consegue iniciar consultas.

## Executar em um servidor com Docker

Requisitos: Docker Engine com Compose e pelo menos 1 GB de memória compartilhada disponível para o navegador.

No Windows, o Docker Desktop precisa de um backend de containers Linux ativo. Na configuração padrão, instale ou atualize o WSL 2 em um PowerShell executado como administrador e reinicie o Windows se solicitado antes de usar o Compose.

```bash
cp .env.example .env
docker compose up -d --build
```

Edite `CERTIFICA_ALLOWED_HOSTS` no `.env` e inclua o domínio real da aplicação. Para testar no próprio servidor, abra `http://localhost:8000`.

O container inclui Python, Playwright e Chromium. O Chromium roda em modo completo dentro do Xvfb, uma tela virtual Linux: nenhuma janela aparece no computador do usuário. O volume `browser-profile` preserva somente o perfil técnico do navegador entre consultas.

Em produção, publique a porta 8000 atrás de um proxy HTTPS e restrinja o acesso ao cliente no próprio provedor ou proxy. A aplicação valida o cabeçalho `Host`, exige origem compatível nas escritas e usa um token CSRF por processo.

## Arquitetura

1. O frontend envia o CNPJ para a API.
2. A API valida os dados e adiciona a consulta à fila em memória.
3. Um único worker processa as consultas na ordem recebida.
4. O worker abre Chromium no servidor e executa o formulário oficial.
5. O PDF recebido é conferido antes de ser liberado.
6. Resultado e PDF ficam em memória por 30 minutos e desaparecem ao reiniciar o container.

A fila aceita até 100 consultas aguardando por padrão. Usar um único worker evita várias emissões simultâneas contra os portais. Esta versão deve rodar como uma única instância; filas e resultados não são compartilhados entre réplicas.

## Configuração

| Variável | Padrão | Uso |
| --- | --- | --- |
| `PORT` | `8000` | Porta HTTP da aplicação. |
| `CERTIFICA_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Domínios aceitos, separados por vírgula e sem protocolo ou porta. |
| `CERTIFICA_MAX_QUEUE` | `100` | Consultas aguardando; aceita de 1 a 500. |
| `CERTIFICA_BROWSER_MODE` | `server` no container | `server` usa Chromium; `local-edge` usa Edge no Windows. |
| `CERTIFICA_HEADLESS` | `false` no container | Mantém o navegador completo dentro do Xvfb. |
| `CERTIFICA_PROFILE_DIR` | `/data/browser-profile` | Perfil técnico persistente do Chromium federal. |

O endpoint `GET /healthz` pode ser usado pelo provedor para verificar a saúde do container.

## Desenvolvimento no Windows

```powershell
python -m pip install --user -r requirements.txt
python app.py
```

Abra `http://127.0.0.1:8000`. Nesse modo, a consulta federal continua usando o Microsoft Edge local e visível para facilitar diagnóstico. Para reproduzir o servidor, instale o Chromium do Playwright e defina as variáveis correspondentes:

```powershell
python -m playwright install chromium
$env:CERTIFICA_BROWSER_MODE='server'
$env:CERTIFICA_HEADLESS='true'
python app.py
```

Se aparecer `No module named 'playwright.async_api'`, instale as dependências usando exatamente o mesmo executável `python` que inicia o aplicativo.

## Consultas

- **Federal:** válida para CNPJs de qualquer cidade. O worker solicita emissão; quando já existe uma certidão válida, obtém a segunda via. O PDF só é entregue após conferir CNPJ, Receita/PGFN, tipo, controle e datas.
- **Santa Rita do Sapucaí:** usa o fluxo público da prefeitura e confere o PDF municipal antes de entregá-lo.

O portal federal usa hCaptcha invisível. Normalmente ele é resolvido em segundo plano, mas pode recusar a sessão ou apresentar um desafio. A aplicação não tenta contornar essa proteção e não transforma falha de acesso em conclusão fiscal. Uma consulta recusada termina com a causa identificada e pode ser refeita posteriormente.

## Privacidade e operação

- Não solicita conta gov.br, senha ou certificado digital.
- Não grava CNPJ, resultado ou PDF em banco de dados.
- O perfil técnico persistente pode guardar cookies do portal, mas não credenciais do usuário.
- O PDF só é salvo no dispositivo quando o usuário seleciona o download.
- O serviço não possui API paga nem custo por certidão; a máquina ou plataforma que executa o container continua sendo necessária.

## Testes

```powershell
python -m unittest discover -s tests -v
python tests/browser_smoke.py
```

Os testes automatizados usam respostas controladas. Os conectores também foram verificados nos portais reais: Santa Rita emitiu e validou o PDF municipal; a consulta federal localizou uma certidão vigente, solicitou a segunda via e validou o PDF retornado.
