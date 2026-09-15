# Certifica — CND federal, FGTS, CNDT, estaduais MG/SP e municipais

Aplicação web para emitir ou baixar a segunda via da certidão federal da Receita Federal/PGFN, consultar o CRF do FGTS na Caixa, emitir a CNDT trabalhista no TST, solicitar a certidão de falência e concordata no TJMG, emitir CNDs estaduais de MG/SP e emitir CNDs municipais de Santa Rita do Sapucaí e Congonhal. O usuário informa o CNPJ, inicia a consulta e recebe a prévia do PDF na própria página, com opção de download, quando o portal libera a emissão.

## Prévia gratuita imediata no Windows

O script abaixo publica a aplicação por uma URL HTTPS temporária do `localhost.run`, sem cadastro. Ele inicia o servidor e o túnel como processos ocultos, gera uma senha para a execução e grava a URL atual em `.runtime/preview-url.txt`:

```powershell
.\scripts\start-free-preview.cmd
```

Para encerrar os dois processos:

```powershell
.\scripts\stop-free-preview.cmd
```

O computador precisa permanecer ligado e conectado. A URL gratuita muda quando o túnel é reiniciado, tem velocidade limitada e deve ser usada somente para demonstração. O usuário e a senha aparecem no terminal após a inicialização.

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
5. O PDF recebido ou impresso pelo navegador é conferido antes de ser liberado.
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
| `CERTIFICA_PROFILE_DIR` | `/data/browser-profile` | Perfil técnico persistente do Chromium nacional. |
| `CERTIFICA_LOCAL_EDGE_PROFILE_DIR` | `.runtime/local-edge-profile` | Perfil persistente do Edge usado no modo assistido do Windows. |
| `CERTIFICA_BASIC_USER` e `CERTIFICA_BASIC_PASSWORD` | vazios | Protegem a aplicação com autenticação HTTP quando definidos juntos. |

O endpoint `GET /healthz` pode ser usado pelo provedor para verificar a saúde do container.

## Desenvolvimento no Windows

```powershell
python -m pip install --user -r requirements.txt
python app.py
```

Abra `http://127.0.0.1:8000`. Nesse modo, Receita, Caixa, CNDT trabalhista e eCND estadual SP podem usar o Microsoft Edge local com um perfil persistente. Se o TST ou a Sefaz/SP pedirem caracteres de imagem, a consulta fica aguardando o operador preencher o CAPTCHA na janela do Edge e clicar em emitir/consultar; depois disso, a ferramenta tenta capturar e validar o PDF automaticamente. Falência/concordata e estadual MG rodam no Chromium do servidor, sem abrir Edge; se TJMG, SEF/MG ou Sefaz/SP exigirem código de verificação, login/certificado ou dados que não foram informados, a tentativa termina com status identificado e link para o portal.

Esse é o modo gratuito recomendado para a operação do contador. Para reproduzir o servidor totalmente oculto, instale o Chromium do Playwright e defina as variáveis correspondentes:

```powershell
python -m playwright install chromium
$env:CERTIFICA_BROWSER_MODE='server'
$env:CERTIFICA_HEADLESS='true'
python app.py
```

Se aparecer `No module named 'playwright.async_api'`, instale as dependências usando exatamente o mesmo executável `python` que inicia o aplicativo.

## Consultas

