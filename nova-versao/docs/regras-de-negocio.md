# Regras de negócio a preservar

Este documento é a referência inicial para a migração. Cada regra deverá ganhar testes automatizados antes da troca do sistema atual.

## Colaboradores
- Público atual: enfermeiros e técnicos de enfermagem, conforme a configuração do sistema.
- Importação de planilha com Nome, Matrícula e Cargo Efetivo.
- Normalização de nome para identificar duplicidades.
- Se houver duplicidade com registros RJU e não-RJU, excluir o registro RJU conforme regra vigente.
- Se a duplicidade permanecer ambígua, marcar para revisão; não importar automaticamente.
- Preservar matrícula para conferência e rastreabilidade.

## Treinamentos
- Cadastro, edição e alteração de situação.
- Treinamento pode ocorrer em um ou dois dias.
- Edição de informações não pode apagar ou desvincular presenças históricas.
- Treinamentos cancelados e pendentes não entram indevidamente nos cálculos de assiduidade.
- Elegibilidade e inclusão manual de participante devem continuar respeitadas.

## Presenças
- Para treinamento de dois dias, registrar presença do primeiro e do segundo dia.
- A participação consolidada é positiva se a pessoa compareceu em pelo menos um dos dias.
- Um treinamento conta como uma participação, mesmo quando ocorre em dois dias.
- Afastamento que coincida com a data do treinamento não deve ser contado como ausência.
- Ausência, presença, pendência e afastamento devem permanecer distinguíveis.

## Monitoramento
- Faixa de monitoramento: taxa de presença menor ou igual a 30%.
- Taxa = presenças / (presenças + ausências) × 100.
- Pendências, treinamentos cancelados e afastamentos ficam fora do denominador.
- Treinamento de dois dias conta uma única vez.

## Histórico e relatórios
- Histórico individual deve mostrar taxa, presenças, ausências, pendências e evolução.
- Relatórios coletivos incluem análises e gráficos equivalentes aos painéis atuais.
- Dados individuais devem permanecer disponíveis em formato tabular; não é necessário gráfico individual no Excel.

## Afastamentos
- Registrar tipo administrativo, período e observação quando necessária.
- Tipos incluem férias, licença saúde, maternidade/paternidade e outros.
- Não solicitar diagnóstico ou CID.

## Participantes externos e documento ANEXO 0185
- Presenças confirmadas de participantes internos e externos devem aparecer na mesma lista do documento.
- No cabeçalho do documento, preencher somente o campo Atividade; demais campos e assinaturas ficam em branco.
- Interno com cargo terminado em RJU: setor UCM/MI; vínculo UFU.
- Interno sem final RJU: setor UCM/MI; vínculo EBSERH.
- Externo: setor UFU; vínculo UFU.
- Manter o modelo e ampliar linhas conforme o número de participantes.

## Segurança e dados
- Não armazenar diagnóstico/CID.
- Não expor segredos no frontend ou no repositório.
- Não executar migração nem escrita no banco de produção nesta fase.
