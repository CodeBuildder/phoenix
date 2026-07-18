import { useState } from 'react'
import useSWR, { useSWRConfig } from 'swr'
import { fetchScenarios, stopScenario, triggerScenario } from '../api/chaos'
import type { Scenario, ScenarioDomain, TriggerPayload } from '../types/chaos'
import { AlertCircle, FlaskConical, Loader2, Play, Square, X } from 'lucide-react'

const STATUS_COLORS: Record<string, string> = {
  running: 'text-danger',
  completed: 'text-success',
  failed: 'text-warning',
  stopped: 'text-slate-500',
  pending: 'text-accent',
}

const FAULT_PRESETS: { domain: ScenarioDomain; fault_type: string; label: string }[] = [
  { domain: 'chaos_mesh', fault_type: 'pod-failure', label: 'Pod Failure' },
  { domain: 'chaos_mesh', fault_type: 'network-delay', label: 'Network Delay' },
  { domain: 'chaos_mesh', fault_type: 'network-loss', label: 'Packet Loss' },
  { domain: 'chaos_mesh', fault_type: 'cpu-stress', label: 'CPU Stress' },
  { domain: 'chaos_mesh', fault_type: 'memory-stress', label: 'Memory Stress' },
  { domain: 'simulator', fault_type: 'http-error', label: 'HTTP Error (sim)' },
  { domain: 'simulator', fault_type: 'latency-spike', label: 'Latency Spike (sim)' },
]

function ScenarioRow({ s, onStop }: { s: Scenario; onStop: () => void }) {
  const [stopping, setStopping] = useState(false)

  async function handleStop() {
    setStopping(true)
    try { await onStop() } finally { setStopping(false) }
  }

  return (
    <tr className="border-b border-border/50 hover:bg-elevated/40 transition-colors">
      <td className="py-2.5 pr-4 font-mono text-sm text-slate-200">{s.name}</td>
      <td className="py-2.5 pr-4">
        <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-elevated text-slate-400">
          {s.domain}
        </span>
      </td>
      <td className="py-2.5 pr-4 text-sm font-mono text-slate-400">{s.fault_type}</td>
      <td className="py-2.5 pr-4 text-sm font-mono text-slate-400">
        {s.target.namespace ?? '—'}
      </td>
      <td className="py-2.5 pr-4">
        <span className={`text-xs font-mono font-semibold uppercase ${STATUS_COLORS[s.status] ?? 'text-slate-400'}`}>
          {s.status}
        </span>
      </td>
      <td className="py-2.5 text-xs text-slate-500 font-mono pr-4">
        {s.started_at ? new Date(s.started_at).toLocaleTimeString() : '—'}
      </td>
      <td className="py-2.5">
        {s.status === 'running' && (
          <button
            onClick={handleStop}
            disabled={stopping}
            className="flex items-center gap-1 px-2 py-1 rounded bg-danger/10 border border-danger/20 text-danger hover:bg-danger/20 text-xs transition-colors disabled:opacity-50"
          >
            {stopping ? <Loader2 className="w-3 h-3 animate-spin" /> : <Square className="w-3 h-3" />}
            Stop
          </button>
        )}
      </td>
    </tr>
  )
}

interface TriggerForm {
  name: string
  domain: ScenarioDomain
  fault_type: string
  namespace: string
  label_selector: string
  duration_seconds: string
}

