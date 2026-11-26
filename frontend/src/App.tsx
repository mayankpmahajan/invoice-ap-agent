import { NavLink, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import RunView from "./pages/RunView";
import MasterData from "./pages/MasterData";
import { cx } from "./components/ui";

const NAV = [
  { to: "/", label: "Voucher register" },
  { to: "/master", label: "Vendors & POs" },
];

export default function App() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-blotter-deep">
        <div className="mx-auto flex max-w-[1240px] flex-wrap items-end gap-x-10 gap-y-2 px-4 pt-5 md:px-8">
          <div className="pb-3">
            <div className="title text-xl leading-none">AP Agent</div>
            <div className="mt-1 text-xs text-muted">Reads invoices. Rules decide. Every reason on file.</div>
          </div>
          <nav className="flex gap-1">
            {NAV.map(({ to, label }) => (
              <NavLink key={to} to={to} end={to === "/"}
                className={({ isActive }) => cx(
                  "-mb-px border border-b-0 px-4 py-2 text-sm font-semibold",
                  isActive ? "border-rule bg-paper text-ink" : "border-transparent text-muted hover:text-ink")}>
                {label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-[1240px] px-4 py-7 md:px-8">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/runs/:id" element={<RunView />} />
          <Route path="/master" element={<MasterData />} />
        </Routes>
      </main>
    </div>
  );
}
