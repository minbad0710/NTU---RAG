// Client for server.py. /api/chat streams newline-delimited JSON events while the answer is prepared.

export type Course = { code: string; name: string }
export type SlideRef = { course: string; file: string; pages: string }
export type PastQuestion = {
  course: string
  year: string
  sem: number
  label: string
  marks: number
  has_figure: boolean
  source: string
  text: string
}
export type Source = 'slides' | 'web' | 'model'

export type AnswerEvent = {
  type: 'answer'
  text: string
  streamed?: boolean
  course: string
  intent: 'qa' | 'solve' | 'generate'
  mode: 'full' | 'hint'
  hint_level: number
  source: Source
  source_label: string
  slides: SlideRef[]
  past_questions: PastQuestion[]
  web_sources: { title: string; url: string }[]
  max_hints?: number
  generated?: number
  trace?: string[]
}

export type ChatEvent =
  | { type: 'status'; text: string }
  | { type: 'info'; text: string; course: string }
  | { type: 'error'; text: string }
  | { type: 'ask_course'; text: string; options: Course[] }
  | { type: 'exercise'; course: string; label: string; text: string; figure_attached: boolean; has_figure: boolean }
  | { type: 'past_papers'; course: string; topic: string; items: PastQuestion[] }
  | { type: 'delta'; text: string } // answer text while it is written (before it is checked)
  | { type: 'draft_reset'; text: string } // the streamed text was rejected; text says why, a new attempt follows
  | { type: 'file'; name: string; pages: number; ocr: boolean; text: string }
  | AnswerEvent
  | { type: 'done' }

export async function getCourses(): Promise<Course[]> {
  const res = await fetch('/api/courses')
  if (!res.ok) throw new Error('The server is not reachable. Start it with: python -m uvicorn backend.server:app --port 8000')
  return res.json()
}

export async function resetSession(sessionId: string): Promise<void> {
  const body = new FormData()
  body.append('session_id', sessionId)
  await fetch('/api/reset', { method: 'POST', body })
}

export function slideUrl(course: string, file: string, page: number): string {
  const q = new URLSearchParams({ course, file, page: String(page) })
  return `/api/slide?${q}`
}

/** Send one message (and optionally a file); calls onEvent for every event until the answer is complete. */
export async function streamChat(
  sessionId: string,
  message: string,
  file: File | null,
  onEvent: (event: ChatEvent) => void,
): Promise<void> {
  const body = new FormData()
  body.append('session_id', sessionId)
  body.append('message', message)
  if (file) body.append('file', file)

  const res = await fetch('/api/chat', { method: 'POST', body })
  if (!res.ok || !res.body) {
    let detail = `The server answered ${res.status}.`
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* not JSON */
    }
    throw new Error(detail)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let newline: number
    while ((newline = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, newline).trim()
      buffer = buffer.slice(newline + 1)
      if (line) onEvent(JSON.parse(line) as ChatEvent)
    }
  }
}
