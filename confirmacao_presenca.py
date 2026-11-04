import psycopg2
from datetime import date

import streamlit as st

from db_postgres import conectar, inicializar_banco


# ======================================================
# CONFIGURAÇÃO
# ======================================================

st.set_page_config(
    page_title="Confirmação de Presença",
    page_icon="✅",
    layout="centered",
)

# Usa o mesmo PostgreSQL da área administrativa.
inicializar_banco()


@st.cache_resource(show_spinner=False)
def garantir_colunas_dois_dias():
    """Garante as colunas do recurso "treinamento em dois dias".

    É o mesmo ajuste feito pelo App.py (ADD COLUMN IF NOT EXISTS), repetido aqui
    para este aplicativo funcionar mesmo se for publicado antes do administrativo.
    Não apaga nem altera dados existentes.
    """
    with conectar() as conn:
        conn.execute("ALTER TABLE treinamentos ADD COLUMN IF NOT EXISTS data_dia2 TEXT", ())
        conn.execute("ALTER TABLE presencas ADD COLUMN IF NOT EXISTS presente_dia1 INTEGER", ())
        conn.execute("ALTER TABLE presencas ADD COLUMN IF NOT EXISTS presente_dia2 INTEGER", ())
    return True


try:
    garantir_colunas_dois_dias()
except (psycopg2.Error, RuntimeError) as erro:
    st.error(f"Não foi possível preparar o banco de dados: {erro}")
    st.stop()


# ======================================================
# REGRAS DE DIA E PRESENÇA
# ======================================================

def dia_do_treinamento(data, data_dia2, hoje):
    """Retorna 1 se hoje é o 1º dia, 2 se hoje é o 2º dia e 0 caso contrário."""
    if str(data or "")[:10] == hoje:
        return 1
    if data_dia2 and str(data_dia2)[:10] == hoje:
        return 2
    return 0


def presenca_por_dia(presente, presente_dia1, presente_dia2):
    """Devolve (presente_no_dia1, presente_no_dia2).

    Registros feitos antes do recurso de dois dias têm presente_dia1 vazio;
    nesse caso a presença vale para o 1º dia.
    """
    dia2 = presente_dia2 == 1
    if presente_dia1 is not None:
        dia1 = presente_dia1 == 1
    else:
        dia1 = (presente == 1) and not dia2
    return dia1, dia2


# ======================================================
# CONSULTAS E GRAVAÇÃO
# ======================================================

def buscar_colaborador_por_matricula(matricula):
    with conectar() as conn:
        return conn.execute(
            """
            SELECT id, nome, matricula
            FROM colaboradores
            WHERE TRIM(COALESCE(matricula, '')) = ?
              AND ativo = 1
            LIMIT 1
            """,
            (matricula,),
        ).fetchone()


def listar_treinamentos_de_hoje(colaborador_id):
    """Treinamentos cujo 1º ou 2º dia é hoje, já com o estado da presença de hoje."""
    hoje = date.today().isoformat()

    with conectar() as conn:
        linhas = conn.execute(
            """
            SELECT
                t.id,
                t.titulo,
                t.data,
                t.data_dia2,
                t.hora_inicio,
                t.hora_fim,
                t.situacao,
                p.presente,
                p.presente_dia1,
                p.presente_dia2
            FROM elegibilidade e
            JOIN treinamentos t
              ON t.id = e.treinamento_id
            LEFT JOIN presencas p
              ON p.treinamento_id = t.id
             AND p.colaborador_id = e.colaborador_id
            WHERE e.colaborador_id = ?
              AND (t.data = ? OR t.data_dia2 = ?)
              AND t.situacao <> 'Cancelado'
            ORDER BY t.hora_inicio, t.titulo
            """,
            (colaborador_id, hoje, hoje),
        ).fetchall()

    treinamentos = []
    for linha in linhas:
        dois_dias = bool(linha["data_dia2"])
        dia_hoje = dia_do_treinamento(linha["data"], linha["data_dia2"], hoje)
        dia1_ok, dia2_ok = presenca_por_dia(
            linha["presente"], linha["presente_dia1"], linha["presente_dia2"]
        )
        if dois_dias:
            presente_hoje = dia1_ok if dia_hoje == 1 else dia2_ok
            presente_outro_dia = dia2_ok if dia_hoje == 1 else dia1_ok
        else:
            presente_hoje = linha["presente"] == 1
            presente_outro_dia = False

        treinamentos.append({
            "id": linha["id"],
            "titulo": linha["titulo"],
            "data": linha["data"],
            "data_dia2": linha["data_dia2"],
            "hora_inicio": linha["hora_inicio"],
            "hora_fim": linha["hora_fim"],
            "dois_dias": dois_dias,
            "dia_hoje": dia_hoje,
            "presente_hoje": presente_hoje,
            "presente_outro_dia": presente_outro_dia,
        })
    return treinamentos


