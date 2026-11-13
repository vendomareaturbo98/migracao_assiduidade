import psycopg2
from datetime import date

import streamlit as st

from db_postgres import conectar, inicializar_banco


st.set_page_config(
    page_title="Confirmação de Presença",
    page_icon="✅",
    layout="centered",
)

# Usa o mesmo PostgreSQL da área administrativa.
inicializar_banco()


@st.cache_resource(show_spinner=False)
def garantir_colunas_dois_dias():
    """Garante as colunas necessárias para treinamentos em dois dias."""
    with conectar() as conn:
        conn.execute(
            "ALTER TABLE treinamentos ADD COLUMN IF NOT EXISTS data_dia2 TEXT", ()
        )
        conn.execute(
            "ALTER TABLE presencas ADD COLUMN IF NOT EXISTS presente_dia1 INTEGER", ()
        )
        conn.execute(
            "ALTER TABLE presencas ADD COLUMN IF NOT EXISTS presente_dia2 INTEGER", ()
        )
    return True


try:
    garantir_colunas_dois_dias()
except (psycopg2.Error, RuntimeError) as erro:
    st.error(f"Não foi possível preparar o banco de dados: {erro}")
    st.stop()


def dia_do_treinamento(data, data_dia2, hoje):
    """Retorna 1 para o primeiro dia, 2 para o segundo ou 0 se não for hoje."""
    if str(data or "")[:10] == hoje:
        return 1
    if data_dia2 and str(data_dia2)[:10] == hoje:
        return 2
    return 0


def presenca_por_dia(presente, presente_dia1, presente_dia2):
    """Compatibiliza presenças antigas com o controle de treinamentos em dois dias."""
    dia2 = presente_dia2 == 1
    if presente_dia1 is not None:
        dia1 = presente_dia1 == 1
    else:
        dia1 = (presente == 1) and not dia2
    return dia1, dia2


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
    """Lista treinamentos elegíveis cujo primeiro ou segundo dia é hoje."""
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
            FROM treinamentos t
            INNER JOIN elegibilidade e
                ON e.treinamento_id = t.id
               AND e.colaborador_id = ?
            LEFT JOIN presencas p
                ON p.treinamento_id = t.id
               AND p.colaborador_id = ?
            WHERE (
                LEFT(COALESCE(t.data, ''), 10) = ?
                OR LEFT(COALESCE(t.data_dia2, ''), 10) = ?
            )
              AND LOWER(COALESCE(t.situacao, '')) <> 'cancelado'
            ORDER BY t.hora_inicio, t.titulo
            """,
            (colaborador_id, colaborador_id, hoje, hoje),
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

        treinamentos.append(
            {
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
            }
        )

    return treinamentos


def confirmar_presenca(treinamento_id, colaborador_id):
    """Registra a presença do colaborador no dia atual do treinamento."""
    hoje = date.today().isoformat()

    with conectar() as conn:
        # Revalida situação, atividade e elegibilidade no momento da gravação.
        registro = conn.execute(
            """
            SELECT t.id, t.situacao, t.data, t.data_dia2, c.ativo
            FROM treinamentos t
            JOIN colaboradores c ON c.id = ?
            JOIN elegibilidade e
                ON e.treinamento_id = t.id
               AND e.colaborador_id = c.id
            WHERE t.id = ?
            """,
            (colaborador_id, treinamento_id),
        ).fetchone()

        if registro is None:
            return False, (
                "Este treinamento não está disponível para sua matrícula. "
                "Confirme com o responsável se você está na lista de elegibilidade."
            )
        if registro["ativo"] != 1:
            return False, "O cadastro deste colaborador não está ativo."
        if str(registro["situacao"] or "").strip().lower() == "cancelado":
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
                    (treinamento_id, colaborador_id, presente, observacao, atualizado_em)
                VALUES (?, ?, 1, '', CURRENT_TIMESTAMP::text)
                ON CONFLICT(treinamento_id, colaborador_id)
                DO UPDATE SET
                    presente = 1,
                    atualizado_em = CURRENT_TIMESTAMP::text
                """,
                (treinamento_id, colaborador_id),
            )
            return True, "Presença confirmada com sucesso!"

        if atual is None:
            dia1_ok = False
            dia2_ok = False
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
                presente_dia1 = EXCLUDED.presente_dia1,
                presente_dia2 = EXCLUDED.presente_dia2,
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


