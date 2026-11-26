import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "../api/client";
import { Card, Empty, ErrorPanel, Skeleton, cx, money } from "../components/ui";

interface Vendor { vendor_id: string; name: string; tax_id: string; country: string; currency: string; bank_name: string; bank_account: string; status: string }
interface Po { po_number: string; vendor_id: string; currency: string; status: string; description: string; issue_date: string; total: number; invoiced: number;
  lines: { line_no: number; sku: string | null; description: string; quantity: number; unit_price: number }[] }

export default function MasterData() {
  const q = useQuery({ queryKey: ["master"], queryFn: () => unwrap(api.GET("/api/master")) });
  if (q.isLoading) return <div className="mx-auto max-w-6xl space-y-4"><Skeleton className="h-40" /><Skeleton className="h-80" /></div>;
  if (q.isError) return <div className="mx-auto max-w-6xl"><ErrorPanel message="Could not load procurement data." onRetry={() => q.refetch()} /></div>;
  const vendors = (q.data?.vendors ?? []) as Vendor[];
  const pos = (q.data?.purchase_orders ?? []) as Po[];
  const vname = (id: string) => vendors.find((v) => v.vendor_id === id)?.name ?? id;

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Vendors & purchase orders</h1>
        <p className="text-sm text-slate-500">The procurement records every invoice is checked against. Invoiced amounts count approved invoices only.</p>
      </div>
      <Card title="Vendor master">
        {!vendors.length ? <Empty>No vendors.</Empty> : (
          <div className="-mx-4 -my-4 overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-slate-500"><tr className="border-b border-slate-100">
                {["Vendor", "Tax ID", "Bank account on file", "Status"].map((h) => <th key={h} className="px-4 py-2 font-medium">{h}</th>)}
              </tr></thead>
              <tbody>{vendors.map((v) => (
                <tr key={v.vendor_id} className="border-b border-slate-50">
                  <td className="px-4 py-2"><div className="font-medium">{v.name}</div><div className="text-xs text-slate-400">{v.vendor_id} · {v.country} · {v.currency}</div></td>
                  <td className="px-4 py-2 font-mono text-xs">{v.tax_id}</td>
                  <td className="px-4 py-2 text-xs"><div>{v.bank_name}</div><div className="font-mono text-slate-500">{v.bank_account}</div></td>
                  <td className="px-4 py-2"><span className={cx("rounded-full px-2 py-0.5 text-xs font-medium",
                    v.status === "approved" ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700")}>{v.status}</span></td>
                </tr>))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <div className="grid gap-4 md:grid-cols-2">
        {pos.map((p) => {
          const used = Math.min(100, (p.invoiced / p.total) * 100);
          return (
            <Card key={p.po_number} title={<span className="font-mono">{p.po_number}</span>}
              action={<span className="text-xs text-slate-500">{vname(p.vendor_id)}</span>}>
              <div className="text-sm text-slate-600">{p.description}</div>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full bg-indigo-500" style={{ width: `${used}%` }} /></div>
              <div className="mt-1 flex justify-between text-xs text-slate-500"><span>Invoiced {money(p.invoiced, p.currency)}</span><span>of {money(p.total, p.currency)}</span></div>
              <ul className="mt-3 space-y-1 text-xs">
                {p.lines.map((l) => (
                  <li key={l.line_no} className="flex justify-between gap-3 text-slate-600">
                    <span className="truncate">{l.sku && <span className="mr-1 font-mono text-slate-400">{l.sku}</span>}{l.description}</span>
                    <span className="shrink-0 tabular-nums">{l.quantity} × {money(l.unit_price, p.currency)}</span>
                  </li>
                ))}
              </ul>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
