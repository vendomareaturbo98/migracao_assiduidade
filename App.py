import hmac
import os
import re
import unicodedata
from datetime import date, time

import pandas as pd
import psycopg2
import streamlit as st

from db_postgres import conectar, consultar, executar, inicializar_banco


# ======================================================
# CONFIGURAÇÃO E ACESSO ADMINISTRATIVO
# ======================================================

st.set_page_config(
    page_title="Sistema de Assiduidade",
    page_icon="📊",
    layout="wide",
)


def obter_senha_admin():
    senha = os.environ.get("ADMIN_PASSWORD", "").strip()
    if senha:
        return senha
    try:
        return str(st.secrets.get("ADMIN_PASSWORD", "")).strip()
    except Exception:
        return ""


senha_configurada = obter_senha_admin()
if not senha_configurada:
    st.title("📊 Sistema de Assiduidade")
    st.error(
        "A área administrativa está bloqueada. Configure ADMIN_PASSWORD "
        "nos Secrets da hospedagem antes de utilizar ou publicar este app."
    )
    st.stop()

if not st.session_state.get("admin_autenticado", False):
    st.title("🔐 Acesso administrativo")
    with st.form("form_login_admin"):
        senha_digitada = st.text_input("Senha administrativa", type="password")
        entrar = st.form_submit_button("Entrar", use_container_width=True)
    if entrar:
        if hmac.compare_digest(senha_digitada, senha_configurada):
            st.session_state["admin_autenticado"] = True
            st.rerun()
        else:
            st.error("Senha incorreta.")
    st.caption("Acesso exclusivo aos responsáveis pelo sistema.")
    st.stop()

# Cria as tabelas caso ainda não existam; não apaga dados existentes.
inicializar_banco()

# ======================================================
# FUNÇÕES DE TEXTO E CONSULTA
# ======================================================

def normalizar(valor):
    if pd.isna(valor):
        return ""

    texto = str(valor).strip().casefold()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(
        c for c in texto if not unicodedata.combining(c)
    )
    return re.sub(r"\s+", " ", texto)


def cabecalho_normalizado(valor):
    return re.sub(r"[^a-z0-9]", "", normalizar(valor))


def localizar_coluna(colunas, alternativas):
    mapa = {
        cabecalho_normalizado(c): c for c in colunas
    }

    for alternativa in alternativas:
        chave = cabecalho_normalizado(alternativa)
        if chave in mapa:
            return mapa[chave]

    return None


def listar_colaboradores(ativos=True):
    sql = """
        SELECT id, nome, matricula, cargo, ativo
        FROM colaboradores
    """
    if ativos:
        sql += " WHERE ativo = 1"
    sql += " ORDER BY nome"

    return consultar(sql)


def listar_treinamentos():
    return consultar("""
        SELECT *
        FROM treinamentos
        ORDER BY data DESC, hora_inicio DESC
    """)


# ======================================================
# IMPORTAÇÃO E TRATAMENTO DA PLANILHA
# ======================================================