def listar_treinamentos_externos_hoje():
    """Lista treinamentos não cancelados que acontecem hoje, em qualquer dos dias."""
    hoje = date.today().isoformat()
    with conectar() as conn:
        return conn.execute(
            """
            SELECT id, titulo, data, data_dia2, hora_inicio, hora_fim
            FROM treinamentos
            WHERE (
                LEFT(COALESCE(data, ''), 10) = ?
                OR LEFT(COALESCE(data_dia2, ''), 10) = ?
            )
              AND LOWER(COALESCE(situacao, '')) <> 'cancelado'
            ORDER BY hora_inicio, titulo
            """,
            (hoje, hoje),
        ).fetchall()


def registrar_presenca_externa(treinamento_id, nome, instituicao, email):
    """Registra participante externo sem inseri-lo na tabela de colaboradores."""
    hoje = date.today().isoformat()

    with conectar() as conn:
        treinamento = conn.execute(
            """
            SELECT id, data, data_dia2, situacao
            FROM treinamentos
            WHERE id = ?
            """,
            (treinamento_id,),
        ).fetchone()

        if treinamento is None:
            return False, "Treinamento não encontrado."

        dia = dia_do_treinamento(
            treinamento["data"], treinamento["data_dia2"], hoje
        )
        if dia == 0:
            return False, "Treinamento não disponível para confirmação nesta data."
        if str(treinamento["situacao"] or "").strip().lower() == "cancelado":
            return False, "Este treinamento foi cancelado."

        pessoa = conn.execute(
            """
            SELECT id
            FROM participantes_externos
            WHERE LOWER(TRIM(nome)) = LOWER(TRIM(?))
              AND LOWER(TRIM(COALESCE(instituicao, ''))) = LOWER(TRIM(?))
              AND LOWER(TRIM(COALESCE(email, ''))) = LOWER(TRIM(?))
            LIMIT 1
            """,
            (nome, instituicao, email),
        ).fetchone()

        if pessoa is None:
            pessoa = conn.execute(
                """
                INSERT INTO participantes_externos (nome, instituicao, email)
                VALUES (?, ?, ?)
                RETURNING id
                """,
                (nome, instituicao or None, email or None),
            ).fetchone()

        participante_id = pessoa["id"]
        existente = conn.execute(
            """
            SELECT presente
            FROM presencas_externas
            WHERE treinamento_id = ? AND participante_externo_id = ?
            """,
            (treinamento_id, participante_id),
        ).fetchone()

        if existente is not None and existente["presente"] == 1:
            return False, "A presença deste participante já foi registrada neste treinamento."

        conn.execute(
            """
            INSERT INTO presencas_externas
                (treinamento_id, participante_externo_id, presente, atualizado_em)
            VALUES (?, ?, 1, CURRENT_TIMESTAMP::text)
            ON CONFLICT(treinamento_id, participante_externo_id)
            DO UPDATE SET
                presente = 1,
                atualizado_em = CURRENT_TIMESTAMP::text
            """,
            (treinamento_id, participante_id),
        )

    return True, "Presença do participante externo registrada com sucesso!"


# -----------------------------------------------------------------------------
# Interface
# -----------------------------------------------------------------------------
st.title("✅ Confirmação de presença")
st.caption("Sistema de Assiduidade | Educação Continuada")
st.write("Selecione seu tipo de cadastro para registrar a presença no treinamento de hoje.")

aba_interno, aba_externo = st.tabs(["Colaborador interno", "Participante externo"])

