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
    hoje = date.today().isoformat()

    with conectar() as conn:
        return conn.execute(
            """
            SELECT
                t.id,
                t.titulo,
                t.data,
                t.hora_inicio,
                t.hora_fim,
                t.situacao,
                p.presente
            FROM elegibilidade e
            JOIN treinamentos t
              ON t.id = e.treinamento_id
            LEFT JOIN presencas p
              ON p.treinamento_id = t.id
             AND p.colaborador_id = e.colaborador_id
            WHERE e.colaborador_id = ?
              AND t.data = ?
              AND t.situacao <> 'Cancelado'
            ORDER BY t.hora_inicio, t.titulo
            """,
            (colaborador_id, hoje),
        ).fetchall()


def confirmar_presenca(treinamento_id, colaborador_id):
    """
    Grava a presença no banco existente.
    Uma presença já marcada como presente não pode ser confirmada novamente.
    """
    with conectar() as conn:
        # Revalida os requisitos no momento da gravação, evitando confiar
        # apenas nos dados que foram exibidos anteriormente na página.
        registro = conn.execute(
            """
            SELECT t.id, t.situacao, t.data, c.ativo
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

        if registro["data"] != date.today().isoformat():
            return False, "A confirmação só está disponível na data do treinamento."

        atual = conn.execute(
            """
            SELECT presente
            FROM presencas
            WHERE treinamento_id = ? AND colaborador_id = ?
            """,
            (treinamento_id, colaborador_id),
        ).fetchone()

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

                    if treinamento["presente"] == 1:
                        st.success("Sua presença já foi registrada.")
                    else:
                        botao = st.button(
                            "Confirmar minha presença",
                            key=f"confirmar_{treinamento['id']}_{colaborador['id']}",
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
