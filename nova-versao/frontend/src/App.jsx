import { useEffect, useState } from "react";
import {
  Activity,
  BookOpenCheck,
  CalendarDays,
  ClipboardCheck,
  GraduationCap,
  LayoutDashboard,
  Users,
} from "lucide-react";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8080";

const navigation = [
  { label: "Visão geral", icon: LayoutDashboard },
  { label: "Colaboradores", icon: Users },
  { label: "Treinamentos", icon: GraduationCap },
  { label: "Presenças", icon: ClipboardCheck },
  { label: "Relatórios", icon: BookOpenCheck },
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
      .then(() => mounted && setApiStatus("conectada"))
      .catch(() => mounted && setApiStatus("indisponível"));
    return () => {
      mounted = false;
    };
  }, []);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><Activity size={22} /></div>
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
          <span>API {apiStatus === "conectada" ? "conectada" : apiStatus === "verificando" ? "verificando" : "indisponível"}</span>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div>
            <span className="eyebrow">SISTEMA DE ASSIDUIDADE</span>
            <h1>{activePage}</h1>
          </div>
          <div className="topbar-tag">Ambiente de desenvolvimento</div>
        </header>

        {activePage === "Visão geral" ? (
          <section className="welcome-panel">
            <div className="welcome-icon"><CalendarDays size={22} /></div>
            <div>
              <h2>A nova versão está começando.</h2>
              <p>
                Esta é a base visual do sistema. Os módulos e indicadores serão
                conectados gradualmente à API, preservando as regras do aplicativo atual.
              </p>
            </div>
          </section>
        ) : (
          <section className="module-placeholder">
            <div className="placeholder-icon"><BookOpenCheck size={24} /></div>
            <h2>{activePage}</h2>
            <p>Estrutura reservada. A funcionalidade será implementada na próxima etapa.</p>
          </section>
        )}

        <footer className="page-footer">
          <span>Sistema de Assiduidade</span>
          <span>Nova versão · Em desenvolvimento</span>
        </footer>
      </main>
    </div>
  );
}
