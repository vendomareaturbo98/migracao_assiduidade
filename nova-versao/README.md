# Sistema de Assiduidade — nova versão

Esta pasta contém a reconstrução gradual do Sistema de Assiduidade com Java, Spring Boot e React.

## Princípios
- A aplicação Streamlit existente permanece intacta.
- Esta versão trabalha inicialmente sem conexão com o banco de produção.
- O frontend conversa exclusivamente com a API Java.
- O PostgreSQL será conectado somente após levantamento e validação do esquema.
- As regras de negócio existentes devem ser preservadas e cobertas por testes.

## Estrutura
- `backend/`: API Java + Spring Boot.
- `frontend/`: interface administrativa React.
- `confirmacao-presenca/`: página leve de confirmação, integrada à mesma API.
- `docs/`: arquitetura, regras e decisões técnicas.

## Requisitos locais
- Java 21+
- Maven 3.9+
- Node.js LTS e npm

## Executar
Consulte os READMEs de `backend/` e `frontend/`. A API inicial expõe `GET /api/health`.
