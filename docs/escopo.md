# Escopo do MVP hospedado

O produto recebe um CNPJ e entrega, quando os portais permitem, o PDF original da certidão federal da Receita Federal/PGFN, do CRF do FGTS, da CNDT trabalhista, da certidão de falência e concordata do TJMG, das CNDs estaduais de MG/SP e da CND municipal de Santa Rita do Sapucaí.

- Entrada: um CNPJ válido e uma ou mais certidões.
- Abrangência: federal, FGTS e trabalhista para todo o Brasil; falência/concordata e CDT estadual em Minas Gerais; eCND estadual em São Paulo; municipal fixa em Santa Rita, sem seletor de cidades.
- Execução: fila com um worker e navegador Chromium no servidor.
- Retorno federal: segunda via de uma certidão vigente ou nova emissão, com validação do PDF.
- Retorno FGTS: consulta pública do CRF com validação do PDF impresso.
- Retorno trabalhista: tentativa automática da CNDT, com validação do PDF quando o TST não exige CAPTCHA; no modo Windows `local-edge`, a consulta pode aguardar o operador preencher o CAPTCHA no Edge e continuar depois da emissão.
- Retorno falência/concordata: tentativa automática no RUPE/TJMG com os dados judiciais informados no formulário, com validação do PDF quando o portal conclui a solicitação.
- Retorno estadual MG: tentativa automática da CDT da SEF/MG no Chromium do servidor, com validação do PDF quando o portal não exige SIARE, login ou certificado.
- Retorno estadual SP: tentativa automática da eCND de débitos tributários não inscritos da Sefaz/SP no Chromium do servidor, com validação do PDF quando o portal não exige e-CNPJ, e-CPF ou SIPET.
- Retorno municipal: emissão e validação do PDF de Santa Rita.
- Retenção: resultados e PDFs em memória por até 30 minutos.
- Capacidade inicial: até 100 consultas aguardando, processadas em sequência.
- Custo externo por consulta: nenhum.

O hCaptcha invisível da consulta federal, a validação visual da CNDT, os dados obrigatórios do RUPE/TJMG e eventuais validações/login dos portais estaduais podem recusar ou impedir uma sessão automatizada. O worker não resolve nem contorna desafios; quando a CNDT roda em Edge local, ele só aguarda a digitação humana do CAPTCHA e valida o PDF gerado. Nos demais casos, registra a falha ou a pendência sem concluir que o CNPJ está regular ou irregular.

O container deve operar como uma única instância. Escala horizontal exige uma fila e um armazenamento compartilhados, que não fazem parte deste MVP.

Ficam fora do escopo: outros municípios, certidão de dívida ativa da PGE/SP, importação em lote, agendamento, alertas, histórico permanente e autenticação própria. O acesso ao site hospedado deve ser protegido pelo provedor ou proxy HTTPS.
