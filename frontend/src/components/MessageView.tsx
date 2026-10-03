import { useEffect, useState } from 'react'
import type { AnswerEvent, ChatEvent, Course, PastQuestion, SlideRef } from '../api'
import { AnswerText } from './AnswerText'
import { SlideIcon } from './icons'
import type { SlideTarget } from './SlideViewer'

export type UserMessage = { id: string; role: 'user'; text: string; fileName?: string }
export type BotMessage = {
  id: string
  role: 'bot'
  events: ChatEvent[] // everything the server sent for this turn, in order
  streamed: string // generate-mode text so far
  status: string
  startedAt: number
  done: boolean
  error?: string
}
export type Message = UserMessage | BotMessage

type Actions = {
  send: (text: string) => void
  openSlide: (target: SlideTarget) => void
  busy: boolean
}

export function pageRange(pages: string): [number, number] {
  const [a, b] = pages.split('-').map(Number)
  return [a || 1, b || a || 1]
}

export function MessageView({ message, actions }: { message: Message; actions: Actions }) {
  if (message.role === 'user') {
    return (
      <div className="msg msg-user">
        <div className="bubble">
          {message.fileName ? <div className="bubble-file">📎 {message.fileName}</div> : null}
          {message.text ? <div className="bubble-text">{message.text}</div> : null}
        </div>
      </div>
    )
  }
  return <BotView message={message} actions={actions} />
}

function BotView({ message, actions }: { message: BotMessage; actions: Actions }) {
  const answer = message.events.find((e): e is AnswerEvent => e.type === 'answer')
  return (
    <div className="msg msg-bot">
      {message.events.map((e, i) => (
        <EventView key={i} event={e} actions={actions} />
      ))}
      {!answer && message.streamed ? (
        <section className="answer draft">
          <AnswerText text={message.streamed} />
        </section>
      ) : null}
      {!message.done ? <StatusLine text={message.status} startedAt={message.startedAt} /> : null}
      {message.error ? <div className="note note-error">{message.error}</div> : null}
    </div>
  )
}

function StatusLine({ text, startedAt }: { text: string; startedAt: number }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  const secs = Math.max(0, Math.round((now - startedAt) / 1000))
  return (
    <div className="status" role="status">
      <span className="spinner" aria-hidden />
      <span className="status-text">{text || 'Thinking...'}</span>
      <span className="status-time">{secs}s</span>
    </div>
  )
}

function EventView({ event, actions }: { event: ChatEvent; actions: Actions }) {
  switch (event.type) {
    case 'info':
      return <div className="note">{event.text}</div>
    case 'error':
      return <div className="note note-error">{event.text}</div>
    case 'file':
      return (
        <div className="note">
          Read <b>{event.name}</b> ({event.pages} page{event.pages === 1 ? '' : 's'}
          {event.ocr ? ', text recognised with OCR' : ''}).
        </div>
      )
    case 'ask_course':
      return <AskCourse text={event.text} options={event.options} actions={actions} />
    case 'exercise':
      return (
        <section className="card exercise">
          <div className="card-kicker">
            {event.course} · {event.label}
          </div>
          <p className="exercise-text">{event.text}</p>
          {event.figure_attached ? (
            <div className="card-foot">The exam page with its figure was shown to the tutor.</div>
          ) : event.has_figure ? (
            <div className="card-foot warn">This question has a figure the tutor could not see.</div>
          ) : null}
        </section>
      )
    case 'past_papers':
      return <PastPapers topic={event.topic} course={event.course} items={event.items} actions={actions} />
    case 'answer':
      return <AnswerView answer={event} actions={actions} />
    default:
      return null // status, delta and done are folded into the message state
  }
}

function AskCourse({ text, options, actions }: { text: string; options: Course[]; actions: Actions }) {
  return (
    <div className="card ask">
      <p>{text}</p>
      <div className="chip-row">
        {options.map((o) => (
          <button key={o.code} className="chip" disabled={actions.busy} onClick={() => actions.send(o.code)}>
            <b>{o.code}</b> {o.name}
          </button>
        ))}
      </div>
    </div>
  )
}

function paperRef(q: PastQuestion) {
  return `${q.course} ${q.year} S${q.sem} ${q.label}`
}