def confirmar_presenca(treinamento_id, colaborador_id):
    """
    Grava a presença no banco existente.
    Em treinamentos de dois dias, a confirmação vale para o dia de hoje e a
    presença em qualquer um dos dias conta como presente no treinamento.
    Uma presença já registrada para o dia de hoje não pode ser confirmada
    novamente.
    """
    hoje = date.today().isoformat()

    with conectar() as conn:
        # Revalida os requisitos no momento da gravação, evitando confiar
        # apenas nos dados que foram exibidos anteriormente na página.
        registro = conn.execute(
            """
            SELECT t.id, t.situacao, t.data, t.data_dia2, c.ativo
            FROM treinamentos t
            JOIN elegibilidade e ON e.treinamento_id = t.id
            JOIN colaboradores c ON c.id = e.colaborador_id
            WHERE t.id = ?
              AND c.id = ?
            """,
            (treinamento_id, colaborador_id),
        ).fetchone()

        if registro is None:
            return False, "Este colaborador não está elegível para o treinamento."

        if registro["ativo"] != 1:
            return False, "O cadastro deste colaborador não está ativo."

        if registro["situacao"] == "Cancelado":
            return False, "Este treinamento foi cancelado."

        dia = dia_do_treinamento(registro["data"], registro["data_dia2"], hoje)
        if dia == 0:
            return False, "A confirmação só está disponível na data do treinamento."

        atual = conn.execute(
            """
            SELECT presente, presente_dia1, presente_dia2
            FROM presencas
            WHERE treinamento_id = ? AND colaborador_id = ?
            """,
            (treinamento_id, colaborador_id),
        ).fetchone()

        dois_dias = bool(registro["data_dia2"])

        if not dois_dias:
            if atual is not None and atual["presente"] == 1:
                return False, "A presença deste treinamento já foi registrada."

            conn.execute(
                """
                INSERT INTO presencas
                    (treinamento_id, colaborador_id, presente, observacao,
                     atualizado_em)
                VALUES (?, ?, 1, '', CURRENT_TIMESTAMP::text)
                ON CONFLICT(treinamento_id, colaborador_id)
                DO UPDATE SET
                    presente = 1,
                    atualizado_em = CURRENT_TIMESTAMP::text
                """,
                (treinamento_id, colaborador_id),
            )
            return True, "Presença confirmada com sucesso!"

        # Treinamento em dois dias: registra o dia de hoje sem apagar o outro.
        if atual is None:
            dia1_ok = dia2_ok = False
        else:
            dia1_ok, dia2_ok = presenca_por_dia(
                atual["presente"], atual["presente_dia1"], atual["presente_dia2"]
            )

        if (dia == 1 and dia1_ok) or (dia == 2 and dia2_ok):
            return False, "A presença deste dia do treinamento já foi registrada."

        if dia == 1:
            dia1_ok = True
        else:
            dia2_ok = True

        conn.execute(
            """
            INSERT INTO presencas
                (treinamento_id, colaborador_id, presente, presente_dia1,
                 presente_dia2, observacao, atualizado_em)
            VALUES (?, ?, 1, ?, ?, '', CURRENT_TIMESTAMP::text)
            ON CONFLICT(treinamento_id, colaborador_id)
            DO UPDATE SET
                presente = 1,
                presente_dia1 = excluded.presente_dia1,
                presente_dia2 = excluded.presente_dia2,
                atualizado_em = CURRENT_TIMESTAMP::text
            """,
            (
                treinamento_id,
                colaborador_id,
                1 if dia1_ok else 0,
                1 if dia2_ok else 0,
            ),
        )

    return True, f"Presença do {dia}º dia confirmada com sucesso!"


# ======================================================
# INTERFACE DO COLABORADOR
# ======================================================

