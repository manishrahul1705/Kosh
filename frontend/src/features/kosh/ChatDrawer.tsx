import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { MessageSquare, Send, X, ExternalLink, ShieldAlert } from 'lucide-react'
import { useSeller } from '@/app/SellerContext'
import { koshApi } from '@/lib/api/kosh'

export const ChatDrawer = () => {
  const { activeSellerId } = useSeller()
  const [open, setOpen] = useState(false)
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<{
    status: string
    reason: string
    facts: { id: string; text: string; href: string }[]
  } | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    setResult(null)
    setQuestion('')
  }, [activeSellerId])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!question.trim()) return
    setError('')
    setLoading(true)
    try {
      const res = await koshApi.chat(activeSellerId!, question)
      setResult(res)
    } catch {
      setError('Unable to load computed facts.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <aside aria-label="Read-only cash chat" className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-blue-600 text-white hover:bg-blue-700 shadow-2xs transition-colors"
      >
        <MessageSquare size={13} />
        Cash chat
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Read-only cash chat"
          className="fixed right-4 top-20 z-50 w-96 max-w-[calc(100vw-2rem)] rounded-2xl border border-slate-200/90 bg-white p-5 shadow-2xl space-y-4 animate-in fade-in slide-in-from-top-2 duration-150"
        >
          {/* Header */}
          <div className="flex items-start justify-between border-b border-slate-100 pb-3">
            <div>
              <h2 className="text-sm font-bold text-slate-900 tracking-tight flex items-center gap-1.5">
                <MessageSquare size={16} className="text-blue-600" />
                Read-only cash chat
              </h2>
              <p className="text-xs text-slate-500 mt-0.5">
                Computed numbers with source links. Actions require their own approval flow.
              </p>
            </div>
            <button
              onClick={() => setOpen(false)}
              className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100"
              aria-label="Close chat"
            >
              <X size={16} />
            </button>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-3">
            <div>
              <label htmlFor="kosh-chat-input" className="block text-xs font-semibold text-slate-700 mb-1">
                Question
              </label>
              <div className="relative">
                <input
                  id="kosh-chat-input"
                  aria-label="Question"
                  required
                  maxLength={2000}
                  placeholder="e.g. What is my week 6 cash buffer?"
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  className="w-full pl-3 pr-10 py-2 rounded-lg border border-slate-300 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 bg-white"
                />
                <button
                  type="submit"
                  disabled={activeSellerId === null || loading || !question.trim()}
                  className="absolute right-1.5 top-1.5 p-1 rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-40"
                  aria-label="Send message"
                >
                  <Send size={13} />
                </button>
              </div>
            </div>
            <div className="flex justify-end">
              <button
                type="submit"
                disabled={activeSellerId === null || loading || !question.trim()}
                className="btn-primary text-xs py-1.5 px-3"
              >
                {loading ? 'Thinking...' : 'Ask'}
              </button>
            </div>
          </form>

          {/* Error */}
          {error && (
            <p role="alert" className="p-2.5 rounded-lg bg-rose-50 border border-rose-200 text-xs text-rose-700">
              {error}
            </p>
          )}

          {/* Results */}
          {result && (
            <div className="space-y-3 pt-1 border-t border-slate-100">
              <div
                role="status"
                className={`p-3 rounded-lg text-xs ${
                  result.status === 'REFUSED'
                    ? 'bg-amber-50 border border-amber-200 text-amber-900'
                    : 'bg-emerald-50 border border-emerald-200 text-emerald-900'
                }`}
              >
                <div className="flex items-center gap-1.5 font-bold mb-0.5">
                  <ShieldAlert size={14} className={result.status === 'REFUSED' ? 'text-amber-600' : 'text-emerald-600'} />
                  <span>{result.status}: {result.reason}</span>
                </div>
              </div>

              {result.facts.length > 0 && (
                <div className="space-y-1.5">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                    Sourced Facts
                  </span>
                  <div className="space-y-1">
                    {result.facts.map((f) => (
                      <div
                        key={f.id}
                        className="flex items-center justify-between text-xs p-2 rounded-lg bg-slate-50 border border-slate-200/70"
                      >
                        <span className="text-slate-700">{f.text}</span>
                        <Link
                          to={f.href}
                          className="inline-flex items-center gap-1 text-blue-600 font-semibold hover:underline shrink-0 ml-2"
                        >
                          {f.id}
                          <ExternalLink size={10} />
                        </Link>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </aside>
  )
}

