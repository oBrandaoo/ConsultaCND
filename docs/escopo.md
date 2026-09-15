# Escopo do MVP hospedado

O produto recebe um CNPJ e entrega, quando os portais permitem, uma prévia no site e o PDF original ou impresso validado da certidão federal da Receita Federal/PGFN, do CRF do FGTS, da CNDT trabalhista, da certidão de falência e concordata do TJMG, das CNDs estaduais de MG/SP e das CNDs municipais de Santa Rita do Sapucaí e Congonhal.

- Entrada: um CNPJ válido e uma ou mais certidões.
- Abrangência: federal, FGTS e trabalhista para todo o Brasil; falência/concordata e CDT estadual em Minas Gerais; eCND estadual em São Paulo; municipais fixas em Santa Rita do Sapucaí e Congonhal, sem seletor de cidades.
- Execução: fila com um worker e navegador Chromium no servidor.
- Retorno federal: segunda via de uma certidão vigente ou nova emissão, com validação do PDF.
- Retorno FGTS: consulta pública do CRF com validação do PDF impresso.
- Retorno trabalhista: tentativa automática da CNDT, com validação do PDF quando o TST não exige CAPTCHA; no modo Windows `local-edge`, a consulta pode aguardar o operador preencher o CAPTCHA no Edge e continuar depois da emissão.
- Retorno falência/concordata: tentativa automática no RUPE/TJMG com os dados judiciais informados no formulário, com validação do PDF quando o portal conclui a solicitação.
- Retorno estadual MG: tentativa automática da CDT da SEF/MG no Chromium do servidor, com validação do PDF quando o portal não exige SIARE, login ou certificado.
- Retorno estadual SP: tentativa automática da eCND de débitos tributários não inscritos da Sefaz/SP, com validação do PDF quando o portal não exige e-CNPJ, e-CPF ou SIPET; no modo Windows `local-edge`, a consulta pode aguardar o operador preencher o CAPTCHA no Edge e continuar depois da emissão.
- Retorno municipal: emissão e validação do PDF de Santa Rita do Sapucaí e tentativa automática da CND de Congonhal, usando nome e CPF do usuário solicitante quando Congonhal estiver selecionada, com entrega somente após validação do PDF.
- Retenção: resultados e PDFs em memória por até 30 minutos.
- Interface: toda certidão encontrada exibe prévia do PDF validado no card de resultado e mantém o download disponível.
- Capacidade inicial: até 100 consultas aguardando, processadas em sequência.
- Custo externo por consulta: nenhum.

O hCaptcha invisível da consulta federal, a validação visual da CNDT, os dados obrigatórios do RUPE/TJMG e eventuais validações/login dos portais estaduais podem recusar ou impedir uma sessão automatizada. O worker não resolve nem contorna desafios; quando a CNDT ou a eCND estadual SP rodam em Edge local, ele só aguarda a digitação humana do CAPTCHA e valida o PDF gerado. Nos demais casos, registra a falha ou a pendência sem concluir que o CNPJ está regular ou irregular.

O container deve operar como uma única instância. Escala horizontal exige uma fila e um armazenamento compartilhados, que não fazem parte deste MVP.

Ficam fora do escopo: municípios diferentes de Santa Rita do Sapucaí e Congonhal, certidão de dívida ativa da PGE/SP, importação em lote, agendamento, alertas, histórico permanente e autenticação própria. O acesso ao site hospedado deve ser protegido pelo provedor ou proxy HTTPS.