st.title("✅ Confirmação de presença")
st.caption("Sistema de Assiduidade | Educação Continuada")
st.write(
    "Informe sua matrícula para consultar os treinamentos de hoje "
    "em que você está inscrito."
)

if "colaborador_confirmacao" not in st.session_state:
    st.session_state["colaborador_confirmacao"] = None

if "matricula_confirmacao" not in st.session_state:
    st.session_state["matricula_confirmacao"] = ""

if "mensagem_presenca" in st.session_state:
    st.success(st.session_state.pop("mensagem_presenca"))

with st.form("form_identificacao"):
    matricula_digitada = st.text_input(
        "Número de matrícula",
        value=st.session_state["matricula_confirmacao"],
        placeholder="Digite sua matrícula",
        help="Digite a matrícula exatamente como consta no cadastro.",
    ).strip()
    consultar_treinamentos = st.form_submit_button(
        "Consultar treinamentos",
        use_container_width=True,
    )

if consultar_treinamentos:
    if not matricula_digitada:
        st.error("Informe sua matrícula.")
        st.session_state["colaborador_confirmacao"] = None
        st.session_state["matricula_confirmacao"] = ""
    else:
        try:
            colaborador = buscar_colaborador_por_matricula(matricula_digitada)

            if colaborador is None:
                st.session_state["colaborador_confirmacao"] = None
                st.session_state["matricula_confirmacao"] = matricula_digitada
                st.error(
                    "Matrícula não encontrada ou colaborador inativo. "
                    "Confira os dados ou procure o responsável pelo sistema."
                )
            else:
                st.session_state["colaborador_confirmacao"] = {
                    "id": int(colaborador["id"]),
                    "nome": colaborador["nome"],
                    "matricula": colaborador["matricula"] or matricula_digitada,
                }
                st.session_state["matricula_confirmacao"] = matricula_digitada
        except (psycopg2.Error, RuntimeError) as erro:
            st.error(f"Não foi possível consultar o banco de dados: {erro}")

colaborador = st.session_state.get("colaborador_confirmacao")

if colaborador:
    st.divider()
    st.subheader(f"Olá, {colaborador['nome']}!")

    try:
        treinamentos = listar_treinamentos_de_hoje(colaborador["id"])

        if not treinamentos:
            st.info(
                "Não há treinamentos disponíveis para confirmação hoje "
                "no seu cadastro."
            )
        else:
            st.write("**Treinamentos disponíveis hoje**")

            for treinamento in treinamentos:
                with st.container(border=True):
                    st.markdown(f"**{treinamento['titulo']}**")
                    st.caption(
                        f"Horário: {treinamento['hora_inicio']}–"
                        f"{treinamento['hora_fim']}"
                    )
                    if treinamento["dois_dias"]:
                        st.caption(
                            f"Treinamento em dois dias "
                            f"({str(treinamento['data'])[:10]} e "
                            f"{str(treinamento['data_dia2'])[:10]}). "
                            f"Hoje é o {treinamento['dia_hoje']}º dia."
                        )

                    if treinamento["presente_hoje"]:
                        st.success("Sua presença de hoje já foi registrada.")
                    else:
                        if treinamento["presente_outro_dia"]:
                            st.info(
                                "Você já tem presença registrada no outro dia "
                                "deste treinamento, então não será contado como "
                                "ausente. Confirmar hoje é opcional."
                            )
                        botao = st.button(
                            "Confirmar minha presença",
                            key=(
                                f"confirmar_{treinamento['id']}_"
                                f"{colaborador['id']}_{treinamento['dia_hoje']}"
                            ),
                            use_container_width=True,
                        )

                        if botao:
                            try:
                                sucesso, mensagem = confirmar_presenca(
                                    int(treinamento["id"]),
                                    int(colaborador["id"]),
                                )
                                if sucesso:
                                    st.session_state["mensagem_presenca"] = mensagem
                                    st.rerun()
                                else:
                                    st.warning(mensagem)
                            except (psycopg2.Error, RuntimeError) as erro:
                                st.error(
                                    "Não foi possível salvar a presença. "
                                    f"Detalhes: {erro}"
                                )

    except (psycopg2.Error, RuntimeError) as erro:
        st.error(f"Não foi possível carregar os treinamentos: {erro}")

st.divider()
st.caption(
    "A confirmação é vinculada à matrícula informada. "
    "A matrícula, sozinha, não comprova a identidade de quem está usando a página."
)
