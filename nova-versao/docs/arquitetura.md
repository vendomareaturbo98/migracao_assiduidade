# Arquitetura — nova versão

## Objetivo
Reconstruir o Sistema de Assiduidade em Java/Spring Boot e React, mantendo a página de confirmação leve e reutilizando as mesmas regras e serviços do backend.

## Componentes
- **Backend:** API REST Spring Boot. Centraliza autenticação, autorização, regras de negócio, validação e acesso a dados.
- **Frontend administrativo:** React + Vite. Não acessa PostgreSQL diretamente.
- **Confirmação:** HTML/CSS/JavaScript servido como página independente; consome endpoints específicos da mesma API.
- **Persistência:** PostgreSQL. O esquema definitivo será mapeado antes de criar entidades e migrações.
- **Migrações:** Flyway, após validar o esquema real e definir o banco de desenvolvimento.

## Isolamento
A implementação está em `nova-versao/` e na branch `migracao-java-react-2026-11-13`. Não substituir, remover ou alterar os arquivos Streamlit existentes. Não conectar esta versão ao banco de produção durante a construção.

## Segurança
- Segredos apenas em variáveis de ambiente/gerenciador de segredos.
- Nenhuma chave privilegiada no navegador.
- Confirmação de presença por token aleatório, com validade e validação no servidor.
- A matrícula não deve ser tratada como segredo ou prova de identidade.
- CORS restrito às origens autorizadas.
- Autenticação e autorização serão implementadas antes de liberar operações administrativas.

## Próximas decisões
1. Inventariar todas as tabelas, colunas, constraints, índices e dados existentes.
2. Definir ambiente PostgreSQL isolado para desenvolvimento.
3. Desenhar modelo relacional e migrações Flyway.
4. Implementar autenticação e perfis.
5. Migrar os módulos por etapas, comparando resultados com o sistema atual.
6. Avaliar integração com UPG somente após confirmar APIs e mecanismo de autenticação disponíveis.
