import os
from copy import deepcopy
import re
import unicodedata
from datetime import date, time
from io import BytesIO
from pathlib import Path

from docx import Document
from openpyxl.chart import BarChart, Reference

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
    """Gera planilha Excel com participações, indicadores e gráfico de assiduidade."""
    buffer = BytesIO()
    resumo = calcular_resumo_assiduidade(dados)
    colunas = [
        "treinamento_id", "treinamento", "data", "data_fim", "situacao",
        "nome", "matricula", "cargo", "presente", "resultado",
    ]
    exportacao = dados.reindex(columns=colunas).copy()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        exportacao.to_excel(writer, sheet_name="Participações", index=False)
        resumo.to_excel(writer, sheet_name="Assiduidade", index=False)

        indicadores = pd.DataFrame([{
            "Colaboradores analisados": int(resumo["colaborador_id"].nunique()) if not resumo.empty else 0,
            "Presenças": int((dados["resultado"] == "Presente").sum()) if not dados.empty else 0,
            "Ausências": int((dados["resultado"] == "Ausente").sum()) if not dados.empty else 0,
            "Pendências": int((dados["resultado"] == "Pendente").sum()) if not dados.empty else 0,
            "Cancelados": int((dados["resultado"] == "Cancelado").sum()) if not dados.empty else 0,
        }])
        indicadores.to_excel(writer, sheet_name="Indicadores", index=False)

        ws = writer.book["Assiduidade"]
        if len(resumo) > 0:
            grafico = BarChart()
            grafico.type = "bar"
            grafico.style = 10
            grafico.title = "Taxa de presença por colaborador"
            grafico.y_axis.title = "Colaborador"
            grafico.x_axis.title = "Taxa de presença (%)"
            grafico.height = 10
            grafico.width = 20
            coluna_taxa = resumo.columns.get_loc("taxa_presenca") + 1
            dados_grafico = Reference(
                ws, min_col=coluna_taxa, min_row=1, max_row=len(resumo) + 1
            )
            categorias = Reference(ws, min_col=2, min_row=2, max_row=len(resumo) + 1)
            grafico.add_data(dados_grafico, titles_from_data=True)
            grafico.set_categories(categorias)
            ws.add_chart(grafico, "L2")

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


def _definir_texto_celula(celula, texto):
    celula.text = ""
    if celula.paragraphs:
        celula.paragraphs[0].add_run(str(texto))