def preparar_planilha(arquivo, aba=None):
    arquivo.seek(0)

    if arquivo.name.lower().endswith(".csv"):
        try:
            df = pd.read_csv(
                arquivo, dtype=str, sep=None, engine="python"
            )
        except UnicodeDecodeError:
            arquivo.seek(0)
            df = pd.read_csv(
                arquivo,
                dtype=str,
                sep=None,
                engine="python",
                encoding="latin-1",
            )
    else:
        df = pd.read_excel(
            arquivo,
            sheet_name=0 if aba is None else aba,
            dtype=str,
        )

    coluna_nome = localizar_coluna(
        df.columns, ["Nome", "Nome completo"]
    )
    coluna_matricula = localizar_coluna(
        df.columns, ["Matrícula", "Matricula"]
    )
    coluna_cargo = localizar_coluna(
        df.columns, ["Cargo Efetivo", "Cargo"]
    )

    if not all([coluna_nome, coluna_matricula, coluna_cargo]):
        raise ValueError(
            "A planilha precisa conter Nome, Matrícula e Cargo Efetivo."
        )

    base = pd.DataFrame({
        "Nome": df[coluna_nome].fillna("").astype(str).str.strip(),
        "Matrícula": (
            df[coluna_matricula].fillna("").astype(str).str.strip()
        ),
        "Cargo Efetivo": (
            df[coluna_cargo].fillna("").astype(str).str.strip()
        ),
    })

    base = base[base["Nome"] != ""].copy()
    base["Chave"] = base["Nome"].apply(normalizar)
    base["RJU"] = base["Cargo Efetivo"].str.contains(
        r"RJU\s*$", case=False, regex=True, na=False
    )

    excluidos = []
    ambiguos = []

    # A regra RJU só exclui registros quando há alternativa não RJU.
    for chave, grupo in base.groupby("Chave", sort=False):
        if len(grupo) <= 1:
            continue

        rju = grupo[grupo["RJU"]]
        nao_rju = grupo[~grupo["RJU"]]

        if len(rju) and len(nao_rju):
            excluidos.extend(rju.index.tolist())
        else:
            ambiguos.extend(grupo.index.tolist())

    base["Resultado"] = "Importável"
    base.loc[excluidos, "Resultado"] = (
        "Excluído: RJU com alternativa não RJU"
    )
    base.loc[ambiguos, "Resultado"] = "Revisar duplicidade"

    # Apenas nomes únicos após aplicar a regra são importados.
    elegiveis = base[~base.index.isin(excluidos)].copy()

    contagem = elegiveis["Chave"].value_counts()
    chaves_ambiguas = set(contagem[contagem > 1].index)

    elegiveis.loc[
        elegiveis["Chave"].isin(chaves_ambiguas), "Resultado"
    ] = "Revisar duplicidade"

    importaveis = elegiveis[
        ~elegiveis["Chave"].isin(chaves_ambiguas)
    ].copy()

    return base, importaveis, excluidos, ambiguos


# ======================================================
# INTERFACE
# ======================================================

st.title("📊 Sistema de Assiduidade")
st.caption("Educação Continuada | Banco de dados PostgreSQL na nuvem")

menu = st.sidebar.radio(
    "Navegação",
    [
        "Visão geral",
        "Colaboradores",
        "Treinamentos",
        "Presenças",
        "Relatórios",
    ],
)


# ======================================================
# VISÃO GERAL
# ======================================================

