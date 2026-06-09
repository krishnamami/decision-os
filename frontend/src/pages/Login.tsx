// Placeholder sign-in page — auth lands in a later session.
export default function Login() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center px-6">
      <div className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-8 text-center">
        <div className="text-2xl font-bold text-emerald-600">Accord</div>
        <p className="mt-2 text-sm text-slate-500">Sign-in is coming soon.</p>
        <button className="mt-6 w-full rounded-lg bg-emerald-600 px-4 py-2 font-medium text-white hover:bg-emerald-700">
          Continue as demo user
        </button>
      </div>
    </div>
  )
}
