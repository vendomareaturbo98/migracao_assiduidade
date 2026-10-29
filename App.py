import hmac
import os
import re
import unicodedata
from datetime import date, time

import pandas as pd
import plotly.express as px
import streamlit as st

from dashboard_utils import (
    SITUACOES,
    aplicar_filtros,
    calcular_metricas,
    classificar_resultados,
    desempenho_por_treinamento,
    evolucao_mensal,
    resumo_por_cargo,
)

# A versão publicada usa exclusivamente o PostgreSQL do Supabase.
# O banco SQLite de testes não deve ser selecionado por variável de ambiente
# nesta versão de produção.
from db_postgres import conectar, consultar, inicializar_banco


# ======================================================
# CONFIGURAÇÃO E ACESSO ADMINISTRATIVO
# ======================================================

st.set_page_config(
    page_title="Sistema de Assiduidade",
    page_icon="📊",
    layout="wide",
)


# Carrega os estilos visuais externos sem alterar a lógica do aplicativo.
from pathlib import Path

caminho_css = Path(__file__).parent / "style.css"
if caminho_css.exists():
    with open(caminho_css, encoding="utf-8") as arquivo_css:
        st.markdown(
            f"<style>{arquivo_css.read()}</style>",
            unsafe_allow_html=True,
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
        "nos Secrets da hospedagem antes de utilizar este aplicativo."
    )
    st.stop()

if not st.session_state.get("admin_autenticado", False):
    st.title("🔐 Acesso administrativo")
    with st.form("form_login_admin"):
        senha_digitada = st.text_input(
            "Senha administrativa",
            type="password",
            autocomplete="current-password",
        )
        entrar = st.form_submit_button("Entrar", use_container_width=True)
    if entrar:
        if hmac.compare_digest(senha_digitada, senha_configurada):
            st.session_state["admin_autenticado"] = True
            st.rerun()
        else:
            st.error("Senha incorreta.")
    st.caption("Acesso exclusivo aos responsáveis pelo sistema.")
    st.stop()

# Cria tabelas se necessário; não apaga dados existentes.
inicializar_banco()


@st.cache_resource(show_spinner=False)
def garantir_colunas_dois_dias():
    """Adiciona, uma única vez, as colunas do recurso "treinamento em dois dias".

    Não apaga nem altera dados existentes: treinamentos antigos ficam com
    data_dia2 vazia e continuam funcionando como treinamentos de um dia.
    """
    with conectar() as conn:
        conn.execute("ALTER TABLE treinamentos ADD COLUMN IF NOT EXISTS data_dia2 TEXT", ())
        conn.execute("ALTER TABLE presencas ADD COLUMN IF NOT EXISTS presente_dia1 INTEGER", ())
        conn.execute("ALTER TABLE presencas ADD COLUMN IF NOT EXISTS presente_dia2 INTEGER", ())
    return True


try:
    garantir_colunas_dois_dias()
except Exception:
    st.error(
        "Não foi possível preparar o banco para treinamentos em dois dias. "
        "Verifique os logs e as permissões do usuário do banco."
    )
    st.stop()


# ======================================================
# FUNÇÕES AUXILIARES
# ======================================================

def normalizar(valor):
    if pd.isna(valor):
        return ""
    texto = str(valor).strip().casefold()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto)


def cabecalho_normalizado(valor):
    return re.sub(r"[^a-z0-9]", "", normalizar(valor))