- **Federal:** válida para CNPJs de qualquer cidade. O worker solicita emissão; quando já existe uma certidão válida, obtém a segunda via. O PDF só é entregue após conferir CNPJ, Receita/PGFN, tipo, controle e datas.
- **FGTS:** consulta o CRF público da Caixa com o CNPJ completo, confirma a declaração de regularidade, o número e a validade e imprime a página oficial em PDF.
- **Trabalhista:** abre a emissão pública da CNDT no TST, preenche o CNPJ e tenta emitir automaticamente. No Windows em `local-edge`, se o portal exigir CAPTCHA, a consulta aguarda a digitação humana dos caracteres na janela do Edge e continua após o operador clicar em emitir. No Docker/servidor, onde não há janela interativa para o usuário, o CAPTCHA encerra a tentativa com status identificado. O PDF só é entregue após conferir CNPJ, tipo, número e validade.
- **Falência e concordata:** abre o RUPE/TJMG no Chromium do servidor, usa os dados judiciais informados no formulário e tenta solicitar a certidão cível. Se faltarem comarca, nome exato, dados do solicitante ou código de verificação, a consulta termina sem abrir Edge. O PDF só é entregue após conferir CNPJ, tipo, número, comarca e validade.
- **Estadual MG:** tenta emitir a CDT pública da SEF/MG no Chromium do servidor e entrega o PDF somente após conferir CNPJ, órgão emissor, declaração, número e validade. Quando a SEF/MG exige SIARE, login ou certificado, o status informa a pendência sem abrir Edge.
- **Estadual SP:** tenta emitir a eCND de débitos tributários não inscritos da Sefaz/SP e entrega o PDF somente após conferir CNPJ, órgão emissor, declaração, número e validade. No Windows em `local-edge`, se a Sefaz/SP exigir CAPTCHA, a consulta aguarda a digitação humana no Edge e continua após o operador clicar em emitir/consultar. Pendências que exigem e-CNPJ, e-CPF, SIPET ou atendimento pela PGE ficam sinalizadas como login/manual.
- **Santa Rita do Sapucaí:** usa o fluxo público da prefeitura e confere o PDF municipal antes de entregá-lo.
- **Congonhal:** usa o fluxo público Prefeitura Moderna/IPTU e Outros Débitos, tenta emitir a CND municipal por CNPJ e exige nome e CPF do usuário solicitante. Esses dados são usados somente na consulta em andamento. O PDF só é entregue após conferir CNPJ, município, declaração negativa, número/controle e validade.

O portal federal usa hCaptcha invisível. Normalmente ele é resolvido em segundo plano, mas pode recusar a sessão ou apresentar um desafio. A aplicação não tenta contornar essa proteção e não transforma falha de acesso em conclusão fiscal. Uma consulta recusada termina com a causa identificada e pode ser refeita posteriormente.

O portal do FGTS usa uma proteção antifraude que bloqueia navegadores ocultos em algumas redes. No modo gratuito `local-edge`, a consulta usa uma janela normal do Edge com perfil persistente. No Docker, um bloqueio é informado sem concluir que a empresa possui pendências.

O portal da CNDT trabalhista pode exigir caracteres exibidos em imagem. A aplicação não tenta resolver nem contornar essa proteção; quando há Edge local, apenas aguarda a digitação humana e segue com a validação do PDF. Sem uma janela interativa, a exigência de CAPTCHA encerra a tentativa com status identificado.

O RUPE/TJMG exige campos que não podem ser inferidos só pelo CNPJ, incluindo comarca, nome exatamente igual ao cadastro pesquisado, dados do solicitante e código de verificação. Esses dados são usados somente na consulta em andamento, não aparecem no retorno da API e não são persistidos.

As consultas estaduais usam os portais oficiais indicados pela SEF/MG e pela Sefaz/SP. Para SP, esta versão cobre a eCND de débitos não inscritos; a certidão de dívida ativa da PGE/SP é um portal separado e deve ser adicionada como novo serviço se o fluxo operacional exigir essa certidão também. A aplicação não resolve nem contorna CAPTCHA da Sefaz/SP; no Edge local, apenas aguarda a digitação humana e valida o PDF gerado.

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

Os testes automatizados usam respostas controladas. Os conectores também foram verificados nos portais reais: Santa Rita emitiu e validou o PDF municipal; a consulta federal localizou uma certidão vigente, solicitou a segunda via e validou o PDF retornado; e o FGTS confirmou um CRF vigente da própria Caixa e gerou o PDF validado. A CNDT trabalhista, a certidão de falência/concordata, as estaduais MG/SP e Congonhal possuem cobertura automatizada simulada e dependem de validação visual em uso real.
