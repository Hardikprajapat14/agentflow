import { Bot, FileText, LayoutDashboard, LogOut, PlusCircle } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";

const links = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/new", label: "New Workflow", icon: PlusCircle },
  { to: "/documents", label: "Documents", icon: FileText },
];

export default function AppLayout() {
  const { user, signOut } = useAuth();
  return (
    <div className="min-h-screen md:flex">
      <aside className="flex shrink-0 flex-col border-b border-slate-200 bg-white md:min-h-screen md:w-60 md:border-b-0 md:border-r">
        <div className="flex items-center gap-2 px-5 py-4 text-lg font-bold text-indigo-700"><Bot className="h-6 w-6" /> AgentFlow</div>
        <nav className="flex gap-1 overflow-x-auto px-3 pb-2 md:flex-col md:pb-0">
          {links.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end}
              className={({ isActive }) => `flex items-center gap-2 whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium ${isActive ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-slate-100"}`}>
              <Icon className="h-4 w-4" /> {label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto hidden border-t border-slate-200 p-4 md:block">
          <div className="truncate text-sm font-medium">{user?.name}</div>
          <div className="truncate text-xs text-slate-500">{user?.email}</div>
          <button onClick={signOut} className="mt-3 flex items-center gap-2 text-sm text-slate-600 hover:text-rose-600"><LogOut className="h-4 w-4" /> Log out</button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 p-4 md:p-8"><Outlet /></main>
    </div>
  );
}