def localizar_coluna(colunas, alternativas):
    mapa = {cabecalho_normalizado(c): c for c in colunas}
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
        SELECT id, titulo, data, data_dia2, hora_inicio, hora_fim, carga_horaria,
               publico, situacao, observacoes, criado_em
        FROM treinamentos
        ORDER BY data DESC, hora_inicio DESC, id DESC
    """)


def carregar_participacoes_dashboard():
    """Carrega cada elegibilidade com seu estado de presença para o painel."""
    return consultar("""
        SELECT
            t.id AS treinamento_id,
            t.titulo AS treinamento,
            t.data,
            t.situacao,
            c.id AS colaborador_id,
            c.nome,
            c.matricula,
            c.cargo,
            p.presente
        FROM elegibilidade e
        JOIN treinamentos t ON t.id = e.treinamento_id
        JOIN colaboradores c ON c.id = e.colaborador_id
        LEFT JOIN presencas p
            ON p.treinamento_id = t.id
            AND p.colaborador_id = c.id
        WHERE c.ativo = 1
        ORDER BY t.data, t.hora_inicio, t.titulo, c.nome
    """)


def exibir_grafico(figura, descricao):
    """Centraliza a configuração de acessibilidade e dos controles dos gráficos."""
    figura.update_layout(
        margin=dict(l=12, r=12, t=36, b=12),
        legend_title_text="",
        hoverlabel=dict(namelength=-1),
    )
    # O parâmetro "alt" não é passado para manter compatibilidade com
    # versões do Streamlit a partir da faixa 1.40 definida em requirements.txt.
    st.plotly_chart(
        figura,
        use_container_width=True,
        config={"displaylogo": False, "scrollZoom": False},
    )


def exibir_visao_geral():
    """Mostra o painel interativo de acompanhamento da educação continuada."""
    colaboradores = listar_colaboradores()
    treinamentos = listar_treinamentos()
    participacoes = classificar_resultados(carregar_participacoes_dashboard())

    st.subheader("Painel de acompanhamento")
    st.caption(
        "Use os filtros para explorar a cobertura dos treinamentos, a presença "
        "e os pontos que precisam de acompanhamento."
    )

    datas = pd.to_datetime(treinamentos["data"], errors="coerce").dropna()
    if datas.empty:
        inicio_padrao = fim_padrao = date.today()
    else:
        inicio_padrao = datas.min().date()
        fim_padrao = datas.max().date()

    cargos_disponiveis = sorted(
        colaboradores["cargo"].fillna("").loc[lambda serie: serie != ""].unique()
    ) if not colaboradores.empty else []

    with st.expander("Filtros do painel", expanded=True):
        filtro_col1, filtro_col2, filtro_col3 = st.columns(3)
        with filtro_col1:
            periodo = st.date_input(
                "Período dos treinamentos",
                value=(inicio_padrao, fim_padrao),
                key="dashboard_periodo",
            )
        with filtro_col2:
            cargos = st.multiselect(
                "Cargos", options=cargos_disponiveis, key="dashboard_cargos"
            )
        with filtro_col3:
            situacoes = st.multiselect(
                "Situações", options=SITUACOES, default=SITUACOES,
                key="dashboard_situacoes",
            )

    if isinstance(periodo, tuple) and len(periodo) == 2:
        data_inicial, data_final = periodo
    else:
        data_inicial = data_final = periodo
    if data_inicial > data_final:
        st.error("A data inicial do filtro deve ser anterior ou igual à data final.")
        return

    participacoes_filtradas = aplicar_filtros(
        participacoes, data_inicial, data_final, cargos, situacoes
    )
    if treinamentos.empty:
        treinamentos_filtrados = treinamentos.copy()
    else:
        dados_treinamentos = treinamentos.copy()
        dados_treinamentos["data"] = pd.to_datetime(
            dados_treinamentos["data"], errors="coerce"
        )
        mascara_periodo = dados_treinamentos["data"].dt.date.between(
            data_inicial, data_final
        )
        treinamentos_filtrados = dados_treinamentos.loc[
            mascara_periodo & dados_treinamentos["situacao"].isin(situacoes)
        ].copy()

    metricas = calcular_metricas(
        colaboradores, treinamentos_filtrados, participacoes_filtradas, cargos
    )
    indicador1, indicador2, indicador3, indicador4, indicador5 = st.columns(5)
    indicador1.metric("Colaboradores ativos", metricas["colaboradores_ativos"])
    indicador2.metric("Treinamentos", metricas["treinamentos"])
    indicador3.metric("Realizados", metricas["treinamentos_realizados"])
    indicador4.metric("Taxa de presença", f'{metricas["taxa_presenca"]:.1f}%')
    indicador5.metric("Ausências", metricas["ausencias"])

    aba_panorama, aba_assiduidade, aba_agenda = st.tabs(
        ["Panorama", "Assiduidade", "Agenda e pendências"]
    )

    with aba_panorama:
        if treinamentos_filtrados.empty:
            st.info("Não há treinamentos para os filtros selecionados.")
        else:
            grafico1, grafico2 = st.columns(2)
            with grafico1:
                por_situacao = (
                    treinamentos_filtrados["situacao"].value_counts()
                    .rename_axis("situacao").reset_index(name="quantidade")
                )
                figura_situacao = px.pie(
                    por_situacao,
                    names="situacao",
                    values="quantidade",
                    hole=0.55,
                    title="Situação dos treinamentos",
                    color="situacao",
                    color_discrete_map={
                        "Realizado": "#2E8B57", "Agendado": "#1F77B4",
                        "Remarcado": "#F39C12", "Cancelado": "#C0392B",
                    },
                )
                exibir_grafico(
                    figura_situacao,
                    "Distribuição dos treinamentos por situação.",
                )
            with grafico2:
                por_resultado = (
                    participacoes_filtradas["resultado"].value_counts()
                    .reindex(["Presente", "Ausente", "Pendente", "Cancelado"], fill_value=0)
                    .rename_axis("resultado").reset_index(name="quantidade")
                )
                figura_resultado = px.bar(
                    por_resultado,
                    x="resultado",
                    y="quantidade",
                    color="resultado",
                    text="quantidade",
                    title="Resultado das participações",
                    color_discrete_map={
                        "Presente": "#2E8B57", "Ausente": "#C0392B",
                        "Pendente": "#1F77B4", "Cancelado": "#7F8C8D",
                    },
                )
                figura_resultado.update_layout(showlegend=False, yaxis_title="Participações")
                exibir_grafico(
                    figura_resultado,
                    "Quantidade de presenças, ausências, pendências e cancelamentos.",
                )

        st.subheader("Resumo dos indicadores filtrados")
        st.dataframe(
            pd.DataFrame([{
                "Presenças": metricas["presencas"],
                "Ausências": metricas["ausencias"],
                "Pendências": metricas["pendencias"],
                "Taxa de presença (%)": metricas["taxa_presenca"],
            }]),
            hide_index=True,
            use_container_width=True,
        )

    with aba_assiduidade:
        if participacoes_filtradas.empty:
            st.info("Ainda não há participantes elegíveis para os filtros selecionados.")
        else:
            evolucao = evolucao_mensal(participacoes_filtradas)
            por_cargo = resumo_por_cargo(participacoes_filtradas)
            grafico3, grafico4 = st.columns(2)
            with grafico3:
                if evolucao.empty:
                    st.info("Não há treinamentos concluídos no período para calcular a taxa mensal.")
                else:
                    figura_evolucao = px.line(
                        evolucao, x="mes", y="taxa_presenca", markers=True,
                        hover_data=["participacoes"],
                        title="Evolução mensal da presença",
                    )
                    figura_evolucao.update_layout(
                        yaxis_title="Taxa de presença (%)", xaxis_title="Mês"
                    )
                    figura_evolucao.update_yaxes(range=[0, 100])
                    exibir_grafico(
                        figura_evolucao,
                        "Taxa de presença por mês e quantidade de participações concluídas.",
                    )
            with grafico4:
                if por_cargo.empty:
                    st.info("Não há presenças ou ausências concluídas para comparar por cargo.")
                else:
                    figura_cargo = px.bar(
                        por_cargo, x="cargo", y="quantidade", color="resultado",
                        barmode="group", text="quantidade",
                        title="Presença por cargo",
                        color_discrete_map={"Presente": "#2E8B57", "Ausente": "#C0392B"},
                    )
                    figura_cargo.update_layout(xaxis_title="Cargo", yaxis_title="Participações")
                    exibir_grafico(
                        figura_cargo,
                        "Comparação de presenças e ausências por cargo.",
                    )

            st.subheader("Desempenho por treinamento")
            desempenho = desempenho_por_treinamento(participacoes_filtradas)
            if desempenho.empty:
                st.info("O desempenho será exibido após registrar as presenças de um treinamento realizado.")
            else:
                st.dataframe(
                    desempenho.rename(columns={
                        "treinamento": "Treinamento", "data": "Data",
                        "presentes": "Presentes", "ausentes": "Ausentes",
                        "taxa_presenca": "Taxa de presença (%)",
                    }),
                    hide_index=True,
                    use_container_width=True,
                )

    with aba_agenda:
        st.subheader("Treinamentos no período")
        if treinamentos_filtrados.empty:
            st.info("Não há treinamentos no período selecionado.")
        else:
            agenda = treinamentos_filtrados[
                ["titulo", "data", "data_dia2", "hora_inicio", "hora_fim",
                 "carga_horaria", "situacao"]
            ].rename(columns={
                "titulo": "Treinamento", "data": "Data", "data_dia2": "2º dia",
                "hora_inicio": "Início",
                "hora_fim": "Fim", "carga_horaria": "Carga horária", "situacao": "Situação",
            })
            st.dataframe(agenda, hide_index=True, use_container_width=True)

        st.subheader("Ausências que requerem acompanhamento")
        ausentes = participacoes_filtradas[
            participacoes_filtradas["resultado"] == "Ausente"
        ]
        if ausentes.empty:
            st.success("Não há ausências nos filtros selecionados.")
        else:
            st.dataframe(
                ausentes[["nome", "matricula", "cargo", "treinamento", "data"]].rename(
                    columns={
                        "nome": "Colaborador", "matricula": "Matrícula", "cargo": "Cargo",
                        "treinamento": "Treinamento", "data": "Data",
                    }
                ),
                hide_index=True,
                use_container_width=True,
            )


def preparar_planilha(arquivo, aba=None):
    arquivo.seek(0)
    if arquivo.name.lower().endswith(".csv"):
        try:
            df = pd.read_csv(arquivo, dtype=str, sep=None, engine="python")
        except UnicodeDecodeError:
            arquivo.seek(0)
            df = pd.read_csv(
                arquivo, dtype=str, sep=None, engine="python",
                encoding="latin-1"
            )
    else:
        df = pd.read_excel(
            arquivo, sheet_name=0 if aba is None else aba, dtype=str
        )

    coluna_nome = localizar_coluna(df.columns, ["Nome", "Nome completo"])
    coluna_matricula = localizar_coluna(df.columns, ["Matrícula", "Matricula"])
    coluna_cargo = localizar_coluna(df.columns, ["Cargo Efetivo", "Cargo"])

    if not all([coluna_nome, coluna_matricula, coluna_cargo]):
        raise ValueError(
            "A planilha precisa conter as colunas Nome, Matrícula e Cargo Efetivo."
        )

    base = pd.DataFrame({
        "Nome": df[coluna_nome].fillna("").astype(str).str.strip(),
        "Matrícula": df[coluna_matricula].fillna("").astype(str).str.strip(),
        "Cargo Efetivo": df[coluna_cargo].fillna("").astype(str).str.strip(),
    })
    base = base[base["Nome"] != ""].copy()
    base["Chave"] = base["Nome"].apply(normalizar)
    base["RJU"] = base["Cargo Efetivo"].str.contains(
        r"RJU\s*$", case=False, regex=True, na=False
    )

    excluidos = []
    ambiguos = []
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
    base.loc[excluidos, "Resultado"] = "Excluído: RJU com alternativa não RJU"
    base.loc[ambiguos, "Resultado"] = "Revisar duplicidade"

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


def texto_data_dia2(valor):
    """Devolve a data do 2º dia como texto AAAA-MM-DD, ou "" quando não existe."""
    if valor is None or pd.isna(valor):
        return ""
    return str(valor)[:10]


def sufixo_dia2(linha):
    """Trecho " e AAAA-MM-DD" para treinamentos em dois dias (vazio nos demais)."""
    dia2 = texto_data_dia2(linha.get("data_dia2"))
    return f" e {dia2}" if dia2 else ""


def formatar_treinamento(linha):
    return (
        f'ID {int(linha["id"])} | {linha["titulo"]} | '
        f'Data: {linha["data"]}{sufixo_dia2(linha)} | Status: {linha["situacao"]}'
    )


# ======================================================
# INTERFACE PRINCIPAL
# ======================================================

st.title("📊 Sistema de Assiduidade")
st.caption("Educação Continuada | Banco de dados PostgreSQL na nuvem")

menu = st.sidebar.radio(
    "Navegação",
    ["Visão geral", "Colaboradores", "Treinamentos", "Presenças", "Relatórios"],
)


# ======================================================
# VISÃO GERAL
# ======================================================

if menu == "Visão geral":
    exibir_visao_geral()
    st.info(
        "Os dados ficam salvos no PostgreSQL do Supabase, na nuvem, "
        "mesmo após fechar o aplicativo."
    )


# ======================================================
# COLABORADORES
# ======================================================

elif menu == "Colaboradores":
    st.header("Cadastro de colaboradores")

    with st.expander("Importar planilha Excel ou CSV", expanded=True):
        arquivo = st.file_uploader(
            "Selecione a planilha", type=["xlsx", "xls", "csv"],
            key="planilha_colaboradores",
        )
        aba = None
        if arquivo and arquivo.name.lower().endswith((".xlsx", ".xls")):
            try:
                abas = pd.ExcelFile(arquivo).sheet_names
                if len(abas) > 1:
                    aba = st.selectbox("Aba da planilha", abas)
            except Exception:
                st.error("Não foi possível listar as abas da planilha.")

        if arquivo and st.button("Analisar planilha"):
            try:
                original, importaveis, excluidos, ambiguos = preparar_planilha(
                    arquivo, aba
                )
                st.session_state["importaveis"] = importaveis
                st.session_state["excluidos"] = original[
                    original.index.isin(excluidos)
                ]
                st.session_state["ambiguos"] = original[
                    original.index.isin(ambiguos)
                ]
                st.success(
                    f"{len(importaveis)} registro(s) pronto(s) para importar."
                )
            except Exception as erro:
                st.error(f"Não foi possível analisar a planilha: {erro}")

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
                st.warning("Registros RJU que serão excluídos pela regra de duplicidade:")
                st.dataframe(
                    st.session_state["excluidos"][
                        ["Nome", "Matrícula", "Cargo Efetivo"]
                    ],
                    hide_index=True,
                    use_container_width=True,
                )
            if not st.session_state["ambiguos"].empty:
                st.warning(
                    "Há nomes duplicados sem alternativa não RJU. "
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
                                "SELECT id FROM colaboradores WHERE nome_chave = ?",
                                (chave,),
                            ).fetchone()
                            if existente:
                                conn.execute(
                                    """
                                    UPDATE colaboradores
                                    SET nome = ?, matricula = ?, cargo = ?, ativo = 1
                                    WHERE nome_chave = ?
                                    """,
                                    (
                                        linha["Nome"], linha["Matrícula"],
                                        linha["Cargo Efetivo"], chave,
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
                                        linha["Nome"], chave, linha["Matrícula"],
                                        linha["Cargo Efetivo"],
                                    ),
                                )
                                inseridos += 1
                    st.success(
                        f"Importação concluída: {inseridos} novos; "
                        f"{atualizados} atualizados."
                    )
                    for chave in ["importaveis", "excluidos", "ambiguos"]:
                        st.session_state.pop(chave, None)
                    st.rerun()
                except Exception:
                    st.error(
                        "Não foi possível concluir a importação. "
                        "Verifique os logs do aplicativo."
                    )

    st.divider()
    st.subheader("Base salva no banco")
    colaboradores = listar_colaboradores(ativos=False)
    if colaboradores.empty:
        st.info("Nenhum colaborador cadastrado.")
    else:
        busca = st.text_input("Buscar por nome, matrícula ou cargo")
        if busca:
            mascara = (
                colaboradores["nome"].fillna("").str.contains(
                    busca, case=False, na=False, regex=False
                )
                | colaboradores["matricula"].fillna("").str.contains(
                    busca, case=False, na=False, regex=False
                )
                | colaboradores["cargo"].fillna("").str.contains(
                    busca, case=False, na=False, regex=False
                )
            )
            colaboradores = colaboradores[mascara]
        st.dataframe(colaboradores, hide_index=True, use_container_width=True)
        csv = colaboradores.to_csv(index=False, sep=";", encoding="utf-8-sig")
        st.download_button(
            "Exportar colaboradores em CSV",
            data=csv,
            file_name="colaboradores.csv",
            mime="text/csv",
        )


# ======================================================
# TREINAMENTOS: CADASTRO, ALTERAÇÃO DE STATUS E DATA
# ======================================================

elif menu == "Treinamentos":
    st.header("Cadastro e gerenciamento de treinamentos")
    aviso = st.session_state.pop("aviso_treinamentos", None)
    if aviso:
        st.success(aviso)
    colaboradores = listar_colaboradores()

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
    if publico == "Todos os colaboradores ativos":
        ids = colaboradores["id"].astype(int).tolist() if not colaboradores.empty else []
        st.info(f"Serão incluídos {len(ids)} colaboradores ativos.")
    elif colaboradores.empty:
        st.warning("Não há colaboradores cadastrados.")
    else:
        cargos_disponiveis = sorted(
            colaboradores["cargo"].fillna("").astype(str).str.strip()
            .loc[lambda s: s != ""].unique().tolist()
        )
        cargos_selecionados = st.multiselect(
            "Filtrar por cargo", options=cargos_disponiveis,
            key="cargos_treinamento",
        )
        if cargos_selecionados:
            filtrados = colaboradores[
                colaboradores["cargo"].fillna("").astype(str).str.strip()
                .isin(cargos_selecionados)
            ].copy()
        else:
            filtrados = colaboradores.copy()

        st.caption(f"{len(filtrados)} colaborador(es) encontrado(s).")
        opcoes = {
            (
                f'{r["nome"]} | Cargo: {r["cargo"] or "não informado"} | '
                f'Matrícula: {r["matricula"] or "não informada"}'
            ): int(r["id"])
            for _, r in filtrados.iterrows()
        }
        selecionar_todos = st.checkbox(
            "Selecionar todos os colaboradores exibidos",
            key="selecionar_todos_treinamento",
        )
        if selecionar_todos:
            # Permite tirar colaboradores específicos mesmo com o grupo inteiro marcado.
            excecoes = st.multiselect(
                "Remover colaboradores da seleção (opcional)",
                options=list(opcoes.keys()),
                key="excecoes_selecao_treinamento",
                help=(
                    "Todos os colaboradores exibidos serão incluídos, "
                    "exceto os que você escolher aqui."
                ),
            )
            ids = [cid for nome, cid in opcoes.items() if nome not in excecoes]
            if excecoes:
                st.caption(
                    f"{len(excecoes)} colaborador(es) removido(s) da seleção."
                )
        else:
            selecionados = st.multiselect(
                "Escolha os colaboradores", options=list(opcoes.keys()),
                key="colaboradores_especificos_treinamento",
            )
            ids = [opcoes[nome] for nome in selecionados]

        st.caption(f"Total de participantes selecionados: {len(ids)}")

    st.divider()
    st.subheader("2. Informações do novo treinamento")
    with st.form("form_treinamento"):
        titulo = st.text_input("Nome do treinamento")
        data_treinamento = st.date_input("Data (1º dia)", value=date.today())
        data_dia2_novo = st.date_input(
            "Data do 2º dia (opcional)",
            value=None,
            help=(
                "Preencha apenas se o mesmo treinamento for dividido em dois dias. "
                "Quem comparecer em qualquer um dos dias conta como presente."
            ),
        )
        col1, col2 = st.columns(2)
        with col1:
            hora_inicio = st.time_input("Horário de início", value=time(8, 0))
        with col2:
            hora_fim = st.time_input("Horário de término", value=time(9, 0))
        carga = st.number_input(
            "Carga horária (horas)", min_value=0.25, value=1.0, step=0.25
        )
        situacao_novo = st.selectbox(
            "Situação inicial", SITUACOES, index=0,
            help="Use Realizado somente quando o treinamento já tiver ocorrido.",
        )
        observacoes = st.text_area("Observações")
        salvar = st.form_submit_button("Salvar treinamento")

        if salvar:
            if not titulo.strip():
                st.error("Informe o nome do treinamento.")
            elif hora_fim <= hora_inicio:
                st.error("O horário de término deve ser posterior ao início.")
            elif data_dia2_novo is not None and data_dia2_novo <= data_treinamento:
                st.error("A data do 2º dia deve ser posterior à data do 1º dia.")
            elif not ids:
                st.error("Selecione pelo menos um colaborador elegível.")
            else:
                try:
                    with conectar() as conn:
                        cursor = conn.execute(
                            """
                            INSERT INTO treinamentos
                            (titulo, data, data_dia2, hora_inicio, hora_fim,
                             carga_horaria, publico, situacao, observacoes)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                titulo.strip(), data_treinamento.isoformat(),
                                data_dia2_novo.isoformat() if data_dia2_novo else None,
                                hora_inicio.strftime("%H:%M"),
                                hora_fim.strftime("%H:%M"), float(carga),
                                publico, situacao_novo, observacoes.strip(),
                            ),
                        )
                        treinamento_id = cursor.lastrowid
                        conn.executemany(
                            """
                            INSERT INTO elegibilidade
                            (treinamento_id, colaborador_id)
                            VALUES (?, ?)
                            """,
                            [(treinamento_id, cid) for cid in ids],
                        )
                    st.success("Treinamento cadastrado com sucesso.")
                    st.rerun()
                except Exception:
                    st.error(
                        "Não foi possível salvar o treinamento. "
                        "Verifique os logs do aplicativo."
                    )

    # Listagem e edição de treinamentos existentes.
    st.divider()
    st.subheader("3. Treinamentos cadastrados")
    treinamentos = listar_treinamentos()
    if treinamentos.empty:
        st.info("Nenhum treinamento cadastrado.")
    else:
        st.dataframe(
            treinamentos[
                ["id", "titulo", "data", "data_dia2", "hora_inicio", "hora_fim",
                 "carga_horaria", "publico", "situacao"]
            ],
            hide_index=True,
            use_container_width=True,
            column_config={
                "data_dia2": st.column_config.TextColumn("Data do 2º dia"),
            },
        )

        st.markdown("### Alterar status ou remarcar treinamento")
        mapa = {
            formatar_treinamento(r): int(r["id"])
            for _, r in treinamentos.iterrows()
        }
        escolha = st.selectbox(
            "Selecione o treinamento que deseja alterar",
            options=list(mapa.keys()),
            key="editar_treinamento_escolha",
        )
        tid_editar = mapa[escolha]
        atual = treinamentos[treinamentos["id"] == tid_editar].iloc[0]

        status_atual = str(atual["situacao"])
        data_atual_str = str(atual["data"])[:10]
        try:
            data_atual = date.fromisoformat(data_atual_str)
        except ValueError:
            data_atual = date.today()

        dia2_atual_str = texto_data_dia2(atual["data_dia2"])
        try:
            dia2_atual = date.fromisoformat(dia2_atual_str) if dia2_atual_str else None
        except ValueError:
            dia2_atual = None

        st.caption(
            f"Status atual: **{status_atual}** | "
            f"Data atual: **{data_atual_str}**"
            + (f" | 2º dia: **{dia2_atual_str}**" if dia2_atual_str else "")
        )
        with st.form(f"form_editar_treinamento_{tid_editar}"):
            novo_status = st.selectbox(
                "Novo status",
                SITUACOES,
                index=SITUACOES.index(status_atual)
                if status_atual in SITUACOES else 0,
            )
            nova_data = st.date_input("Data do treinamento (1º dia)", value=data_atual)
            nova_data_dia2 = st.date_input(
                "Data do 2º dia (opcional)",
                value=dia2_atual,
                key=f"data_dia2_treinamento_{tid_editar}",
                help="Deixe vazio para treinamentos de um único dia.",
            )
            nova_observacao = st.text_area(
                "Observações",
                value=str(atual["observacoes"] or ""),
                key=f"observacoes_treinamento_{tid_editar}",
            )
            salvar_alteracao = st.form_submit_button("Salvar alterações")

            if salvar_alteracao:
                if novo_status == "Remarcado" and nova_data == data_atual:
                    st.warning(
                        "O status será salvo como Remarcado, mas a data não mudou. "
                        "Se houve mudança de data, informe a nova data."
                    )
                if (
                    status_atual == "Realizado"
                    and novo_status in ("Agendado", "Remarcado")
                ):
                    st.warning(
                        "Você está reabrindo um treinamento já marcado como realizado. "
                        "Confira se essa alteração é realmente necessária."
                    )
                if nova_data_dia2 is not None and nova_data_dia2 <= nova_data:
                    st.error("A data do 2º dia deve ser posterior à data do 1º dia.")
                else:
                    try:
                        with conectar() as conn:
                            resultado = conn.execute(
                                """
                                UPDATE treinamentos
                                SET situacao = ?, data = ?, data_dia2 = ?, observacoes = ?
                                WHERE id = ?
                                """,
                                (
                                    novo_status, nova_data.isoformat(),
                                    nova_data_dia2.isoformat() if nova_data_dia2 else None,
                                    nova_observacao.strip(), tid_editar,
                                ),
                            )
                        if resultado.rowcount == 1:
                            st.success("Treinamento atualizado com sucesso.")
                            st.rerun()
                        else:
                            st.error("O treinamento não foi encontrado para atualização.")
                    except Exception:
                        st.error(
                            "Não foi possível atualizar o treinamento. "
                            "Verifique os logs do aplicativo."
                        )

    # Mantém exclusão restrita aos agendados, como na versão anterior.
    st.divider()
    st.subheader("4. Excluir treinamento agendado")
    if treinamentos.empty:
        st.info("Não há treinamentos para excluir.")
    else:
        agendados = treinamentos[treinamentos["situacao"] == "Agendado"].copy()
        if agendados.empty:
            st.info("Não há treinamentos agendados disponíveis para exclusão.")
        else:
            opcoes_exclusao = {
                formatar_treinamento(r): int(r["id"])
                for _, r in agendados.iterrows()
            }
            escolha_exclusao = st.selectbox(
                "Selecione o treinamento agendado",
                options=list(opcoes_exclusao.keys()),
                key="treinamento_excluir",
            )
            confirmar_exclusao = st.checkbox(
                "Confirmo que desejo excluir este treinamento agendado.",
                key="confirmar_exclusao_treinamento",
            )
            if st.button(
                "Excluir treinamento",
                disabled=not confirmar_exclusao,
                key="botao_excluir_treinamento",
            ):
                id_excluir = opcoes_exclusao[escolha_exclusao]
                excluido = False
                try:
                    with conectar() as conn:
                        registro = conn.execute(
                            "SELECT situacao FROM treinamentos WHERE id = ?",
                            (id_excluir,),
                        ).fetchone()
                        if registro is None:
                            st.error("O treinamento não foi encontrado.")
                        elif registro["situacao"] != "Agendado":
                            st.error(
                                "Só é permitido excluir treinamentos com status Agendado."
                            )
                        else:
                            # Remove os registros dependentes antes do treinamento.
                            conn.execute(
                                "DELETE FROM presencas WHERE treinamento_id = ?",
                                (id_excluir,),
                            )
                            conn.execute(
                                "DELETE FROM elegibilidade WHERE treinamento_id = ?",
                                (id_excluir,),
                            )
                            resultado = conn.execute(
                                """
                                DELETE FROM treinamentos
                                WHERE id = ? AND situacao = 'Agendado'
                                """,
                                (id_excluir,),
                            )
                            if resultado.rowcount == 1:
                                excluido = True
                            else:
                                st.error("Nenhum treinamento foi excluído.")
                    # O bloco "with" já terminou: o COMMIT foi feito.
                    # st.rerun() precisa vir depois, nunca dentro do "with".
                    if excluido:
                        st.session_state["aviso_treinamentos"] = (
                            "Treinamento excluído com sucesso."
                        )
                        st.session_state.pop("confirmar_exclusao_treinamento", None)
                        st.rerun()
                except Exception:
                    st.error(
                        "Não foi possível excluir o treinamento. "
                        "Verifique os logs do aplicativo."
                    )