def gerar_lista_presenca_word(treinamento_id, titulo_treinamento):
    """Preenche o modelo oficial ANEXO 0185 com presenças internas e externas."""
    caminho_modelo = Path(__file__).parent / "modelo_anexo_0185.docx"
    if not caminho_modelo.exists():
        raise FileNotFoundError(
            "O arquivo modelo_anexo_0185.docx não está na pasta do aplicativo."
        )

    internos = consultar(
        """
        SELECT
            c.nome,
            c.cargo,
            'UCM/MI' AS instituicao,
            CASE
                WHEN UPPER(TRIM(COALESCE(c.cargo, ''))) LIKE '%RJU'
                    THEN 'UFU'
                ELSE 'EBSERH'
            END AS vinculo
        FROM presencas p
        JOIN colaboradores c ON c.id = p.colaborador_id
        WHERE p.treinamento_id = ? AND p.presente = 1 AND c.ativo = 1
        ORDER BY c.nome
        """,
        (treinamento_id,),
    )
    externos = consultar(
        """
        SELECT
            pe.nome,
            '' AS cargo,
            'UFU' AS instituicao,
            'UFU' AS vinculo
        FROM presencas_externas px
        JOIN participantes_externos pe
            ON pe.id = px.participante_externo_id
        WHERE px.treinamento_id = ? AND px.presente = 1
        ORDER BY pe.nome
        """,
        (treinamento_id,),
    )
    participantes = pd.concat([internos, externos], ignore_index=True)
    if participantes.empty:
        raise ValueError("Não há presenças confirmadas para este treinamento.")

    documento = Document(str(caminho_modelo))

    # Mantém o cabeçalho oficial, mas remove os dados de exemplo.
    campos_cabecalho = (
        "Entidade Executora:", "Local de Realização:", "Horário de Início:",
        "Horário de Término:", "Carga horária:", "Data:",
        "Nome completo do(s)", "Instrutor(es):", "Conteúdo abordado:",
    )
    for tabela in documento.tables:
        for linha in tabela.rows:
            for celula in linha.cells:
                texto_original = celula.text.strip()
                if "Atividade:" in texto_original:
                    _definir_texto_celula(celula, f"Atividade: {titulo_treinamento}")
                elif any(campo in texto_original for campo in campos_cabecalho):
                    rotulo = next(
                        (campo for campo in campos_cabecalho if campo in texto_original),
                        "",
                    )
                    _definir_texto_celula(celula, rotulo)

    linhas_participantes = []
    for tabela in documento.tables:
        indice_cabecalho = None
        for indice, linha in enumerate(tabela.rows):
            texto_linha = " ".join(c.text for c in linha.cells).casefold()
            if "participante" in texto_linha and "assinatura" in texto_linha:
                indice_cabecalho = indice
                break
        if indice_cabecalho is not None:
            for linha in tabela.rows[indice_cabecalho + 1:]:
                if len(linha.cells) >= 10:
                    linhas_participantes.append(linha)

    # O modelo é usado apenas como referência visual. Se houver mais
    # participantes do que linhas disponíveis, cria novas linhas com a mesma
    # estrutura e formatação da última linha de participantes.
    if len(participantes) > len(linhas_participantes):
        tabelas_com_participantes = []
        for tabela in documento.tables:
            for indice, linha in enumerate(tabela.rows):
                texto_linha = " ".join(c.text for c in linha.cells).casefold()
                if "participante" in texto_linha and "assinatura" in texto_linha:
                    linhas_da_tabela = [
                        r for r in tabela.rows[indice + 1:] if len(r.cells) >= 10
                    ]
                    if linhas_da_tabela:
                        tabelas_com_participantes.append(
                            (tabela, linhas_da_tabela)
                        )
                    break

        if not tabelas_com_participantes:
            raise ValueError(
                "Não foi possível identificar uma linha-base de participantes no modelo."
            )

        tabela_final, linhas_finais = tabelas_com_participantes[-1]
        linha_base = linhas_finais[-1]
        quantidade_extra = len(participantes) - len(linhas_participantes)

        for _ in range(quantidade_extra):
            # Duplica a linha-base completa do modelo, preservando exatamente
            # as células mescladas, larguras, bordas, alturas e formatação.
            # Isso evita reconstruir manualmente os índices da tabela.
            nova_linha_xml = deepcopy(linha_base._tr)
            tabela_final._tbl.append(nova_linha_xml)
            nova_linha = tabela_final.rows[-1]
            linhas_participantes.append(nova_linha)

    # Limpa as linhas de exemplo e preenche apenas as presenças confirmadas.
    for numero, linha in enumerate(linhas_participantes, start=1):
        for celula in linha.cells:
            _definir_texto_celula(celula, "")
        indice = numero - 1
        if indice >= len(participantes):
            continue
        participante = participantes.iloc[indice]
        celulas = linha.cells
        _definir_texto_celula(celulas[0], numero)
        _definir_texto_celula(celulas[1], participante.get("nome", ""))
        _definir_texto_celula(celulas[4], participante.get("cargo", "") or "")
        _definir_texto_celula(celulas[6], participante.get("instituicao", "") or "")
        _definir_texto_celula(celulas[7], participante.get("vinculo", "") or "")
        # As células de assinatura permanecem vazias.

    saida = BytesIO()
    documento.save(saida)
    saida.seek(0)
    return saida.getvalue()


