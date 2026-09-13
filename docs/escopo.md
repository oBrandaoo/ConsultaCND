# Escopo do MVP hospedado

O produto recebe um CNPJ e entrega, quando os portais permitem, o PDF original da certidão federal da Receita Federal/PGFN, do CRF do FGTS, da CNDT trabalhista e da CND municipal de Santa Rita do Sapucaí.

- Entrada: um CNPJ válido e uma ou mais certidões.
- Abrangência: federal, FGTS e trabalhista para todo o Brasil; municipal fixa em Santa Rita, sem seletor de cidades.
- Execução: fila com um worker e navegador Chromium no servidor.
- Retorno federal: segunda via de uma certidão vigente ou nova emissão, com validação do PDF.
- Retorno FGTS: consulta pública do CRF com validação do PDF impresso.
- Retorno trabalhista: emissão assistida da CNDT quando o TST exige validação visual, com validação do PDF.
- Retorno municipal: emissão e validação do PDF de Santa Rita.
- Retenção: resultados e PDFs em memória por até 30 minutos.
- Capacidade inicial: até 100 consultas aguardando, processadas em sequência.
- Custo externo por consulta: nenhum.

O hCaptcha invisível da consulta federal e a validação visual da CNDT podem recusar ou pausar uma sessão automatizada. O worker não resolve nem contorna desafios; nesses casos, registra a falha ou aguarda o usuário no modo assistido sem concluir que o CNPJ está regular ou irregular.

O container deve operar como uma única instância. Escala horizontal exige uma fila e um armazenamento compartilhados, que não fazem parte deste MVP.

Ficam fora do escopo: outros municípios, CND estadual, falência e concordata, importação em lote, agendamento, alertas, histórico permanente e autenticação própria. O acesso ao site hospedado deve ser protegido pelo provedor ou proxy HTTPS.
