import { useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  BookOpenCheck,
  CalendarDays,
  CheckCircle2,
  ClipboardCheck,
  Clock3,
  GraduationCap,
  LayoutDashboard,
  Users,
  UserRound,
  TrendingUp,
} from "lucide-react";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8080";

const navigation = [
  { label: "Visão geral", icon: LayoutDashboard },
  { label: "Colaboradores", icon: Users },
  { label: "Treinamentos", icon: GraduationCap },
  { label: "Presenças", icon: ClipboardCheck },
  { label: "Relatórios", icon: BookOpenCheck },
];

// DADOS DEMONSTRATIVOS — substituir pelos dados da API futuramente.
const indicadores = [
  {
    titulo: "Colaboradores ativos",
    valor: "128",
    detalhe: "Enfermeiros e técnicos",
    icon: Users,
    cor: "blue",
  },
  {
    titulo: "Treinamentos realizados",
    valor: "18",
    detalhe: "No período selecionado",
    icon: GraduationCap,
    cor: "purple",
  },
  {
    titulo: "Participações registradas",
    valor: "246",
    detalhe: "Presenças confirmadas",
    icon: ClipboardCheck,
    cor: "green",
  },
  {
    titulo: "Taxa de assiduidade",
    valor: "78,5%",
    detalhe: "Média demonstrativa",
    icon: TrendingUp,
    cor: "orange",
  },
];

const evolucao = [
  { mes: "Jun", valor: 62 },
  { mes: "Jul", valor: 70 },
  { mes: "Ago", valor: 66 },
  { mes: "Set", valor: 74 },
  { mes: "Out", valor: 72 },
  { mes: "Nov", valor: 78.5 },
];

const proximosTreinamentos = [
  {
    titulo: "Segurança do paciente",
    data: "20/11/2026",
    horario: "14:00",
    publico: "Enfermeiros e técnicos",
  },
  {
    titulo: "Prevenção de infecções",
    data: "25/11/2026",
    horario: "09:00",
    publico: "Enfermeiros e técnicos",
  },
  {
    titulo: "Cuidados com dispositivos",
    data: "02/12/2026",
    horario: "14:00",
    publico: "Enfermeiros e técnicos",
  },
];

const monitoramento = [
  { nome: "Colaborador demonstrativo 01", cargo: "Enfermeiro", taxa: 18 },
  {
    nome: "Colaborador demonstrativo 02",
    cargo: "Técnico de enfermagem",
    taxa: 25,
  },
  {
    nome: "Colaborador demonstrativo 03",
    cargo: "Técnico de enfermagem",
    taxa: 30,
  },
];

