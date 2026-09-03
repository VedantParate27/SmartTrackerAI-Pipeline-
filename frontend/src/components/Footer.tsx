export default function Footer() {
  return (
    <footer className="mt-auto border-t border-(--line) py-6">
      <div className="wrap flex flex-col gap-2 text-xs muted sm:flex-row sm:items-center sm:justify-between">
        <p className="m-0">
          SmartTracker AI — FastAPI is the source of truth for complaint
          identity, status, routing, and approvals.
        </p>
        <p className="m-0 subtle">SRS v1.0 · academic project prototype</p>
      </div>
    </footer>
  )
}
