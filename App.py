import os
from copy import deepcopy
import re
import unicodedata
from datetime import date, time
from io import BytesIO
from pathlib import Path

from docx import Document
from openpyxl.chart import BarChart, LineChart, PieChart, Reference

import pandas as pd
import plotly.express as px
import streamlit as st
from supabase import create_client

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


DOMINIOS_AUTORIZADOS = ("@ebserh.gov.br", "@hubrasil.gov.br")


def obter_config_supabase():
    """Lê apenas URL e chave pública; nunca utiliza service_role no aplicativo."""
    url = os.environ.get("SUPABASE_URL", "").strip()
    chave = os.environ.get("SUPABASE_ANON_KEY", "").strip()
    try:
        url = url or str(st.secrets.get("SUPABASE_URL", "")).strip()
        chave = chave or str(st.secrets.get("SUPABASE_ANON_KEY", "")).strip()
    except Exception:
        pass
    return url, chave


def cliente_autenticacao():
    url, chave = obter_config_supabase()
    if not url or not chave:
        return None
    return create_client(url, chave)


def email_institucional_valido(email):
    email = (email or "").strip().lower()
    return (
        len(email) <= 254
        and email.count("@") == 1
        and any(email.endswith(dominio) for dominio in DOMINIOS_AUTORIZADOS)
    )


def usuario_confirmado(usuario):
    if usuario is None:
        return False
    confirmado = getattr(usuario, "email_confirmed_at", None)
    if confirmado:
        return True
    # Compatibilidade com versões da resposta do supabase-py.
    return bool(getattr(usuario, "confirmed_at", None))


def interface_autenticacao():
    st.title("🔐 Acesso administrativo")
    st.caption("Cadastro permitido somente para e-mails institucionais autorizados.")

    cliente = cliente_autenticacao()
    if cliente is None:
        st.error(
            "Configuração de autenticação ausente. Cadastre SUPABASE_URL e "
            "SUPABASE_ANON_KEY nos Secrets da hospedagem (ou variáveis de ambiente)."
        )
        st.stop()

    token = st.session_state.get("admin_access_token")
    if token:
        try:
            resposta = cliente.auth.get_user(token)
            usuario = getattr(resposta, "user", None)
            email = getattr(usuario, "email", "") if usuario else ""
            if usuario and usuario_confirmado(usuario) and email_institucional_valido(email):
                st.session_state["admin_email"] = email
                with st.sidebar:
                    st.caption(f"Conectado: {email}")
                    if st.button("Sair", use_container_width=True):
                        try:
                            cliente.auth.sign_out()
                        except Exception:
                            pass
                        st.session_state.pop("admin_access_token", None)
                        st.session_state.pop("admin_email", None)
                        st.rerun()
                return
        except Exception:
            pass
        st.session_state.pop("admin_access_token", None)
        st.session_state.pop("admin_email", None)

    aba_login, aba_cadastro = st.tabs(["Entrar", "Criar conta"])

    with aba_login:
        with st.form("form_login_admin"):
            email_login = st.text_input("E-mail institucional", key="email_login").strip().lower()
            senha_login = st.text_input("Senha", type="password", key="senha_login")
            entrar = st.form_submit_button("Entrar", use_container_width=True)
        if entrar:
            if not email_institucional_valido(email_login):
                st.error("Use um e-mail terminado em @ebserh.gov.br ou @hubrasil.gov.br.")
            elif not senha_login:
                st.error("Informe sua senha.")
            else:
                try:
                    resposta = cliente.auth.sign_in_with_password(
                        {"email": email_login, "password": senha_login}
                    )
                    usuario = getattr(resposta, "user", None)
                    sessao = getattr(resposta, "session", None)
                    if not usuario_confirmado(usuario):
                        st.error("Confirme seu e-mail pelo link enviado antes de entrar.")
                    elif not sessao or not getattr(sessao, "access_token", None):
                        st.error("Não foi possível iniciar a sessão. Tente novamente.")
                    else:
                        st.session_state["admin_access_token"] = sessao.access_token
                        st.session_state["admin_email"] = email_login
                        st.rerun()
                except Exception:
                    st.error("Não foi possível entrar. Confira o e-mail, a senha e a confirmação do endereço.")

    with aba_cadastro:
        with st.form("form_cadastro_admin"):
            email_novo = st.text_input("E-mail institucional", key="email_novo").strip().lower()
            senha_nova = st.text_input("Crie uma senha", type="password", key="senha_nova")
            confirmar_senha = st.text_input("Confirme a senha", type="password", key="confirmar_senha")
            cadastrar = st.form_submit_button("Criar conta", use_container_width=True)
        if cadastrar:
            if not email_institucional_valido(email_novo):
                st.error("Cadastro permitido somente para @ebserh.gov.br ou @hubrasil.gov.br.")
            elif len(senha_nova) < 8:
                st.error("A senha deve ter pelo menos 8 caracteres.")
            elif senha_nova != confirmar_senha:
                st.error("As senhas não conferem.")
            else:
                try:
                    resposta = cliente.auth.sign_up({"email": email_novo, "password": senha_nova})
                    usuario = getattr(resposta, "user", None)
                    sessao = getattr(resposta, "session", None)
                    if usuario and usuario_confirmado(usuario) and sessao:
                        st.session_state["admin_access_token"] = sessao.access_token
                        st.session_state["admin_email"] = email_novo
                        st.success("Conta criada e e-mail confirmado.")
                        st.rerun()
                    else:
                        st.success(
                            "Cadastro iniciado. Enviamos um link de confirmação para "
                            "seu e-mail. Após confirmar, volte à página e entre com sua senha."
                        )
                except Exception:
                    st.error("Não foi possível criar a conta. Verifique se o e-mail já está cadastrado e tente novamente.")

    st.caption("A confirmação do e-mail é obrigatória. A senha é gerenciada pelo Supabase Auth.")
    st.stop()