def exibir_historico_individual():
    st.header("Histórico individual de assiduidade")
    dados = carregar_relatorio_interno()
    if dados.empty:
        st.info("Ainda não há participações internas registradas.")
        return

    dados["data_filtro"] = pd.to_datetime(dados["data"], errors="coerce")
    datas = dados["data_filtro"].dropna()
    inicio = datas.min().date() if not datas.empty else date.today()
    fim = datas.max().date() if not datas.empty else date.today()

    with st.expander("Filtros do histórico", expanded=True):
        f1, f2, f3 = st.columns(3)
        with f1:
            periodo = st.date_input(
                "Período", value=(inicio, fim), key="historico_periodo"
            )
        with f2:
            cargos = sorted(dados["cargo"].fillna("").astype(str).unique().tolist())
            cargo = st.multiselect("Cargo", cargos, key="historico_cargo")
        with f3:
            situacoes = st.multiselect(
                "Situação", options=SITUACOES, default=SITUACOES,
                key="historico_situacoes",
            )

    if isinstance(periodo, tuple) and len(periodo) == 2:
        data_inicio, data_fim = periodo
    else:
        data_inicio = data_fim = periodo

    filtrado = dados[
        dados["data_filtro"].dt.date.between(data_inicio, data_fim)
        & dados["situacao"].isin(situacoes)
    ].copy()
    if cargo:
        filtrado = filtrado[filtrado["cargo"].isin(cargo)]

    if filtrado.empty:
        st.info("Nenhuma participação encontrada com os filtros selecionados.")
        return

    opcoes = {
        f'{r["nome"]} | Matrícula: {r["matricula"] or "não informada"}': int(r["colaborador_id"])
        for _, r in filtrado[["colaborador_id", "nome", "matricula"]]
        .drop_duplicates("colaborador_id").sort_values("nome").iterrows()
    }
    selecionado = st.selectbox("Colaborador", list(opcoes.keys()))
    colaborador_id = opcoes[selecionado]
    individual = filtrado[filtrado["colaborador_id"] == colaborador_id].copy()
    resumo_individual = calcular_resumo_assiduidade(individual)
    if not resumo_individual.empty:
        linha = resumo_individual.iloc[0]
        a, b, c, d = st.columns(4)
        a.metric("Taxa de presença", f'{linha["taxa_presenca"]:.1f}%' if pd.notna(linha["taxa_presenca"]) else "—")
        b.metric("Presenças", int(linha["presencas"]))
        c.metric("Ausências", int(linha["ausencias"]))
        d.metric("Pendências", int(linha["pendencias"]))

    st.subheader("Evolução da assiduidade")
    concluidos = individual[individual["resultado"].isin(["Presente", "Ausente"])].copy()
    if concluidos.empty:
        st.info("A evolução será exibida após a conclusão de treinamentos.")
    else:
        concluidos["mes"] = pd.to_datetime(concluidos["data"], errors="coerce").dt.to_period("M").astype(str)
        evolucao = concluidos.groupby("mes").agg(
            presencas=("resultado", lambda s: int((s == "Presente").sum())),
            participacoes=("resultado", "size"),
        ).reset_index()
        evolucao["taxa_presenca"] = evolucao["presencas"] / evolucao["participacoes"] * 100
        figura = px.line(
            evolucao, x="mes", y="taxa_presenca", markers=True,
            title="Taxa mensal de presença",
        )
        figura.update_yaxes(range=[0, 100], title="Taxa (%)")
        figura.update_xaxes(title="Mês")
        st.plotly_chart(figura, use_container_width=True)

    st.subheader("Detalhamento por treinamento")
    colunas = ["treinamento", "data", "data_fim", "situacao", "resultado"]
    st.dataframe(
        individual[colunas].rename(columns={
            "treinamento": "Treinamento", "data": "Data inicial",
            "data_fim": "Data final", "situacao": "Situação",
            "resultado": "Resultado",
        }),
        hide_index=True, use_container_width=True,
    )
    st.download_button(
        "Exportar histórico individual em CSV",
        data=individual[colunas].to_csv(index=False, sep=";", encoding="utf-8-sig"),
        file_name="historico_individual.csv",
        mime="text/csv",
    )


# ======================================================
# INTERFACE PRINCIPAL
# ======================================================

st.title("📊 Sistema de Assiduidade")
st.caption("Educação Continuada | Banco de dados PostgreSQL na nuvem")

