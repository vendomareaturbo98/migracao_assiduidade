# Sistema de Assiduidade — migração para PostgreSQL

Este pacote prepara duas aplicações Streamlit para usar **o mesmo PostgreSQL**: `App.py` (administração) e `confirmar_presenca.py` (colaboradores). O script `migrar_sqlite_para_postgres.py` copia os dados do SQLite existente sem alterar o arquivo original.

## Antes de começar

1. **Não apague nem mova o banco original.** Faça uma cópia de `dados/assiduidade.db`.
2. Crie um projeto PostgreSQL no Supabase ou use um PostgreSQL aprovado pela empresa.
3. No painel do banco, copie a URL de conexão PostgreSQL com SSL. Para o Supabase, use a URL do pooler de sessão se a conexão direta não estiver disponível no ambiente de hospedagem. A senha da URL pode precisar estar codificada para URL.
4. Não publique a URL nem a senha no GitHub, em prints ou no código.

## 1. Preparar o SQLite para a migração

Coloque `App.py`, `confirmar_presenca.py`, `db_postgres.py`, `migrar_sqlite_para_postgres.py` e `requirements.txt` na mesma pasta do projeto. Mantenha o banco original no caminho `dados/assiduidade.db` (ou informe outro caminho no comando abaixo).

Faça uma cópia do banco antes de continuar. Feche o sistema administrativo antes da cópia para evitar que uma gravação esteja em andamento.

## 2. Instalar dependências no computador

Abra o terminal nessa pasta e execute:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Se o Windows bloquear a ativação do ambiente virtual, você pode executar o `pip` pelo Python já instalado ou pedir ajuda ao suporte de TI; não altere políticas corporativas sem autorização.

## 3. Migrar para o PostgreSQL

A migração deve apontar para um **banco de destino vazio**. Ela interrompe o processo se encontrar registros nas tabelas de destino, para evitar duplicidades. Ela preserva os IDs e os relacionamentos e não modifica o SQLite original.

No PowerShell, execute:

```powershell
python migrar_sqlite_para_postgres.py
```

O script solicitará a URL do PostgreSQL com entrada oculta. Cole a URL de conexão e pressione Enter. Para um SQLite em outro caminho:

```powershell
python migrar_sqlite_para_postgres.py --sqlite "C:\caminho\para\assiduidade.db"
```

Guarde a mensagem final e os totais de cada tabela. Se a migração for interrompida, **não repita apontando para um banco que já tenha dados**: verifique os totais no painel do PostgreSQL primeiro. Se ocorreu erro, compartilhe a mensagem de erro sem incluir a URL ou senha.

## 4. Configurar os Secrets do Streamlit

Para cada aplicativo publicado, configure os Secrets no painel de configurações do Streamlit Community Cloud. Os dois apps precisam usar exatamente a mesma `DATABASE_URL`:

```toml
DATABASE_URL = "postgresql://USUARIO:SENHA@HOST:5432/postgres?sslmode=require"
```

No app administrativo (`App.py`), adicione também uma senha forte e exclusiva para os responsáveis:

```toml
ADMIN_PASSWORD = "SUBSTITUA_POR_UMA_SENHA_FORTE_E_EXCLUSIVA"
```

Use a URL real fornecida pelo provedor; o exemplo acima é ilustrativo. Não coloque o arquivo `secrets.toml` no GitHub. O `.gitignore` deste pacote já o exclui.

## 5. Publicar os aplicativos

1. Envie os arquivos Python e `requirements.txt` a um repositório privado do GitHub, conforme as regras de TI da empresa. Não inclua o banco `.db`, planilhas com dados pessoais, nem segredos.
2. No Streamlit Community Cloud, crie um app apontando para `App.py` e outro apontando para `confirmar_presenca.py`, ambos no mesmo repositório e branch.
3. Configure os Secrets separadamente em cada app. O administrativo precisa de `DATABASE_URL` e `ADMIN_PASSWORD`; o app de confirmação precisa de `DATABASE_URL`.
4. Teste os dois links usando Wi-Fi e dados móveis. Faça testes com um colaborador e um treinamento de teste antes de divulgar o link real.

## Segurança importante

- A página administrativa inclui um bloqueio por senha simples, mas isso não substitui autenticação corporativa, controle de acesso robusto ou uma revisão de segurança.
- A página de confirmação mantém o comportamento atual de identificar pela matrícula. **Matrícula não é um segredo** e, sozinha, não comprova a identidade. Antes de usar como registro oficial, avalie adicionar um código temporário ou outro fator de validação.
- Confirme com a empresa se é permitido hospedar dados de colaboradores em um serviço externo e quais requisitos de LGPD, backup, retenção e acesso são exigidos.
- O plano gratuito pode ter limites, pausa por inatividade e ausência de backups automáticos. Faça backups periódicos e teste a restauração.

## Observações técnicas

- `data`, `hora_inicio` e `hora_fim` permanecem como texto para manter o comportamento atual do sistema.
- As quatro tabelas existentes são mantidas: `colaboradores`, `treinamentos`, `elegibilidade` e `presencas`.
- `db_postgres.py` usa o adaptador `psycopg2` e mantém a interface de consulta/gravação usada pelo app atual.
- A migração preserva IDs explícitos e reajusta os contadores de identidade das tabelas `colaboradores` e `treinamentos`.