interface_autenticacao()

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
    """Carrega elegíveis e participantes incluídos manualmente na presença."""
    return consultar("""
        SELECT * FROM (
            SELECT
                t.id AS treinamento_id, t.titulo AS treinamento, t.data,
                t.situacao, c.id AS colaborador_id, c.nome, c.matricula,
                c.cargo, p.presente
            FROM elegibilidade e
            JOIN treinamentos t ON t.id = e.treinamento_id
            JOIN colaboradores c ON c.id = e.colaborador_id
            LEFT JOIN presencas p
                ON p.treinamento_id = t.id AND p.colaborador_id = c.id
            WHERE c.ativo = 1

            UNION ALL

            SELECT
                t.id AS treinamento_id, t.titulo AS treinamento, t.data,
                t.situacao, c.id AS colaborador_id, c.nome, c.matricula,
                c.cargo, p.presente
            FROM presencas p
            JOIN treinamentos t ON t.id = p.treinamento_id
            JOIN colaboradores c ON c.id = p.colaborador_id
            WHERE c.ativo = 1
              AND NOT EXISTS (
                  SELECT 1 FROM elegibilidade e
                  WHERE e.treinamento_id = p.treinamento_id
                    AND e.colaborador_id = p.colaborador_id
              )
        ) participacoes
        ORDER BY data, treinamento, nome
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

        st.subheader("Monitoramento de colaboradores com assiduidade ≤ 30%")
        resumo_assiduidade = calcular_resumo_assiduidade(participacoes_filtradas)
        monitorados = resumo_assiduidade[
            resumo_assiduidade["taxa_presenca"].notna()
            & (resumo_assiduidade["taxa_presenca"] <= 30)
        ].sort_values(["taxa_presenca", "ausencias"], ascending=[True, False])
        if monitorados.empty:
            st.success("Nenhum colaborador com taxa de presença igual ou inferior a 30% nos filtros selecionados.")
        else:
            st.caption("Pendências e treinamentos cancelados não entram no cálculo da taxa.")
            st.dataframe(
                monitorados[[
                    "nome", "matricula", "cargo", "presencas", "ausencias",
                    "pendencias", "treinamentos_contabilizados", "taxa_presenca",
                ]].rename(columns={
                    "nome": "Colaborador", "matricula": "Matrícula",
                    "cargo": "Cargo", "presencas": "Presenças",
                    "ausencias": "Ausências", "pendencias": "Pendências",
                    "treinamentos_contabilizados": "Treinamentos contabilizados",
                    "taxa_presenca": "Taxa de presença (%)",
                }),
                hide_index=True, use_container_width=True,
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
# RECURSOS COMPLEMENTARES: ASSIDUIDADE, HISTÓRICO E EXPORTAÇÕES
# ======================================================

def carregar_relatorio_interno():
    """Carrega somente participações de colaboradores internos."""
    dados = consultar("""
        SELECT * FROM (
            SELECT
                t.id AS treinamento_id, t.titulo AS treinamento, t.data,
                COALESCE(t.data_dia2, t.data::text) AS data_fim,
                t.situacao, c.id AS colaborador_id, c.nome, c.matricula,
                c.cargo, p.presente
            FROM elegibilidade e
            JOIN treinamentos t ON t.id = e.treinamento_id
            JOIN colaboradores c ON c.id = e.colaborador_id
            LEFT JOIN presencas p
                ON p.treinamento_id = t.id AND p.colaborador_id = c.id
            WHERE c.ativo = 1

            UNION ALL

            SELECT
                t.id AS treinamento_id, t.titulo AS treinamento, t.data,
                COALESCE(t.data_dia2, t.data::text) AS data_fim,
                t.situacao, c.id AS colaborador_id, c.nome, c.matricula,
                c.cargo, p.presente
            FROM presencas p
            JOIN treinamentos t ON t.id = p.treinamento_id
            JOIN colaboradores c ON c.id = p.colaborador_id
            WHERE c.ativo = 1
              AND NOT EXISTS (
                  SELECT 1 FROM elegibilidade e
                  WHERE e.treinamento_id = p.treinamento_id
                    AND e.colaborador_id = p.colaborador_id
              )
        ) participacoes
        ORDER BY data DESC, treinamento, nome
    """)

    if dados.empty:
        dados["resultado"] = pd.Series(dtype="object")
        return dados

    hoje = date.today().isoformat()
    dados["resultado"] = "Pendente"
    dados.loc[dados["situacao"] == "Cancelado", "resultado"] = "Cancelado"

    treinamento_concluido = (
        (dados["situacao"] == "Realizado")
        & (dados["data_fim"].astype(str).str[:10] <= hoje)
    )
    dados.loc[
        treinamento_concluido & (dados["presente"] == 1), "resultado"
    ] = "Presente"
    dados.loc[
        treinamento_concluido
        & (dados["presente"].isna() | (dados["presente"] == 0)),
        "resultado",
    ] = "Ausente"
    return dados


def calcular_resumo_assiduidade(dados):
    """Taxa = presenças / (presenças + ausências); pendências/cancelados fora."""
    colunas = [
        "colaborador_id", "nome", "matricula", "cargo", "presencas",
        "ausencias", "pendencias", "cancelados", "treinamentos_contabilizados",
        "taxa_presenca",
    ]
    if dados is None or dados.empty:
        return pd.DataFrame(columns=colunas)

    linhas = []
    for (cid, nome, matricula, cargo), grupo in dados.groupby(
        ["colaborador_id", "nome", "matricula", "cargo"], dropna=False
    ):
        presencas = int((grupo["resultado"] == "Presente").sum())
        ausencias = int((grupo["resultado"] == "Ausente").sum())
        pendencias = int((grupo["resultado"] == "Pendente").sum())
        cancelados = int((grupo["resultado"] == "Cancelado").sum())
        contabilizados = presencas + ausencias
        taxa = (presencas / contabilizados * 100) if contabilizados else None
        linhas.append({
            "colaborador_id": cid,
            "nome": nome,
            "matricula": matricula,
            "cargo": cargo,
            "presencas": presencas,
            "ausencias": ausencias,
            "pendencias": pendencias,
            "cancelados": cancelados,
            "treinamentos_contabilizados": contabilizados,
            "taxa_presenca": taxa,
        })

    return pd.DataFrame(linhas, columns=colunas)


def gerar_excel_assiduidade(dados):
    """Gera relatório Excel com panorama, análises de assiduidade e dados individuais."""
    buffer = BytesIO()
    resumo = calcular_resumo_assiduidade(dados)

    colunas_participacoes = [
        "treinamento_id", "treinamento", "data", "data_fim", "situacao",
        "nome", "matricula", "cargo", "presente", "resultado",
    ]
    exportacao = dados.reindex(columns=colunas_participacoes).copy()

    # Panorama: situação dos treinamentos e resultado das participações.
    if dados.empty:
        por_situacao = pd.DataFrame(columns=["Situação", "Quantidade"])
        por_resultado = pd.DataFrame(columns=["Resultado", "Quantidade"])
        evolucao = pd.DataFrame(columns=["Mês", "Taxa de presença (%)", "Participações"])
        cargo = pd.DataFrame(columns=["Cargo", "Presente", "Ausente"])
    else:
        treinamentos_unicos = dados.drop_duplicates("treinamento_id")
        por_situacao = (
            treinamentos_unicos["situacao"].value_counts()
            .rename_axis("Situação").reset_index(name="Quantidade")
        )
        ordem_resultados = ["Presente", "Ausente", "Pendente", "Cancelado"]
        por_resultado = (
            dados["resultado"].value_counts()
            .reindex(ordem_resultados, fill_value=0)
            .rename_axis("Resultado").reset_index(name="Quantidade")
        )

        concluidas = dados[dados["resultado"].isin(["Presente", "Ausente"])].copy()
        if concluidas.empty:
            evolucao = pd.DataFrame(columns=["Mês", "Taxa de presença (%)", "Participações"])
        else:
            concluidas["Mês"] = pd.to_datetime(
                concluidas["data"], errors="coerce"
            ).dt.to_period("M").astype(str)
            mensal = concluidas.groupby("Mês").agg(
                Presenças=("resultado", lambda s: int(s.eq("Presente").sum())),
                Participações=("resultado", "size"),
            )
            mensal["Taxa de presença (%)"] = (
                mensal["Presenças"] / mensal["Participações"] * 100
            ).round(1)
            evolucao = mensal.reset_index()[
                ["Mês", "Taxa de presença (%)", "Participações"]
            ]

        cargo_base = resumo_por_cargo(dados)
        if cargo_base.empty:
            cargo = pd.DataFrame(columns=["Cargo", "Presente", "Ausente"])
        else:
            cargo = cargo_base.pivot(
                index="cargo", columns="resultado", values="quantidade"
            ).fillna(0).reset_index()
            cargo.columns.name = None
            for resultado in ["Presente", "Ausente"]:
                if resultado not in cargo.columns:
                    cargo[resultado] = 0
            cargo = cargo.rename(columns={"cargo": "Cargo"})[
                ["Cargo", "Presente", "Ausente"]
            ]

    indicadores = pd.DataFrame([{
        "Colaboradores analisados": int(resumo["colaborador_id"].nunique()) if not resumo.empty else 0,
        "Presenças": int((dados["resultado"] == "Presente").sum()) if not dados.empty else 0,
        "Ausências": int((dados["resultado"] == "Ausente").sum()) if not dados.empty else 0,
        "Pendências": int((dados["resultado"] == "Pendente").sum()) if not dados.empty else 0,
        "Cancelados": int((dados["resultado"] == "Cancelado").sum()) if not dados.empty else 0,
    }])

    monitoramento = resumo.rename(columns={
        "nome": "Colaborador", "matricula": "Matrícula", "cargo": "Cargo",
        "presencas": "Presenças", "ausencias": "Ausências",
        "pendencias": "Pendências", "cancelados": "Cancelados",
        "treinamentos_contabilizados": "Treinamentos contabilizados",
        "taxa_presenca": "Taxa de presença (%)",
    }).copy()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        indicadores.to_excel(writer, sheet_name="Indicadores", index=False)
        por_situacao.to_excel(writer, sheet_name="Panorama", index=False, startrow=0, startcol=0)
        por_resultado.to_excel(writer, sheet_name="Panorama", index=False, startrow=0, startcol=4)
        evolucao.to_excel(writer, sheet_name="Assiduidade", index=False, startrow=0, startcol=0)
        cargo.to_excel(writer, sheet_name="Assiduidade", index=False, startrow=0, startcol=4)
        monitoramento.to_excel(writer, sheet_name="Monitoramento individual", index=False)
        exportacao.to_excel(writer, sheet_name="Participações", index=False)

        ws_panorama = writer.book["Panorama"]
        if len(por_situacao) > 0:
            grafico_situacao = PieChart()
            grafico_situacao.title = "Situação dos treinamentos"
            grafico_situacao.height = 8
            grafico_situacao.width = 13
            valores = Reference(
                ws_panorama, min_col=2, min_row=1, max_row=len(por_situacao) + 1
            )
            categorias = Reference(
                ws_panorama, min_col=1, min_row=2, max_row=len(por_situacao) + 1
            )
            grafico_situacao.add_data(valores, titles_from_data=True)
            grafico_situacao.set_categories(categorias)
            ws_panorama.add_chart(grafico_situacao, "A8")

        if len(por_resultado) > 0:
            grafico_resultados = BarChart()
            grafico_resultados.type = "col"
            grafico_resultados.style = 10
            grafico_resultados.title = "Resultado das participações"
            grafico_resultados.y_axis.title = "Participações"
            grafico_resultados.height = 8
            grafico_resultados.width = 13
            valores = Reference(
                ws_panorama, min_col=6, min_row=1, max_row=len(por_resultado) + 1
            )
            categorias = Reference(
                ws_panorama, min_col=5, min_row=2, max_row=len(por_resultado) + 1
            )
            grafico_resultados.add_data(valores, titles_from_data=True)
            grafico_resultados.set_categories(categorias)
            ws_panorama.add_chart(grafico_resultados, "J8")

        ws_assiduidade = writer.book["Assiduidade"]
        if len(evolucao) > 0:
            grafico_evolucao = LineChart()
            grafico_evolucao.style = 13
            grafico_evolucao.title = "Evolução mensal da presença"
            grafico_evolucao.y_axis.title = "Taxa de presença (%)"
            grafico_evolucao.x_axis.title = "Mês"
            grafico_evolucao.y_axis.scaling.min = 0
            grafico_evolucao.y_axis.scaling.max = 100
            grafico_evolucao.height = 8
            grafico_evolucao.width = 15
            valores = Reference(
                ws_assiduidade, min_col=2, min_row=1, max_row=len(evolucao) + 1
            )
            categorias = Reference(
                ws_assiduidade, min_col=1, min_row=2, max_row=len(evolucao) + 1
            )
            grafico_evolucao.add_data(valores, titles_from_data=True)
            grafico_evolucao.set_categories(categorias)
            ws_assiduidade.add_chart(grafico_evolucao, "A10")

        if len(cargo) > 0:
            grafico_cargo = BarChart()
            grafico_cargo.type = "col"
            grafico_cargo.style = 10
            grafico_cargo.grouping = "clustered"
            grafico_cargo.title = "Presença por cargo"
            grafico_cargo.y_axis.title = "Participações"
            grafico_cargo.x_axis.title = "Cargo"
            grafico_cargo.height = 8
            grafico_cargo.width = 15
            valores = Reference(
                ws_assiduidade, min_col=6, max_col=7,
                min_row=1, max_row=len(cargo) + 1
            )
            categorias = Reference(
                ws_assiduidade, min_col=5, min_row=2, max_row=len(cargo) + 1
            )
            grafico_cargo.add_data(valores, titles_from_data=True)
            grafico_cargo.set_categories(categorias)
            ws_assiduidade.add_chart(grafico_cargo, "J10")

        for planilha in writer.book.worksheets:
            planilha.freeze_panes = "A2"
            planilha.auto_filter.ref = planilha.dimensions
            for coluna in planilha.columns:
                letra = coluna[0].column_letter
                maior = max(
                    (len(str(c.value)) for c in coluna if c.value is not None),
                    default=10,
                )
                planilha.column_dimensions[letra].width = min(max(maior + 2, 12), 42)

    buffer.seek(0)
    return buffer.getvalue()