if menu == "Visão geral":
    colaboradores = listar_colaboradores()
    treinamentos = listar_treinamentos()

    total_colaboradores = len(colaboradores)
    total_treinamentos = len(treinamentos)

    realizados = (
        len(treinamentos[treinamentos["situacao"] == "Realizado"])
        if not treinamentos.empty else 0
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("Colaboradores ativos", total_colaboradores)
    c2.metric("Treinamentos cadastrados", total_treinamentos)
    c3.metric("Treinamentos realizados", realizados)

    st.subheader("Treinamentos cadastrados")

    if treinamentos.empty:
        st.info("Ainda não há treinamentos cadastrados.")
    else:
        st.dataframe(
            treinamentos[
                ["titulo", "data", "situacao", "publico"]
            ],
            hide_index=True,
            use_container_width=True,
        )

    st.info(
        "Os dados ficam salvos no banco SQLite local, "
        "mesmo após fechar o aplicativo."
    )


# ======================================================
# COLABORADORES
# ======================================================

elif menu == "Colaboradores":
    st.header("Cadastro de colaboradores")

    with st.expander("Importar planilha Excel ou CSV", expanded=True):
        arquivo = st.file_uploader(
            "Selecione a planilha",
            type=["xlsx", "xls", "csv"],
            key="planilha_colaboradores",
        )

        aba = None

        if arquivo and arquivo.name.lower().endswith(
            (".xlsx", ".xls")
        ):
            try:
                abas = pd.ExcelFile(arquivo).sheet_names
                if len(abas) > 1:
                    aba = st.selectbox("Aba da planilha", abas)
            except Exception:
                st.error("Não foi possível listar as abas.")

        if arquivo and st.button("Analisar planilha"):
            try:
                original, importaveis, excluidos, ambiguos = (
                    preparar_planilha(arquivo, aba)
                )

                st.session_state["importaveis"] = importaveis
                st.session_state["excluidos"] = original[
                    original.index.isin(excluidos)
                ]
                st.session_state["ambiguos"] = original[
                    original.index.isin(ambiguos)
                ]

                st.success(
                    f"{len(importaveis)} registro(s) prontos para importar."
                )

            except Exception as erro:
                st.error(str(erro))

        if "importaveis" in st.session_state:
            st.write("Prévia dos registros importáveis")
            st.dataframe(
                st.session_state["importaveis"][
                    ["Nome", "Matrícula", "Cargo Efetivo"]
                ],
                hide_index=True,
                use_container_width=True,
            )

            if not st.session_state["excluidos"].empty:
                st.warning("Registros RJU que serão excluídos:")
                st.dataframe(
                    st.session_state["excluidos"][
                        ["Nome", "Matrícula", "Cargo Efetivo"]
                    ],
                    hide_index=True,
                    use_container_width=True,
                )

            if not st.session_state["ambiguos"].empty:
                st.warning(
                    "Existem duplicidades sem alternativa não RJU. "
                    "Esses registros não serão importados automaticamente."
                )
                st.dataframe(
                    st.session_state["ambiguos"][
                        ["Nome", "Matrícula", "Cargo Efetivo"]
                    ],
                    hide_index=True,
                    use_container_width=True,
                )

            if st.button("Confirmar importação no banco"):
                base = st.session_state["importaveis"]
                inseridos = 0
                atualizados = 0

                try:
                    with conectar() as conn:
                        for _, linha in base.iterrows():
                            chave = linha["Chave"]
                            existente = conn.execute(
                                """
                                SELECT id FROM colaboradores
                                WHERE nome_chave = ?
                                """,
                                (chave,),
                            ).fetchone()

                            if existente:
                                conn.execute(
                                    """
                                    UPDATE colaboradores
                                    SET nome = ?, matricula = ?,
                                        cargo = ?, ativo = 1
                                    WHERE nome_chave = ?
                                    """,
                                    (
                                        linha["Nome"],
                                        linha["Matrícula"],
                                        linha["Cargo Efetivo"],
                                        chave,
                                    ),
                                )
                                atualizados += 1
                            else:
                                conn.execute(
                                    """
                                    INSERT INTO colaboradores
                                    (nome, nome_chave, matricula, cargo)
                                    VALUES (?, ?, ?, ?)
                                    """,
                                    (
                                        linha["Nome"],
                                        chave,
                                        linha["Matrícula"],
                                        linha["Cargo Efetivo"],
                                    ),
                                )
                                inseridos += 1

                    st.success(
                        f"Importação concluída: {inseridos} novos; "
                        f"{atualizados} atualizados."
                    )

                    for chave in [
                        "importaveis", "excluidos", "ambiguos"
                    ]:
                        st.session_state.pop(chave, None)

                except psycopg2.Error as erro:
                    st.error(f"Erro no banco de dados: {erro}")

    st.divider()
    st.subheader("Base salva no banco")

    colaboradores = listar_colaboradores(ativos=False)

    if colaboradores.empty:
        st.info("Nenhum colaborador cadastrado.")
    else:
        busca = st.text_input("Buscar por nome, matrícula ou cargo")

        if busca:
            mascara = (
                colaboradores["nome"].str.contains(
                    busca, case=False, na=False, regex=False
                )
                | colaboradores["matricula"].fillna("").str.contains(
                    busca, case=False, na=False, regex=False
                )
                | colaboradores["cargo"].str.contains(
                    busca, case=False, na=False, regex=False
                )
            )
            colaboradores = colaboradores[mascara]

        st.dataframe(
            colaboradores,
            hide_index=True,
            use_container_width=True,
        )

        csv = colaboradores.to_csv(
            index=False, sep=";", encoding="utf-8-sig"
        )
        st.download_button(
            "Exportar colaboradores em CSV",
            data=csv,
            file_name="colaboradores.csv",
            mime="text/csv",
        )


# ======================================================
# TREINAMENTOS
# ======================================================

elif menu == "Treinamentos":
    st.header("Cadastro de treinamentos")

    colaboradores = listar_colaboradores()

    # --------------------------------------------------
    # SELEÇÃO DO PÚBLICO-ALVO
    # --------------------------------------------------

    st.subheader("1. Definir colaboradores elegíveis")

    publico = st.radio(
        "Como deseja selecionar os participantes?",
        [
            "Todos os colaboradores ativos",
            "Selecionar por cargo e/ou colaborador",
        ],
        key="publico_treinamento",
    )

    ids = []
    opcoes = {}
    selecionados = []

    if publico == "Todos os colaboradores ativos":
        ids = colaboradores["id"].astype(int).tolist()

        st.info(
            f"Serão incluídos {len(ids)} colaboradores "
            "retornados pelo cadastro de colaboradores."
        )

    else:
        if colaboradores.empty:
            st.warning("Não há colaboradores cadastrados.")
        elif "cargo" not in colaboradores.columns:
            st.error(
                "Não foi encontrada a coluna 'cargo' no cadastro "
                "de colaboradores. Verifique a estrutura da função "
                "listar_colaboradores()."
            )
        else:
            cargos_disponiveis = sorted(
                colaboradores["cargo"]
                .dropna()
                .astype(str)
                .str.strip()
                .loc[lambda s: s != ""]
                .unique()
                .tolist()
            )

            cargos_selecionados = st.multiselect(
                "Filtrar por cargo",
                options=cargos_disponiveis,
                key="cargos_treinamento",
                placeholder="Selecione um ou mais cargos",
            )

            if cargos_selecionados:
                colaboradores_filtrados = colaboradores[
                    colaboradores["cargo"]
                    .fillna("")
                    .astype(str)
                    .str.strip()
                    .isin(cargos_selecionados)
                ].copy()
            else:
                colaboradores_filtrados = colaboradores.copy()

            st.caption(
                f"{len(colaboradores_filtrados)} colaborador(es) "
                "encontrado(s) com o filtro atual."
            )

            selecionar_todos = st.checkbox(
                "Selecionar todos os colaboradores exibidos",
                key="selecionar_todos_treinamento",
            )

            opcoes = {
                (
                    f'{r["nome"]} | Cargo: {r["cargo"] or "não informado"} '
                    f'| Matrícula: {r["matricula"] or "não informada"}'
                ): int(r["id"])
                for _, r in colaboradores_filtrados.iterrows()
            }

            if selecionar_todos:
                selecionados = list(opcoes.keys())
                ids = list(opcoes.values())
                st.success(
                    f"{len(ids)} colaborador(es) selecionado(s)."
                )
            else:
                selecionados = st.multiselect(
                    "Escolha os colaboradores",
                    options=list(opcoes.keys()),
                    key="colaboradores_especificos_treinamento",
                    placeholder="Selecione os participantes",
                )

                ids = [opcoes[nome] for nome in selecionados]

            st.caption(
                f"Total de participantes selecionados: {len(ids)}"
            )

    st.divider()

    # --------------------------------------------------
    # FORMULÁRIO DE CADASTRO
    # --------------------------------------------------

    st.subheader("2. Informações do treinamento")

    with st.form("form_treinamento"):
        titulo = st.text_input("Nome do treinamento")

        data_treinamento = st.date_input(
            "Data",
            value=date.today(),
        )

        col1, col2 = st.columns(2)

        with col1:
            hora_inicio = st.time_input(
                "Horário de início",
                value=time(8, 0),
            )

        with col2:
            hora_fim = st.time_input(
                "Horário de término",
                value=time(9, 0),
            )

        carga = st.number_input(
            "Carga horária (horas)",
            min_value=0.25,
            value=1.0,
            step=0.25,
        )

        situacao = st.selectbox(
            "Situação",
            ["Agendado", "Realizado", "Cancelado"],
        )

        observacoes = st.text_area("Observações")

        salvar = st.form_submit_button("Salvar treinamento")

        if salvar:
            if not titulo.strip():
                st.error("Informe o nome do treinamento.")

            elif hora_fim <= hora_inicio:
                st.error(
                    "O horário de término deve ser posterior ao início."
                )

            elif not ids:
                st.error(
                    "Selecione pelo menos um colaborador elegível."
                )

            else:
                try:
                    with conectar() as conn:
                        cursor = conn.execute(
                            """
                            INSERT INTO treinamentos
                            (
                                titulo,
                                data,
                                hora_inicio,
                                hora_fim,
                                carga_horaria,
                                publico,
                                situacao,
                                observacoes
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                titulo.strip(),
                                data_treinamento.isoformat(),
                                hora_inicio.strftime("%H:%M"),
                                hora_fim.strftime("%H:%M"),
                                carga,
                                publico,
                                situacao,
                                observacoes.strip(),
                            ),
                        )

                        treinamento_id = cursor.lastrowid

                        conn.executemany(
                            """
                            INSERT INTO elegibilidade
                            (treinamento_id, colaborador_id)
                            VALUES (?, ?)
                            """,
                            [
                                (treinamento_id, cid)
                                for cid in ids
                            ],
                        )

                    st.success("Treinamento cadastrado!")
                    st.rerun()

                except psycopg2.Error as erro:
                    st.error(f"Erro ao salvar: {erro}")

    # --------------------------------------------------
    # LISTAGEM DOS TREINAMENTOS
    # --------------------------------------------------

    st.divider()
    st.subheader("Treinamentos cadastrados")

    mensagem_exclusao = st.session_state.pop(
        "mensagem_exclusao_treinamento", None
    )

    if mensagem_exclusao:
        st.success(mensagem_exclusao)

    treinamentos = listar_treinamentos()

    if treinamentos.empty:
        st.info("Nenhum treinamento cadastrado.")
    else:
        colunas_exibicao = [
            "id",
            "titulo",
            "data",
            "hora_inicio",
            "hora_fim",
            "carga_horaria",
            "publico",
            "situacao",
        ]

        st.dataframe(
            treinamentos[colunas_exibicao],
            hide_index=True,
            use_container_width=True,
        )

    # --------------------------------------------------
    # EXCLUSÃO DE TREINAMENTOS AGENDADOS
    # --------------------------------------------------

    st.divider()
    st.subheader("Excluir treinamento agendado")

    agendados = treinamentos[
        treinamentos["situacao"] == "Agendado"
    ].copy()

    if agendados.empty:
        st.info(
            "Não há treinamentos agendados disponíveis para exclusão."
        )
    else:
        opcoes_exclusao = {
            (
                f'ID {int(r["id"])} | {r["titulo"]} '
                f'| Data: {r["data"]}'
            ): int(r["id"])
            for _, r in agendados.iterrows()
        }

        treinamento_excluir = st.selectbox(
            "Selecione o treinamento que deseja excluir",
            options=list(opcoes_exclusao.keys()),
            key="treinamento_excluir",
        )

        confirmar_exclusao = st.checkbox(
            "Confirmo que desejo excluir este treinamento agendado.",
            key="confirmar_exclusao_treinamento",
        )

        if st.button(
            "Excluir treinamento",
            type="secondary",
            disabled=not confirmar_exclusao,
            key="botao_excluir_treinamento",
        ):
            id_excluir = opcoes_exclusao[treinamento_excluir]

            try:
                with conectar() as conn:
                    registro = conn.execute(
                        """
                        SELECT situacao
                        FROM treinamentos
                        WHERE id = ?
                        """,
                        (id_excluir,),
                    ).fetchone()

                    if registro is None:
                        st.error("O treinamento não foi encontrado.")

                    elif registro["situacao"] != "Agendado":
                        st.error(
                            "Só é permitido excluir treinamentos "
                            "com situação 'Agendado'."
                        )

                    else:
                        conn.execute(
                            """
                            DELETE FROM elegibilidade
                            WHERE treinamento_id = ?
                            """,
                            (id_excluir,),
                        )

                        resultado = conn.execute(
                            """
                            DELETE FROM treinamentos
                            WHERE id = ?
                              AND situacao = 'Agendado'
                            """,
                            (id_excluir,),
                        )

                        if resultado.rowcount == 1:
                            st.session_state[
                                "mensagem_exclusao_treinamento"
                            ] = "Treinamento excluído com sucesso!"
                        else:
                            st.error(
                                "Nenhum treinamento foi excluído."
                            )

                if st.session_state.get(
                    "mensagem_exclusao_treinamento"
                ):
                    st.rerun()

            except psycopg2.Error as erro:
                st.error(f"Erro ao excluir treinamento: {erro}")


# ======================================================
# PRESENÇAS
# ======================================================

elif menu == "Presenças":
    st.header("Registro de presenças")

    treinamentos = listar_treinamentos()
    colaboradores = listar_colaboradores()

    if treinamentos.empty:
        st.info("Cadastre um treinamento antes de registrar presenças.")
        st.stop()

    mapa_treinamentos = {
        (
            f'{r["data"]} | {r["titulo"]} '
            f'| {r["hora_inicio"]} | ID {r["id"]}'
        ): int(r["id"])
        for _, r in treinamentos.iterrows()
    }

    escolha = st.selectbox(
        "Selecione o treinamento",
        list(mapa_treinamentos.keys()),
    )
    tid = mapa_treinamentos[escolha]

    treinamento = treinamentos[
        treinamentos["id"] == tid
    ].iloc[0]

    elegiveis = consultar(
        """
        SELECT c.id, c.nome, c.matricula, c.cargo
        FROM elegibilidade e
        JOIN colaboradores c ON c.id = e.colaborador_id
        WHERE e.treinamento_id = ? AND c.ativo = 1
        ORDER BY c.nome
        """,
        (tid,),
    )

    if elegiveis.empty:
        st.warning("Este treinamento não tem público elegível cadastrado.")
        st.stop()

    if treinamento["situacao"] == "Cancelado":
        st.warning("Este treinamento está cancelado.")
        st.stop()

    ids = elegiveis["id"].astype(int).tolist()

    atuais = consultar(
        """
        SELECT colaborador_id, presente
        FROM presencas
        WHERE treinamento_id = ?
        """,
        (tid,),
    )

    presentes_atuais = set(
        atuais.loc[
            atuais["presente"] == 1, "colaborador_id"
        ].astype(int).tolist()
    )

    nomes = {
        int(r["id"]): (
            f'{r["nome"]} | Matrícula: '
            f'{r["matricula"] or "não informada"}'
        )
        for _, r in elegiveis.iterrows()
    }

    selecionados_atuais = [
        nomes[cid] for cid in ids if cid in presentes_atuais
    ]

    with st.form("form_presencas"):
        presentes = st.multiselect(
            "Selecione quem esteve presente",
            options=[nomes[cid] for cid in ids],
            default=selecionados_atuais,
        )

        salvar_presencas = st.form_submit_button(
            "Salvar presenças"
        )

        if salvar_presencas:
            if treinamento["situacao"] == "Cancelado":
                st.error(
                    "Não é possível registrar presença em treinamento cancelado."
                )
            else:
                presentes_ids = {
                    cid for cid in ids
                    if nomes[cid] in presentes
                }

                try:
                    with conectar() as conn:
                        for cid in ids:
                            conn.execute(
                                """
                                INSERT INTO presencas
                                (treinamento_id, colaborador_id, presente)
                                VALUES (?, ?, ?)
                                ON CONFLICT(treinamento_id, colaborador_id)
                                DO UPDATE SET
                                    presente = excluded.presente,
                                    atualizado_em = CURRENT_TIMESTAMP::text
                                """,
                                (
                                    tid,
                                    cid,
                                    1 if cid in presentes_ids else 0,
                                ),
                            )

                    st.success(
                        "Presenças salvas. Os demais elegíveis estão "
                        "registrados como não presentes."
                    )
                    st.rerun()

                except psycopg2.Error as erro:
                    st.error(f"Erro ao salvar presenças: {erro}")

    if treinamento["situacao"] != "Realizado":
        st.info(
            "Para contabilizar ausências, marque o treinamento como "
            "'Realizado' na seção Treinamentos depois que ele terminar."
        )


# ======================================================
# RELATÓRIOS
# ======================================================

elif menu == "Relatórios":
    st.header("Relatórios de assiduidade")

    resumo = consultar("""
        SELECT
            t.id AS treinamento_id,
            t.titulo AS treinamento,
            t.data,
            t.situacao,
            c.nome,
            c.matricula,
            c.cargo,
            p.presente
        FROM elegibilidade e
        JOIN treinamentos t
            ON t.id = e.treinamento_id
        JOIN colaboradores c
            ON c.id = e.colaborador_id
        LEFT JOIN presencas p
            ON p.treinamento_id = t.id
            AND p.colaborador_id = c.id
        WHERE c.ativo = 1
        ORDER BY t.data DESC, t.titulo, c.nome
    """)

    if resumo.empty:
        st.info("Ainda não há dados para relatório.")
    else:
        hoje = date.today().isoformat()

        resumo["resultado"] = "Pendente"
        resumo.loc[
            resumo["situacao"] == "Cancelado", "resultado"
        ] = "Cancelado"

        resumo.loc[
            (resumo["situacao"] == "Realizado")
            & (resumo["data"] <= hoje)
            & (resumo["presente"] == 1),
            "resultado",
        ] = "Presente"

        resumo.loc[
            (resumo["situacao"] == "Realizado")
            & (resumo["data"] <= hoje)
            & (resumo["presente"] == 0),
            "resultado",
        ] = "Ausente"

        resumo.loc[
            (resumo["situacao"] != "Realizado")
            & (resumo["situacao"] != "Cancelado"),
            "resultado",
        ] = "Pendente"

        c1, c2, c3 = st.columns(3)
        c1.metric(
            "Presenças",
            int((resumo["resultado"] == "Presente").sum()),
        )
        c2.metric(
            "Ausências",
            int((resumo["resultado"] == "Ausente").sum()),
        )
        c3.metric(
            "Pendências",
            int((resumo["resultado"] == "Pendente").sum()),
        )

        st.caption(
            "A ausência é contabilizada apenas para treinamentos "
            "marcados como Realizado. Treinamentos cancelados são excluídos."
        )

        filtro = st.multiselect(
            "Filtrar resultado",
            ["Presente", "Ausente", "Pendente", "Cancelado"],
            default=["Presente", "Ausente", "Pendente", "Cancelado"],
        )

        filtrado = resumo[resumo["resultado"].isin(filtro)]

        st.dataframe(
            filtrado[
                [
                    "treinamento", "data", "nome",
                    "matricula", "cargo", "resultado"
                ]
            ],
            hide_index=True,
            use_container_width=True,
        )

        st.download_button(
            "Baixar relatório em CSV",
            data=filtrado.to_csv(
                index=False, sep=";", encoding="utf-8-sig"
            ),
            file_name="relatorio_assiduidade.csv",
            mime="text/csv",
        )