with aba_interno:
    st.write("Informe sua matrícula para consultar os treinamentos em que está inscrito.")

    if "colaborador_confirmacao" not in st.session_state:
        st.session_state["colaborador_confirmacao"] = None
    if "matricula_confirmacao" not in st.session_state:
        st.session_state["matricula_confirmacao"] = ""
    if "mensagem_presenca" in st.session_state:
        st.success(st.session_state.pop("mensagem_presenca"))

    with st.form("form_identificacao_interno"):
        matricula_digitada = st.text_input(
            "Número de matrícula",
            value=st.session_state["matricula_confirmacao"],
            placeholder="Digite sua matrícula",
            help="Digite a matrícula exatamente como consta no cadastro.",
        ).strip()
        consultar_treinamentos = st.form_submit_button(
            "Consultar treinamentos", use_container_width=True
        )

    if consultar_treinamentos:
        if not matricula_digitada:
            st.error("Informe sua matrícula.")
            st.session_state["colaborador_confirmacao"] = None
            st.session_state["matricula_confirmacao"] = ""
        else:
            try:
                colaborador_encontrado = buscar_colaborador_por_matricula(
                    matricula_digitada
                )
                if colaborador_encontrado is None:
                    st.session_state["colaborador_confirmacao"] = None
                    st.session_state["matricula_confirmacao"] = matricula_digitada
                    st.error(
                        "Matrícula não encontrada ou colaborador inativo. "
                        "Confira os dados ou procure o responsável pelo sistema."
                    )
                else:
                    st.session_state["colaborador_confirmacao"] = {
                        "id": int(colaborador_encontrado["id"]),
                        "nome": colaborador_encontrado["nome"],
                        "matricula": colaborador_encontrado["matricula"]
                        or matricula_digitada,
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
                    "Não há treinamentos elegíveis para sua matrícula com "
                    "confirmação disponível hoje."
                )
            else:
                st.write("**Treinamentos disponíveis hoje**")
                for treinamento in treinamentos:
                    with st.container(border=True):
                        st.markdown(f"**{treinamento['titulo']}**")
                        st.caption(
                            f"Horário: {treinamento['hora_inicio']}–{treinamento['hora_fim']}"
                        )

                        if treinamento["dois_dias"]:
                            st.caption(
                                "Treinamento em dois dias "
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

                            clicou = st.button(
                                "Confirmar minha presença",
                                key=(
                                    f"confirmar_{treinamento['id']}_"
                                    f"{colaborador['id']}_{treinamento['dia_hoje']}"
                                ),
                                use_container_width=True,
                            )
                            if clicou:
                                try:
                                    sucesso, mensagem = confirmar_presenca(
                                        int(treinamento["id"]), int(colaborador["id"])
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

with aba_externo:
    st.write(
        "Preencha seus dados para registrar a presença. Este cadastro não será "
        "incluído entre os colaboradores internos."
    )

    try:
        treinamentos_externos = listar_treinamentos_externos_hoje()
        if not treinamentos_externos:
            st.info("Não há treinamentos disponíveis para participantes externos hoje.")
        else:
            mapa_treinamentos = {}
            for treinamento in treinamentos_externos:
                dias = str(treinamento["data"])[:10]
                if treinamento["data_dia2"]:
                    dias += f" e {str(treinamento['data_dia2'])[:10]}"
                rotulo = (
                    f"{treinamento['titulo']} | {treinamento['hora_inicio']}–"
                    f"{treinamento['hora_fim']} | {dias}"
                )
                mapa_treinamentos[rotulo] = int(treinamento["id"])

            with st.form("form_participante_externo"):
                nome_externo = st.text_input("Nome completo *").strip()
                instituicao = st.text_input("Instituição/empresa").strip()
                email_externo = st.text_input("E-mail (opcional)").strip().lower()
                treinamento_escolhido = st.selectbox(
                    "Treinamento de hoje", list(mapa_treinamentos.keys())
                )
                enviar_externo = st.form_submit_button(
                    "Registrar minha presença", use_container_width=True
                )

            if enviar_externo:
                if not nome_externo:
                    st.error("Informe seu nome completo.")
                elif email_externo and (
                    "@" not in email_externo or len(email_externo) > 254
                ):
                    st.error("Informe um e-mail válido ou deixe o campo em branco.")
                else:
                    try:
                        sucesso, mensagem = registrar_presenca_externa(
                            mapa_treinamentos[treinamento_escolhido],
                            nome_externo,
                            instituicao,
                            email_externo,
                        )
                        if sucesso:
                            st.success(mensagem)
                        else:
                            st.warning(mensagem)
                    except (psycopg2.Error, RuntimeError) as erro:
                        st.error(
                            "Não foi possível registrar a presença. Verifique se "
                            f"a atualização do banco foi aplicada. Detalhes: {erro}"
                        )
    except (psycopg2.Error, RuntimeError) as erro:
        st.error(
            "Não foi possível carregar os treinamentos externos. "
            f"Verifique a conexão com o banco. Detalhes: {erro}"
        )

st.divider()
st.caption(
    "A confirmação de colaborador interno continua vinculada à matrícula e à "
    "elegibilidade. Participantes externos são armazenados separadamente."
)
