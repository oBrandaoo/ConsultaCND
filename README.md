# Certifica — consulta de CNDs

Ferramenta local dedicada a consultas pontuais. Informe CNPJ e município, selecione os órgãos e inicie a consulta. Não há cadastro de empresas, carteira, importação, upload de documentos, histórico permanente ou agenda.

## Executar

Requer Python 3.11+ e Microsoft Edge instalado.

```powershell
python -m pip install --target .tools -r requirements.txt
python app.py
```

Abra **http://127.0.0.1:8000**. Para outra porta, use `python app.py --port 8001`. Encerre com Ctrl+C.

## O que está implementado

- Validação de CNPJ numérico/alfanumérico e seleção das cinco certidões.
- Consulta federal experimental: acessa o formulário público da Receita, preenche e confere o CNPJ, aciona **Consultar Certidão** e interpreta conservadoramente o retorno.
- Nos demais órgãos, verifica o acesso ao portal e aponta login, CAPTCHA, bloqueio, indisponibilidade ou necessidade de consulta manual. **Isso não equivale a consultar a situação fiscal.**
- Resultados temporários na tela, com horário, distinção entre envio da consulta e verificação de acesso, e mensagem do órgão quando identificada.
- Link explícito para continuar manualmente no portal e botão para copiar CNPJ.
- Uma consulta por vez, com no máximo dois acessos aos órgãos em paralelo e sem repetição automática de submissões.

A consulta federal procura certidões já emitidas. Não solicita nova emissão nem garante retorno de PDF. Download e emissão, quando necessários, são feitos no portal. Certidões localizadas podem estar vencidas.

## Situação das integrações em 07/09/2026

| Órgão | Estado real da implementação |
|---|---|
| Receita / PGFN | Consulta pública automatizada experimental. Testada com 18.192.898/0001-02: o CNPJ foi submetido e o órgão retornou aviso 023, sem concluir a consulta. Nenhuma certidão foi confirmada nesse teste. |
| CAIXA / FGTS | Acesso automatizado bloqueado no ambiente de teste. Consulta por CNPJ ainda não integrada. |
| SEF/MG | Portal atual CDT exige login gov.br. A ferramenta abre o link para conclusão manual; não captura credenciais. |
| Santa Rita do Sapucaí | Endereço oficial anteriormente identificado não respondeu no ambiente. Consulta municipal não integrada. |
| Pouso Alegre / Itajubá | Acesso ao portal; consulta por CNPJ ainda não integrada nem validada com contribuinte desses municípios. |
| TJMG | Formulário público requer dados complementares. Pedido e emissão ainda manuais. |

**Automação completa das cinco consultas ainda não foi entregue.** A interface foi corrigida para consultas apenas, e o envio federal foi implementado. Não existe resultado simulado no aplicativo; as simulações são exclusivas dos testes.

Correção do levantamento anterior: a [página antiga da SEF/MG](https://www.fazenda.mg.gov.br/empresas/certidao_debitos/) ainda descrevia emissão sem login, mas seu link de serviço encaminha à [orientação atual de CDT](https://atendimento2.fazenda.mg.gov.br/csm?sys_kb_id=3c9a4c69fb344b90a41cf40d4eefdc5c&id=kb_article_view), que informa autenticação gov.br obrigatória, e ao [portal CDT](https://cdt.fazenda.mg.gov.br/). Não usar a orientação antiga para planejar essa integração.

As regras de dígito verificador seguem o [manual da Receita Federal](https://www.gov.br/receitafederal/pt-br/centrais-de-conteudo/publicacoes/documentos-tecnicos/cnpj/manual-dv-cnpj.pdf). Validar os dígitos não confirma a existência ou a situação cadastral.

## Operação

O aplicativo escuta apenas em 127.0.0.1 e usa proteção de origem nas escritas. Não tem autenticação multiusuário e não deve ser exposto por túnel ou servidor público.

Os resultados ficam em memória por até 30 minutos (máximo de 20 consultas recentes) e somem ao reiniciar o servidor. O navegador guarda apenas o identificador temporário da consulta em sessionStorage para recuperar a tela após recarregar. Não há armazenamento de senhas, certificados ou PDFs. O banco da versão anterior não é acessado nem alterado.

A versão anterior de gestão foi preservada em `.runtime/gestao-anterior/` durante a correção de escopo. Esse diretório é local e ignorado pelo Git.

## Testes

```powershell
python -m unittest discover -s tests -v
python tests/browser_smoke.py
```

Os testes automatizados usam respostas controladas e não consultam terceiros. O teste real com o CNPJ indicado pelo usuário é documentado acima. Falhas de acesso não são resultados fiscais, e nenhuma certidão é declarada negativa apenas por carregar um formulário.

