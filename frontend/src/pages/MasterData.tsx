import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "../api/client";
import { Empty, ErrorNote, Skeleton, cx, money } from "../components/ui";

interface Vendor { vendor_id: string; name: string; tax_id: string; country: string; currency: string; bank_name: string; bank_account: string; status: string }
interface Po { po_number: string; vendor_id: string; currency: string; status: string; description: string; issue_date: string; total: number; invoiced: number;
  lines: { line_no: number; sku: string | null; description: string; quantity: number; unit_price: number }[] }

export default function MasterData() {
  const q = useQuery({ queryKey: ["master"], queryFn: () => unwrap(api.GET("/api/master")) });
  if (q.isLoading) return <div className="space-y-5"><Skeleton className="h-48" /><Skeleton className="h-80" /></div>;
  if (q.isError) return <ErrorNote message="procurement records could not be loaded." onRetry={() => q.refetch()} />;
  const vendors = (q.data?.vendors ?? []) as Vendor[];
  const pos = (q.data?.purchase_orders ?? []) as Po[];
  const vname = (id: string) => vendors.find((v) => v.vendor_id === id)?.name ?? id;

  return (
    <div className="space-y-8">
      <section className="sheet">
        <div className="border-b border-rule px-4 py-2.5">
          <h1 className="title text-lg">Vendor file</h1>
          <p className="text-xs text-muted">Every invoice is checked against these records. A different remit-to account on an invoice is always held.</p>
        </div>
        {!vendors.length ? <div className="p-4"><Empty title="No vendors on file" /></div> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead><tr className="border-b border-rule text-left">
                {["Vendor", "Tax ID", "Remit-to account on file", "Status"].map((h) => <th key={h} className="label px-4 py-2">{h}</th>)}
              </tr></thead>
              <tbody>
                {vendors.map((v) => (
                  <tr key={v.vendor_id} className="border-b border-rule-soft even:bg-[#f4f7f4]">
                    <td className="px-4 py-2.5"><div className="font-semibold">{v.name}</div><div className="typed text-xs text-muted">{v.vendor_id} · {v.country} · {v.currency}</div></td>
                    <td className="typed px-4 py-2.5 text-xs">{v.tax_id}</td>
                    <td className="px-4 py-2.5 text-xs"><div>{v.bank_name}</div><div className="typed">{v.bank_account}</div></td>
                    <td className="px-4 py-2.5">
                      <span className={cx("text-xs font-bold uppercase tracking-wider", v.status === "approved" ? "text-stamp-ok" : "text-stamp-void")}>{v.status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <h2 className="title mb-4 text-lg">Purchase orders</h2>
        {!pos.length ? <Empty title="No purchase orders" /> : (
          <div className="grid gap-6 md:grid-cols-2">
            {pos.map((p) => {
              const used = Math.min(100, (p.invoiced / p.total) * 100);
              return (
                <article key={p.po_number} className="sheet bg-canary">
                  <div className="flex items-start justify-between gap-3 border-b border-[#d9c873] px-4 pb-2 pt-3">
                    <div className="min-w-0">
                      <div className="typed text-base text-carbon">{p.po_number}</div>
                      <div className="truncate text-sm font-semibold">{vname(p.vendor_id)}</div>
                    </div>
                    <div className="text-right text-xs text-[#5b4b12]"><div className="typed">{p.issue_date}</div><div className="uppercase tracking-wider">{p.status}</div></div>
                  </div>
                  <div className="space-y-3 px-4 py-3">
                    <p className="text-sm text-[#5b4b12]">{p.description}</p>
                    <ul className="space-y-1 text-sm">
                      {p.lines.map((l) => (
                        <li key={l.line_no} className="flex justify-between gap-3 border-b border-dotted border-[#d9c873] pb-1">
                          <span className="min-w-0 truncate">{l.description}</span>
                          <span className="typed tnum shrink-0 text-xs">{l.quantity} × {money(l.unit_price, p.currency)}</span>
                        </li>
                      ))}
                    </ul>
                    <div>
                      <div className="h-2 border border-[#c9b65c] bg-paper"><div className="h-full bg-carbon" style={{ width: `${used}%` }} /></div>
                      <div className="typed tnum mt-1 flex justify-between text-xs">
                        <span>Invoiced {money(p.invoiced, p.currency)}</span><span>of {money(p.total, p.currency)}</span>
                      </div>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