function PastPapers({ topic, course, items, actions }: { topic: string; course: string; items: PastQuestion[]; actions: Actions }) {
  if (!items.length) return <div className="note">No past-year questions found on “{topic}” in {course}.</div>
  return (
    <section className="past">
      <div>
        <div className="kicker">Past-year questions · {course}</div>
        <h3 className="past-title">{topic}</h3>
      </div>
      {items.map((q) => (
        <PastCard key={`${q.source}-${q.label}`} q={q} actions={actions} />
      ))}
    </section>
  )
}

function PastCard({ q, actions }: { q: PastQuestion; actions: Actions }) {
  const [open, setOpen] = useState(false)
  const long = q.text.length > 280
  return (
    <article className="card past-card">
      <header className="past-head">
        <span className="mono">
          {q.year} S{q.sem} · {q.label}
        </span>
        <span className="past-tags">
          {q.marks ? <span className="tag">{q.marks} marks</span> : null}
          {q.has_figure ? <span className="tag">figure</span> : null}
        </span>
      </header>
      <p className="past-text">{open || !long ? q.text : q.text.slice(0, 280) + '…'}</p>
      <div className="past-actions">
        {long ? (
          <button className="link-btn" onClick={() => setOpen(!open)}>
            {open ? 'Show less' : 'Show all'}
          </button>
        ) : (
          <span />
        )}
        <span className="chip-row">
          <button className="chip" disabled={actions.busy} onClick={() => actions.send(`Give me a hint for ${paperRef(q)}`)}>
            Hint
          </button>
          <button className="chip chip-strong" disabled={actions.busy} onClick={() => actions.send(`Solve ${paperRef(q)}`)}>
            Solve
          </button>
        </span>
      </div>
    </article>
  )
}

function AnswerView({ answer, actions }: { answer: AnswerEvent; actions: Actions }) {
  const openFile = (file: string, page: number) => {
    const ranges = answer.slides.filter((s) => s.file === file).map((s) => pageRange(s.pages))
    const [first, last] = ranges.find(([a, b]) => page >= a && page <= b) ?? [page, page]
    actions.openSlide({ course: answer.course, file, first, last, page })
  }
  const openRef = (s: SlideRef) => {
    const [first, last] = pageRange(s.pages)
    actions.openSlide({ course: s.course, file: s.file, first, last, page: first })
  }

  const hint = answer.intent === 'solve' && answer.mode === 'hint'
  const maxHints = answer.max_hints ?? 2
  const followUps: { label: string; text: string }[] = []
  if (hint) {
    if (answer.hint_level < maxHints) followUps.push({ label: 'Another hint', text: 'Another hint please' })
    followUps.push({ label: 'Full solution', text: 'Show me the full solution' })
  } else if (answer.intent === 'generate' && answer.generated) {
    for (let n = 1; n <= Math.min(answer.generated, 4); n++) {
      followUps.push({ label: `Q${n} hint`, text: `Give me a hint for question ${n}` })
      followUps.push({ label: `Q${n} solution`, text: `Solve question ${n}` })
    }
  }

  return (
    <section className="answer">
      {hint ? <div className="answer-kicker">Hint {answer.hint_level}</div> : null}
      <AnswerText text={answer.text} slides={answer.slides} onOpenSlide={openFile} />

      <footer className="sources">
        <span className={`badge badge-${answer.source}`}>From {answer.source_label}</span>
        {answer.slides.length ? (
          <div className="chip-row">
            {answer.slides.map((s) => (
              <button key={`${s.file}-${s.pages}`} className="chip chip-slide" onClick={() => openRef(s)}>
                <SlideIcon size={14} />
                {s.file.replace(/\.pdf$/i, '')} <span className="muted">p.{s.pages}</span>
              </button>
            ))}
          </div>
        ) : null}
        {answer.web_sources.length ? (
          <ul className="web-list">
            {answer.web_sources.map((w, i) => (
              <li key={i}>{w.url ? <a href={w.url} target="_blank" rel="noreferrer">{w.title || w.url}</a> : w.title}</li>
            ))}
          </ul>
        ) : null}
      </footer>

      {followUps.length ? (
        <div className="chip-row follow">
          {followUps.map((f) => (
            <button key={f.label} className="chip" disabled={actions.busy} onClick={() => actions.send(f.text)}>
              {f.label}
            </button>
          ))}
        </div>
      ) : null}
    </section>
  )
}
