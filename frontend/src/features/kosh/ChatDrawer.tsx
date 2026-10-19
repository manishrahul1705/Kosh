import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { MessageSquare, Send, X, ExternalLink, ShieldAlert } from 'lucide-react'
import { useSeller } from '@/app/SellerContext'
import { koshApi } from '@/lib/api/kosh'
import { Button } from '@/components/ui/Button'

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
  const [history, setHistory] = useState<{id:number;question:string;answer:{facts:{id:string;text:string;href:string}[]}}[]>([])

  useEffect(() => {
    let active = true
    setHistory([])
    if (open && activeSellerId !== null) {
      koshApi.chatHistory(activeSellerId).then(data => { if (active) setHistory(data.items) })
        .catch(() => { if (active) setError('Unable to load conversation history.') })
    }
    return () => { active = false }
  }, [activeSellerId, open])

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
        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-gradient-to-r from-primary-600 to-primary-500 hover:from-primary-700 hover:to-primary-600 text-white shadow-xs transition-all"
      >
        <MessageSquare size={13} />
        Cash chat
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Read-only cash chat"
          className="fixed right-4 top-20 z-50 w-96 max-w-[calc(100vw-2rem)] rounded-2xl border border-metal-200/90 dark:border-metal-800 bg-white dark:bg-metal-900 p-5 shadow-metal-lg space-y-4 animate-in fade-in slide-in-from-top-2 duration-150"
        >
          {/* Header */}
          <div className="flex items-start justify-between border-b border-metal-100 dark:border-metal-800 pb-3">
            <div>
              <h2 className="text-sm font-bold text-metal-900 dark:text-white tracking-tight flex items-center gap-2">
                <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
                Read-only cash chat
              </h2>
              <p className="text-xs text-metal-500 mt-1 ml-3.5">
                Computed numbers with source links. Actions require their own approval flow.
              </p>
            </div>
            <button
              onClick={() => setOpen(false)}
              className="p-1 rounded-lg text-metal-400 hover:text-metal-600 dark:hover:text-metal-200 hover:bg-metal-100 dark:hover:bg-metal-800 transition-colors"
              aria-label="Close chat"
            >
              <X size={16} />
            </button>
          </div>

          {/* Form */}
          {history.length > 0 && <div aria-label="Conversation history" className="max-h-48 overflow-y-auto space-y-3 text-xs">
            {history.map(entry => <article key={entry.id} className="rounded-lg border border-metal-200 p-2">
              <p className="font-semibold">{entry.question}</p>
              {entry.answer.facts.slice(0,2).map(fact => <p key={fact.id}><Link to={fact.href}>{fact.text}</Link></p>)}
            </article>)}
          </div>}
          <form onSubmit={handleSubmit} className="space-y-3">
            <div>
              <label htmlFor="kosh-chat-input" className="block text-xs font-semibold text-metal-700 dark:text-metal-300 mb-1.5">
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
                  className="w-full pl-3 pr-10 py-2 rounded-xl border border-metal-200 dark:border-metal-700 text-xs focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 bg-white dark:bg-metal-800 text-metal-900 dark:text-white"
                />
                <button
                  type="submit"
                  disabled={activeSellerId === null || loading || !question.trim()}
                  className="absolute right-1.5 top-1.5 p-1.5 rounded-lg bg-primary-600 hover:bg-primary-700 text-white disabled:opacity-40 transition-colors"
                  aria-label="Send message"
                >
                  <Send size={13} />
                </button>
              </div>
            </div>
            <div className="flex justify-end">
              <Button
                type="submit"
                variant="primary"
                size="sm"
                disabled={activeSellerId === null || loading || !question.trim()}
              >
                {loading ? 'Thinking...' : 'Ask'}
              </Button>
            </div>
          </form>

          {/* Error */}
          {error && (
            <p role="alert" className="p-3 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 text-xs text-rose-700 dark:text-rose-300 font-medium">
              {error}
            </p>
          )}

          {/* Results */}
          {result && (
            <div className="space-y-3 pt-1 border-t border-metal-100 dark:border-metal-800">
              <div
                role="status"
                className={`p-3 rounded-xl text-xs font-semibold ${
                  result.status === 'REFUSED'
                    ? 'bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 text-amber-900 dark:text-amber-200'
                    : 'bg-primary-50 dark:bg-primary-950/40 border border-primary-200 dark:border-primary-800 text-primary-900 dark:text-primary-200'
                }`}
              >
                <div className="flex items-center gap-1.5 font-bold mb-0.5">
                  <ShieldAlert size={14} className={result.status === 'REFUSED' ? 'text-amber-600' : 'text-primary-600'} />
                  <span>{result.status}: {result.reason}</span>
                </div>
              </div>

              {result.facts.length > 0 && (
                <div className="space-y-1.5">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-metal-400">
                    Sourced Facts
                  </span>
                  <div className="space-y-1">
                    {result.facts.map((f) => (
                      <div
                        key={f.id}
                        className="flex items-center justify-between text-xs p-2.5 rounded-xl bg-metal-50 dark:bg-metal-800/60 border border-metal-200/70 dark:border-metal-700"
                      >
                        <span className="text-metal-700 dark:text-metal-300">{f.text}</span>
                        <Link
                          to={f.href}
                          className="inline-flex items-center gap-1 text-primary-600 dark:text-primary-400 font-semibold hover:underline shrink-0 ml-2"
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