menu = st.sidebar.radio(
    "Navegação",
    ["Visão geral", "Colaboradores", "Treinamentos", "Presenças", "Histórico individual", "Relatórios"],
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
        st.info(
            "Este treinamento não possui colaboradores elegíveis ativos. "
            "Você ainda poderá incluir participantes pela opção de presença manual, "
            "quando o treinamento estiver como Realizado."
        )
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

    st.divider()
    st.subheader("Adicionar presença manualmente")
    st.caption(
        "Use esta opção para incluir um colaborador ativo que participou do "
        "treinamento, mesmo que ele não esteja na lista de elegibilidade. "
        "O lançamento manual não altera a lista de elegibilidade."
    )

    if treinamento["situacao"] != "Realizado":
        st.info("O lançamento manual fica disponível para treinamentos com situação Realizado.")
    else:
        colaboradores_ativos = listar_colaboradores(ativos=True)
        if colaboradores_ativos.empty:
            st.warning("Não há colaboradores ativos cadastrados.")
        else:
            opcoes_manuais = {
                f'{r["nome"]} | Matrícula: {r["matricula"] or "não informada"} | {r["cargo"] or "Cargo não informado"}': int(r["id"])
                for _, r in colaboradores_ativos.iterrows()
            }
            with st.form(f"form_presenca_manual_{tid}"):
                colaborador_manual = st.selectbox(
                    "Colaborador", list(opcoes_manuais.keys()),
                    key=f"colaborador_manual_{tid}",
                )
                if dois_dias:
                    dia_manual = st.radio(
                        "Dia em que esteve presente",
                        options=["1º dia", "2º dia"], horizontal=True,
                        key=f"dia_manual_{tid}",
                    )
                else:
                    dia_manual = "Treinamento de um dia"
                    st.caption(f"Data do treinamento: {str(treinamento['data'])[:10]}")
                confirmar_manual = st.form_submit_button(
                    "Registrar presença manual", use_container_width=True
                )

            if confirmar_manual:
                cid_manual = opcoes_manuais[colaborador_manual]
                try:
                    with conectar() as conn:
                        if dois_dias:
                            registro = conn.execute(
                                """SELECT presente, presente_dia1, presente_dia2
                                   FROM presencas
                                   WHERE treinamento_id = ? AND colaborador_id = ?""",
                                (tid, cid_manual),
                            ).fetchone()
                            if registro:
                                p1_atual = registro["presente_dia1"]
                                p2_atual = registro["presente_dia2"]
                                if pd.isna(p1_atual):
                                    p1_atual = 1 if registro["presente"] == 1 else 0
                                if pd.isna(p2_atual):
                                    p2_atual = 0
                                p1_atual, p2_atual = int(p1_atual), int(p2_atual)
                            else:
                                p1_atual = p2_atual = 0
                            if dia_manual == "1º dia":
                                p1_atual = 1
                            else:
                                p2_atual = 1
                            conn.execute(
                                """INSERT INTO presencas
                                   (treinamento_id, colaborador_id, presente,
                                    presente_dia1, presente_dia2)
                                   VALUES (?, ?, 1, ?, ?)
                                   ON CONFLICT(treinamento_id, colaborador_id)
                                   DO UPDATE SET presente = 1,
                                     presente_dia1 = excluded.presente_dia1,
                                     presente_dia2 = excluded.presente_dia2,
                                     atualizado_em = CURRENT_TIMESTAMP::text""",
                                (tid, cid_manual, p1_atual, p2_atual),
                            )
                        else:
                            conn.execute(
                                """INSERT INTO presencas
                                   (treinamento_id, colaborador_id, presente)
                                   VALUES (?, ?, 1)
                                   ON CONFLICT(treinamento_id, colaborador_id)
                                   DO UPDATE SET presente = 1,
                                     presente_dia1 = NULL, presente_dia2 = NULL,
                                     atualizado_em = CURRENT_TIMESTAMP::text""",
                                (tid, cid_manual),
                            )
                    st.success("Presença manual registrada com sucesso.")
                    st.rerun()
                except Exception:
                    st.error(
                        "Não foi possível registrar a presença manual. "
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

elif menu == "Histórico individual":
    exibir_historico_individual()


elif menu == "Relatórios":
    st.header("Relatórios de assiduidade")
    resumo = consultar("""
        SELECT * FROM (
            SELECT
                t.id AS treinamento_id, t.titulo AS treinamento, t.data,
                COALESCE(t.data_dia2, t.data::text) AS data_fim,
                t.situacao, c.id AS colaborador_id, c.nome, c.matricula, c.cargo, p.presente
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
                t.situacao, c.id AS colaborador_id, c.nome, c.matricula, c.cargo, p.presente
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

        st.download_button(
            "Exportar relatório completo em Excel",
            data=gerar_excel_assiduidade(resumo),
            file_name="relatorio_assiduidade.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    st.divider()
    st.subheader("Participantes externos")
    try:
        externos = consultar(
            """
            SELECT t.titulo AS treinamento, t.data, t.hora_inicio,
                   pe.nome, pe.instituicao, pe.email, px.atualizado_em
            FROM presencas_externas px
            JOIN treinamentos t ON t.id = px.treinamento_id
            JOIN participantes_externos pe ON pe.id = px.participante_externo_id
            WHERE px.presente = 1
            ORDER BY t.data DESC, t.hora_inicio, pe.nome
            """
        )
        if externos.empty:
            st.info("Ainda não há participantes externos com presença registrada.")
        else:
            st.dataframe(externos, hide_index=True, use_container_width=True)
    except Exception:
        st.warning(
            "A tabela de participantes externos ainda não foi criada. "
            "Execute o arquivo SQL de atualização do banco enviado junto com esta versão."
        )

    st.divider()
    st.subheader("Gerar lista de presença — ANEXO 0185")
    treinamentos_lista = listar_treinamentos()
    if treinamentos_lista.empty:
        st.info("Cadastre um treinamento para gerar a lista.")
    else:
        mapa_lista = {
            formatar_treinamento(r): int(r["id"])
            for _, r in treinamentos_lista.iterrows()
        }
        escolha_lista = st.selectbox(
            "Treinamento para gerar a lista",
            list(mapa_lista.keys()),
            key="treinamento_lista_word",
        )
        if st.button("Gerar lista de presença em Word", use_container_width=True):
            try:
                id_lista = mapa_lista[escolha_lista]
                titulo_lista = treinamentos_lista.loc[
                    treinamentos_lista["id"] == id_lista, "titulo"
                ].iloc[0]
                arquivo_word = gerar_lista_presenca_word(id_lista, titulo_lista)
                st.download_button(
                    "Baixar lista de presença (.docx)",
                    data=arquivo_word,
                    file_name=f"lista_presenca_{id_lista}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"baixar_lista_word_{id_lista}",
                )
            except Exception as erro:
                st.error(f"Não foi possível gerar a lista: {erro}")
                st.exception(erro)