export default function App() {
  const [activePage, setActivePage] = useState("Visão geral");
  const [apiStatus, setApiStatus] = useState("verificando");

  useEffect(() => {
    let mounted = true;

    fetch(`${API_URL}/api/health`)
      .then((response) => {
        if (!response.ok) throw new Error("API indisponível");
        return response.json();
      })
      .then(() => {
        if (mounted) setApiStatus("conectada");
      })
      .catch(() => {
        if (mounted) setApiStatus("indisponível");
      });

    return () => {
      mounted = false;
    };
  }, []);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <Activity size={22} />
          </div>
          <div>
            <strong>Assiduidade</strong>
            <span>Educação Continuada</span>
          </div>
        </div>

        <div className="nav-caption">MENU PRINCIPAL</div>

        <nav className="main-nav" aria-label="Navegação principal">
          {navigation.map(({ label, icon: Icon }) => (
            <button
              className={`nav-item ${activePage === label ? "active" : ""}`}
              key={label}
              onClick={() => setActivePage(label)}
            >
              <Icon size={18} strokeWidth={1.9} />
              <span>{label}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <span className={`status-dot ${apiStatus}`} />
          <span>
            API{" "}
            {apiStatus === "conectada"
              ? "conectada"
              : apiStatus === "verificando"
                ? "verificando"
                : "indisponível"}
          </span>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div>
            <span className="eyebrow">SISTEMA DE ASSIDUIDADE</span>
            <h1>{activePage}</h1>
            <p className="topbar-subtitle">
              Educação Continuada · Acompanhamento de treinamentos
            </p>
          </div>

          <div className="topbar-tag">
            <span className="status-dot conectada" />
            Ambiente de desenvolvimento
          </div>
        </header>

        {activePage === "Visão geral" ? (
          <div className="dashboard-content">
            <div className="dashboard-heading">
              <div>
                <h2>Painel de acompanhamento</h2>
                <p>Resumo das atividades de Educação Continuada.</p>
              </div>
              <span className="demo-label">
                <AlertTriangle size={14} />
                Dados demonstrativos
              </span>
            </div>

            <section className="metrics-grid">
              {indicadores.map(
                ({ titulo, valor, detalhe, icon: Icon, cor }) => (
                  <article className="metric-card" key={titulo}>
                    <div className={`metric-icon ${cor}`}>
                      <Icon size={21} />
                    </div>
                    <div className="metric-info">
                      <span>{titulo}</span>
                      <strong>{valor}</strong>
                      <small>{detalhe}</small>
                    </div>
                  </article>
                ),
              )}
            </section>

            <section className="dashboard-grid">
              <article className="panel chart-panel">
                <div className="panel-heading">
                  <div>
                    <h3>Evolução da assiduidade</h3>
                    <p>Percentual de presença por mês</p>
                  </div>
                  <span className="panel-period">Últimos 6 meses</span>
                </div>

                <div className="chart-area">
                  <div className="chart-y-axis">
                    <span>100%</span>
                    <span>75%</span>
                    <span>50%</span>
                    <span>25%</span>
                    <span>0%</span>
                  </div>

                  <div className="chart-content">
                    <div className="chart-grid-lines">
                      <span />
                      <span />
                      <span />
                      <span />
                      <span />
                    </div>

                    <div className="chart-bars">
                      {evolucao.map((item) => (
                        <div className="chart-column" key={item.mes}>
                          <div className="chart-bar-wrapper">
                            <div
                              className="chart-bar"
                              style={{ height: `${item.valor}%` }}
                              title={`${item.valor}%`}
                            />
                          </div>
                          <span>{item.mes}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="chart-legend">
                  <span className="legend-dot" />
                  Taxa de assiduidade
                </div>
              </article>

              <article className="panel trainings-panel">
                <div className="panel-heading">
                  <div>
                    <h3>Próximos treinamentos</h3>
                    <p>Programação prevista</p>
                  </div>
                  <CalendarDays size={19} />
                </div>

                <div className="training-list">
                  {proximosTreinamentos.map((treinamento) => (
                    <div className="training-item" key={treinamento.titulo}>
                      <div className="training-date">
                        <strong>{treinamento.data.slice(0, 2)}</strong>
                        <span>
                          {treinamento.data.slice(3, 5) === "11"
                            ? "NOV"
                            : "DEZ"}
                        </span>
                      </div>

                      <div className="training-info">
                        <strong>{treinamento.titulo}</strong>
                        <span>{treinamento.publico}</span>
                        <small>
                          <Clock3 size={12} />
                          {treinamento.horario}
                        </small>
                      </div>
                    </div>
                  ))}
                </div>
              </article>
            </section>

            <section className="panel monitoring-panel">
              <div className="panel-heading">
                <div>
                  <h3>Monitoramento de assiduidade</h3>
                  <p>
                    Colaboradores com taxa de presença igual ou inferior a 30%
                  </p>
                </div>
                <span className="monitoring-count">
                  {monitoramento.length} registros
                </span>
              </div>

              <div className="monitoring-table-wrapper">
                <table className="monitoring-table">
                  <thead>
                    <tr>
                      <th>Colaborador</th>
                      <th>Cargo</th>
                      <th>Taxa de presença</th>
                      <th>Situação</th>
                    </tr>
                  </thead>
                  <tbody>
                    {monitoramento.map((colaborador) => (
                      <tr key={colaborador.nome}>
                        <td>
                          <div className="collaborator-name">
                            <div className="collaborator-avatar">
                              <UserRound size={16} />
                            </div>
                            {colaborador.nome}
                          </div>
                        </td>
                        <td>{colaborador.cargo}</td>
                        <td>
                          <div className="attendance-cell">
                            <strong>{colaborador.taxa}%</strong>
                            <div className="attendance-track">
                              <span style={{ width: `${colaborador.taxa}%` }} />
                            </div>
                          </div>
                        </td>
                        <td>
                          <span className="status-warning">
                            <AlertTriangle size={13} />
                            Atenção
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="monitoring-note">
                <CheckCircle2 size={15} />
                <span>
                  Dados ilustrativos. A regra de monitoramento considera taxas
                  iguais ou inferiores a 30%.
                </span>
              </div>
            </section>

            <footer className="page-footer">
              <span>Sistema de Assiduidade</span>
              <span>Nova versão · Em desenvolvimento</span>
            </footer>
          </div>
        ) : (
          <section className="module-placeholder">
            <div className="placeholder-icon">
              <BookOpenCheck size={24} />
            </div>
            <h2>{activePage}</h2>
            <p>
              Estrutura reservada. A funcionalidade será implementada na próxima
              etapa.
            </p>
          </section>
        )}
      </main>
    </div>
  );
}
