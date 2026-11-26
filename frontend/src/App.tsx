import { NavLink, Route, Routes } from "react-router-dom";
import { Database, LayoutDashboard, ReceiptText } from "lucide-react";
import Dashboard from "./pages/Dashboard";
import RunView from "./pages/RunView";
import MasterData from "./pages/MasterData";
import { cx } from "./components/ui";

const NAV = [
  { to: "/", label: "Invoices", icon: LayoutDashboard },
  { to: "/master", label: "Vendors & POs", icon: Database },
];

export default function App() {
  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-56 shrink-0 flex-col border-r border-slate-200 bg-white md:flex">
        <div className="flex items-center gap-2 px-5 py-5">
          <div className="grid size-8 place-items-center rounded-lg bg-slate-900 text-white">
            <ReceiptText className="size-4" />
          </div>
          <div>
            <div className="text-sm font-semibold leading-tight">AP Agent</div>
            <div className="text-xs text-slate-500">Invoice → decision</div>
          </div>
        </div>
        <nav className="flex flex-col gap-0.5 px-3">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === "/"}
              className={({ isActive }) => cx("flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium",
                isActive ? "bg-slate-100 text-slate-900" : "text-slate-600 hover:bg-slate-50")}>
              <Icon className="size-4" /> {label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="min-w-0 flex-1 px-4 py-6 md:px-8">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/runs/:id" element={<RunView />} />
          <Route path="/master" element={<MasterData />} />
        </Routes>
      </main>
    </div>
  );
}