function TriggerModal({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const [form, setForm] = useState<TriggerForm>({
    name: '',
    domain: 'chaos_mesh',
    fault_type: 'pod-failure',
    namespace: 'phoenix',
    label_selector: '',
    duration_seconds: '60',
  })
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  function applyPreset(domain: ScenarioDomain, fault_type: string) {
    setForm(f => ({ ...f, domain, fault_type }))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setErr(null)
    setSubmitting(true)
    try {
      const selectorMap: Record<string, string> = {}
      form.label_selector.split(',').forEach(pair => {
        const [k, v] = pair.trim().split('=')
        if (k && v) selectorMap[k.trim()] = v.trim()
      })
      const payload: TriggerPayload = {
        name: form.name,
        domain: form.domain,
        fault_type: form.fault_type,
        target: {
          namespace: form.namespace || undefined,
          label_selector: Object.keys(selectorMap).length > 0 ? selectorMap : undefined,
        },
        duration_seconds: form.duration_seconds ? Number(form.duration_seconds) : undefined,
      }
      await triggerScenario(payload)
      onSuccess()
      onClose()
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-card border border-border rounded-xl w-full max-w-lg shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <p className="font-semibold text-slate-200">Trigger Chaos Scenario</p>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300">
            <X className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {/* Presets */}
          <div>
            <p className="text-xs text-slate-500 mb-2 uppercase tracking-wider font-mono">Fault preset</p>
            <div className="flex flex-wrap gap-2">
              {FAULT_PRESETS.map(p => (
                <button
                  key={`${p.domain}/${p.fault_type}`}
                  type="button"
                  onClick={() => applyPreset(p.domain, p.fault_type)}
                  className={`px-2.5 py-1 rounded text-xs font-mono transition-colors border ${
                    form.domain === p.domain && form.fault_type === p.fault_type
                      ? 'bg-accent/20 border-accent text-accent'
                      : 'bg-elevated border-border text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          <Field label="Scenario name" required>
            <input
              required
              value={form.name}
              onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              placeholder="e.g. faultlib pod failure"
              className="w-full input"
            />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Namespace">
              <input
                value={form.namespace}
                onChange={e => setForm(f => ({ ...f, namespace: e.target.value }))}
                placeholder="phoenix"
                className="w-full input"
              />
            </Field>
            <Field label="Label selector">
              <input
                value={form.label_selector}
                onChange={e => setForm(f => ({ ...f, label_selector: e.target.value }))}
                placeholder="app=phoenix-faultlib"
                className="w-full input"
              />
            </Field>
          </div>

          <Field label="Duration (seconds)">
            <input
              type="number"
              min={1}
              value={form.duration_seconds}
              onChange={e => setForm(f => ({ ...f, duration_seconds: e.target.value }))}
              className="w-full input"
            />
          </Field>

          {err && (
            <div className="flex items-center gap-2 text-sm text-danger bg-danger/10 border border-danger/20 rounded-lg px-3 py-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              {err}
            </div>
          )}

          <div className="flex gap-3 pt-1">
            <button type="button" onClick={onClose} className="flex-1 btn-secondary">
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="flex-1 btn-primary flex items-center justify-center gap-2"
            >
              {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
              Trigger
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function Field({ label, children, required }: { label: string; children: React.ReactNode; required?: boolean }) {
  return (
    <div>
      <label className="block text-xs text-slate-400 mb-1 font-mono">
        {label}{required && <span className="text-danger ml-1">*</span>}
      </label>
      {children}
    </div>
  )
}

export default function ChaosLab() {
  const { mutate } = useSWRConfig()
  const [showModal, setShowModal] = useState(false)

  const { data: scenarios, error, isLoading } = useSWR('scenarios', fetchScenarios, {
    refreshInterval: 5_000,
  })

  const running = scenarios?.filter(s => s.status === 'running') ?? []

  async function handleStop(id: string) {
    await stopScenario(id)
    mutate('scenarios')
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Chaos Lab</h1>
          <p className="text-sm text-slate-500 mt-1">
            Trigger and monitor fault injection scenarios
          </p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-accent text-white text-sm font-medium hover:bg-accent/90 transition-colors"
        >
          <FlaskConical className="w-4 h-4" />
          Trigger Scenario
        </button>
      </div>

      {running.length > 0 && (
        <div className="flex items-center gap-2 text-sm text-danger bg-danger/10 border border-danger/20 rounded-lg px-4 py-3">
          <span className="w-2 h-2 rounded-full bg-danger animate-pulse shrink-0" />
          {running.length} scenario{running.length !== 1 ? 's' : ''} currently running
        </div>
      )}

      <div className="bg-card border border-border rounded-xl p-5">
        {isLoading && (
          <div className="flex items-center gap-2 text-slate-500 text-sm">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading scenarios…
          </div>
        )}
        {error && (
          <div className="flex items-center gap-2 text-sm text-danger">
            <AlertCircle className="w-4 h-4" /> Chaos service unreachable
          </div>
        )}
        {scenarios && scenarios.length === 0 && (
          <p className="text-slate-500 text-sm">No scenarios yet. Trigger one to get started.</p>
        )}
        {scenarios && scenarios.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="text-slate-500 border-b border-border">
                  <th className="text-left pb-2 pr-4">Name</th>
                  <th className="text-left pb-2 pr-4">Domain</th>
                  <th className="text-left pb-2 pr-4">Fault Type</th>
                  <th className="text-left pb-2 pr-4">Namespace</th>
                  <th className="text-left pb-2 pr-4">Status</th>
                  <th className="text-left pb-2 pr-4">Started</th>
                  <th className="text-left pb-2">Action</th>
                </tr>
              </thead>
              <tbody>
                {scenarios.map(s => (
                  <ScenarioRow key={s.id} s={s} onStop={() => handleStop(s.id)} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showModal && (
        <TriggerModal
          onClose={() => setShowModal(false)}
          onSuccess={() => mutate('scenarios')}
        />
      )}
    </div>
  )
}
