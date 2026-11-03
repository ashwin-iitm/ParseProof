import { NavLink, Outlet } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { FileStack, Layers, LayoutTemplate, Settings as SettingsIcon } from "lucide-react";
import { api } from "@/api";

const NAV = [
  { to: "/", label: "Runs", icon: FileStack, end: true },
  { to: "/batches", label: "Batches", icon: Layers },
  { to: "/templates", label: "Templates", icon: LayoutTemplate },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

export function Logo() {
  return (
    <svg viewBox="0 0 32 32" className="h-6 w-6" aria-hidden>
      <rect width="32" height="32" rx="7" fill="rgb(var(--ink))" />
      <path d="M10 6h9l5 5v15H10z" fill="none" stroke="rgb(var(--paper))" strokeWidth="2" strokeLinejoin="round" />
      <path d="M13.5 18.5l2.5 2.5 5-5.5" fill="none" stroke="rgb(var(--paper))" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function Layout() {
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings, staleTime: 60_000 });
  const keySet = settings.data?.openai_key_set;

  return (
    <div className="flex h-full max-md:flex-col">
      <aside className="flex w-[216px] shrink-0 flex-col border-r border-line bg-panel max-md:w-full max-md:flex-row max-md:items-center max-md:border-b max-md:border-r-0">
        <div className="flex h-14 items-center gap-2.5 px-5 max-md:px-4">
          <Logo />
          <span className="text-md font-semibold tracking-[-0.01em]">ParseProof</span>
        </div>
        <nav className="flex flex-col gap-0.5 px-3 pt-2 max-md:flex-1 max-md:flex-row max-md:justify-end max-md:pt-0" aria-label="Main">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                clsx(
                  "flex h-8 items-center gap-2.5 rounded px-2.5 text-sm transition-colors duration-150",
                  isActive ? "bg-ink/[0.07] font-medium text-ink" : "text-ink-2 hover:bg-ink/[0.04] hover:text-ink",
                )
              }
            >
              <Icon className="h-4 w-4 shrink-0" strokeWidth={1.75} aria-hidden />
              <span className="max-sm:hidden">{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto border-t border-line px-5 py-3.5 text-xs text-ink-3 max-md:hidden">
          <NavLink to="/settings" className="flex items-center gap-2 hover:text-ink">
            <span className={clsx("h-1.5 w-1.5 rounded-full", keySet ? "bg-pass" : keySet === false ? "bg-fail" : "bg-ink-3")} aria-hidden />
            {keySet ? "OpenAI connected" : keySet === false ? "OpenAI key missing" : "Checking…"}
          </NavLink>
        </div>
      </aside>
      <main className="min-h-0 min-w-0 flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