# ======================================================
# PRESENÇAS
# ======================================================

elif menu == "Presenças":
    st.header("Registro de presenças")
    treinamentos = listar_treinamentos()
    if treinamentos.empty:
        st.info("Cadastre um treinamento antes de registrar presenças.")
        st.stop()

    mapa_treinamentos = {
        (
            f'{r["data"]}{sufixo_dia2(r)} | {r["titulo"]} | {r["hora_inicio"]} '
            f'| Status: {r["situacao"]} | ID {r["id"]}'
        ): int(r["id"])
        for _, r in treinamentos.iterrows()
    }
    escolha = st.selectbox("Selecione o treinamento", list(mapa_treinamentos.keys()))
    tid = mapa_treinamentos[escolha]
    treinamento = treinamentos[treinamentos["id"] == tid].iloc[0]

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
        st.warning("Este treinamento não tem colaboradores elegíveis ativos.")
        st.stop()
    if treinamento["situacao"] == "Cancelado":
        st.warning("Este treinamento está cancelado. Não é possível registrar presenças.")
        st.stop()
    if treinamento["situacao"] == "Remarcado":
        st.warning(
            "Este treinamento está marcado como Remarcado. "
            "Confira a nova data antes de registrar presenças."
        )

    ids_elegiveis = elegiveis["id"].astype(int).tolist()
    atuais = consultar(
        """
        SELECT colaborador_id, presente, presente_dia1, presente_dia2
        FROM presencas
        WHERE treinamento_id = ?
        """,
        (tid,),
    )
    presentes_atuais = set(
        atuais.loc[atuais["presente"] == 1, "colaborador_id"].astype(int).tolist()
    )
    nomes = {
        int(r["id"]): (
            f'{r["nome"]} | Matrícula: {r["matricula"] or "não informada"}'
        )
        for _, r in elegiveis.iterrows()
    }
    selecionados_atuais = [
        nomes[cid] for cid in ids_elegiveis if cid in presentes_atuais
    ]

    data_dia2_texto = texto_data_dia2(treinamento["data_dia2"])
    dois_dias = bool(data_dia2_texto)

    # Presença por dia (somente treinamentos em dois dias).
    dia1_atual, dia2_atual = set(), set()
    for _, linha_p in atuais.iterrows():
        cid_p = int(linha_p["colaborador_id"])
        p1, p2 = linha_p["presente_dia1"], linha_p["presente_dia2"]
        if pd.notna(p2) and int(p2) == 1:
            dia2_atual.add(cid_p)
        if pd.notna(p1):
            if int(p1) == 1:
                dia1_atual.add(cid_p)
        elif pd.notna(linha_p["presente"]) and int(linha_p["presente"]) == 1 \
                and cid_p not in dia2_atual:
            # Registro feito antes do recurso de dois dias: vale para o 1º dia.
            dia1_atual.add(cid_p)

    with st.form("form_presencas"):
        if dois_dias:
            st.caption(
                "Treinamento em dois dias: quem estiver presente em pelo menos "
                "um dos dias é contabilizado como presente. Só é ausência "
                "quem faltar nos dois."
            )
            opcoes_presenca = [nomes[cid] for cid in ids_elegiveis]
            presentes_dia1 = st.multiselect(
                f'Presentes no 1º dia ({str(treinamento["data"])[:10]})',
                options=opcoes_presenca,
                default=[nomes[cid] for cid in ids_elegiveis if cid in dia1_atual],
                key=f"presentes_dia1_{tid}",
            )
            presentes_dia2 = st.multiselect(
                f"Presentes no 2º dia ({data_dia2_texto})",
                options=opcoes_presenca,
                default=[nomes[cid] for cid in ids_elegiveis if cid in dia2_atual],
                key=f"presentes_dia2_{tid}",
            )
        else:
            presentes = st.multiselect(
                "Selecione quem esteve presente",
                options=[nomes[cid] for cid in ids_elegiveis],
                default=selecionados_atuais,
            )
        salvar_presencas = st.form_submit_button("Salvar presenças")
        if salvar_presencas:
            try:
                with conectar() as conn:
                    if dois_dias:
                        ids_dia1 = {cid for cid in ids_elegiveis if nomes[cid] in presentes_dia1}
                        ids_dia2 = {cid for cid in ids_elegiveis if nomes[cid] in presentes_dia2}
                        for cid in ids_elegiveis:
                            p1 = 1 if cid in ids_dia1 else 0
                            p2 = 1 if cid in ids_dia2 else 0
                            conn.execute(
                                """
                                INSERT INTO presencas
                                (treinamento_id, colaborador_id, presente,
                                 presente_dia1, presente_dia2)
                                VALUES (?, ?, ?, ?, ?)
                                ON CONFLICT(treinamento_id, colaborador_id)
                                DO UPDATE SET
                                    presente = excluded.presente,
                                    presente_dia1 = excluded.presente_dia1,
                                    presente_dia2 = excluded.presente_dia2,
                                    atualizado_em = CURRENT_TIMESTAMP::text
                                """,
                                (tid, cid, 1 if (p1 or p2) else 0, p1, p2),
                            )
                    else:
                        presentes_ids = {
                            cid for cid in ids_elegiveis if nomes[cid] in presentes
                        }
                        for cid in ids_elegiveis:
                            conn.execute(
                                """
                                INSERT INTO presencas
                                (treinamento_id, colaborador_id, presente)
                                VALUES (?, ?, ?)
                                ON CONFLICT(treinamento_id, colaborador_id)
                                DO UPDATE SET
                                    presente = excluded.presente,
                                    presente_dia1 = NULL,
                                    presente_dia2 = NULL,
                                    atualizado_em = CURRENT_TIMESTAMP::text
                                """,
                                (tid, cid, 1 if cid in presentes_ids else 0),
                            )
                st.success("Presenças salvas com sucesso.")
                st.rerun()
            except Exception:
                st.error(
                    "Não foi possível salvar as presenças. "
                    "Verifique os logs do aplicativo."
                )

    if treinamento["situacao"] != "Realizado":
        st.info(
            "Para contabilizar ausências, altere o status para Realizado "
            "na aba Treinamentos depois que o treinamento terminar."
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
            COALESCE(t.data_dia2, t.data::text) AS data_fim,
            t.situacao,
            c.nome,
            c.matricula,
            c.cargo,
            p.presente
        FROM elegibilidade e
        JOIN treinamentos t ON t.id = e.treinamento_id
        JOIN colaboradores c ON c.id = e.colaborador_id
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

        resumo.loc[resumo["situacao"] == "Cancelado", "resultado"] = "Cancelado"

        realizado_e_data_passada = (
            (resumo["situacao"] == "Realizado")
            & (resumo["data_fim"].astype(str).str[:10] <= hoje)
        )
        resumo.loc[
            realizado_e_data_passada & (resumo["presente"] == 1),
            "resultado",
        ] = "Presente"

        # Se o treinamento foi realizado e não existe confirmação (NULL)
        # ou está explicitamente marcado como não presente (0), é ausência.
        resumo.loc[
            realizado_e_data_passada & (
                resumo["presente"].isna() | (resumo["presente"] == 0)
            ),
            "resultado",
        ] = "Ausente"

        resumo.loc[
            (resumo["situacao"] != "Realizado")
            & (resumo["situacao"] != "Cancelado"),
            "resultado",
        ] = "Pendente"

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Presenças", int((resumo["resultado"] == "Presente").sum()))
        c2.metric("Ausências", int((resumo["resultado"] == "Ausente").sum()))
        c3.metric("Pendências", int((resumo["resultado"] == "Pendente").sum()))
        c4.metric("Cancelados", int((resumo["resultado"] == "Cancelado").sum()))

        st.subheader("Detalhamento")
        filtro_resultado = st.multiselect(
            "Filtrar por resultado",
            options=["Presente", "Ausente", "Pendente", "Cancelado"],
            default=["Presente", "Ausente", "Pendente", "Cancelado"],
        )
        filtro_treinamento = st.text_input("Filtrar por nome do treinamento")
        exibicao = resumo[resumo["resultado"].isin(filtro_resultado)].copy()
        if filtro_treinamento:
            exibicao = exibicao[
                exibicao["treinamento"].fillna("").str.contains(
                    filtro_treinamento, case=False, na=False, regex=False
                )
            ]
        colunas_relatorio = [
            "treinamento_id", "treinamento", "data", "situacao",
            "nome", "matricula", "cargo", "resultado",
        ]
        st.dataframe(
            exibicao[colunas_relatorio],
            hide_index=True,
            use_container_width=True,
        )

        csv = exibicao[colunas_relatorio].to_csv(
            index=False, sep=";", encoding="utf-8-sig"
        )
        st.download_button(
            "Exportar relatório em CSV",
            data=csv,
            file_name="relatorio_assiduidade.csv",
            mime="text/csv",
        )
