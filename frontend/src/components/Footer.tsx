export default function Footer() {
  return (
    <footer className="mt-auto border-t border-(--line) py-6">
      <div className="wrap flex flex-col gap-2 text-xs muted sm:flex-row sm:items-center sm:justify-between">
        <p className="m-0">
          SmartTracker AI — intelligent grievance routing and resolution
          pipeline. AI assists triage; it does not replace human judgement.
        </p>
        <p className="m-0 subtle">SRS v1.0 · academic project prototype</p>
      </div>
    </footer>
  )
}
