const INTEGRATIONS = ['Encompass', 'Fannie Mae', 'Freddie Mac', 'Experian', 'Equifax', 'IRS (4506-C)']

export default function IntegrationsStrip() {
  return (
    <section className="mx-auto max-w-[1200px] px-6 py-10 text-center">
      <div className="text-[13px] font-medium text-slate-400">Built to integrate with</div>
      <div className="mt-4 flex flex-wrap items-center justify-center gap-3">
        {INTEGRATIONS.map((name) => (
          <span key={name} className="rounded-full border border-slate-200 px-4 py-1.5 text-sm font-semibold text-slate-500">
            {name}
          </span>
        ))}
      </div>
    </section>
  )
}
