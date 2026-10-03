import { useEffect, useRef, useState } from 'react'
import { getCourses, resetSession, streamChat, type ChatEvent, type Course } from './api'
import { Composer } from './components/Composer'
import { Logo } from './components/Logo'
import { MessageView, type BotMessage, type Message } from './components/MessageView'
import { Sidebar } from './components/Sidebar'
import { SlideViewer, type SlideTarget } from './components/SlideViewer'
import './App.css'

const EXAMPLES = [
  { label: 'Explain a topic', text: 'Explain how CRC error detection works' },
  { label: 'Hint for a past paper', text: 'Give me a hint for SC2008 AY2526 S2 Q1(15)' },
  { label: 'Solve a past paper', text: 'Solve SC2001 AY1617 S2 Q4(c)' },
  { label: 'Practice questions', text: 'Give me 2 practice questions on paging' },
  { label: 'Past-year questions', text: 'Past year questions on deadlock' },
  { label: 'From a photo', text: '' }, // opens the file picker
]

const newId = () => crypto.randomUUID()

export default function App() {
  const [sessionId, setSessionId] = useState(newId)
  const [courses, setCourses] = useState<Course[]>([])
  const [serverDown, setServerDown] = useState('')
  const [course, setCourse] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [busy, setBusy] = useState(false)
  const [slide, setSlide] = useState<SlideTarget | null>(null)
  const [pickRequest, setPickRequest] = useState(0)
  const [menuOpen, setMenuOpen] = useState(false)
  const scroller = useRef<HTMLDivElement>(null)
  const stick = useRef(true) // keep scrolled to the bottom unless the reader scrolled up

  useEffect(() => {
    getCourses()
      .then(setCourses)
      .catch((e: Error) => setServerDown(e.message))
  }, [])

  useEffect(() => {
    const el = scroller.current
    if (el && stick.current && messages.length) el.scrollTop = el.scrollHeight
  }, [messages])

  function updateBot(id: string, change: (m: BotMessage) => BotMessage) {
    setMessages((ms) => ms.map((m) => (m.id === id && m.role === 'bot' ? change(m) : m)))
  }

  async function send(text: string, file: File | null = null) {
    if (busy || (!text && !file)) return
    const botId = newId()
    const bot: BotMessage = { id: botId, role: 'bot', events: [], streamed: '', status: '', startedAt: Date.now(), done: false }
    setMessages((ms) => [...ms, { id: newId(), role: 'user', text, fileName: file?.name }, bot])
    setBusy(true)
    setMenuOpen(false)
    stick.current = true

    const onEvent = (e: ChatEvent) => {
      if (e.type === 'info' || e.type === 'answer' || e.type === 'past_papers' || e.type === 'exercise') {
        if (e.course) setCourse(e.course)
      }
      updateBot(botId, (m) => {
        switch (e.type) {
          case 'status':
            return { ...m, status: e.text }
          case 'delta':
            return { ...m, streamed: m.streamed + e.text }
          case 'draft_reset':
            return { ...m, streamed: '', status: e.text }
          case 'done':
            return { ...m, done: true }
          default:
            return { ...m, events: [...m.events, e] }
        }
      })
    }
    try {
      await streamChat(sessionId, text, file, onEvent)
    } catch (err) {
      updateBot(botId, (m) => ({ ...m, error: (err as Error).message || 'The request failed.' }))
    } finally {
      updateBot(botId, (m) => ({ ...m, done: true }))
      setBusy(false)
    }
  }

  function newChat() {
    resetSession(sessionId).catch(() => {})
    setSessionId(newId())
    setMessages([])
    setCourse(null)
    setMenuOpen(false)
  }

  const actions = { send: (t: string) => void send(t), openSlide: setSlide, busy }
  const courseName = courses.find((c) => c.code === course)?.name

  return (
    <div className="app">
      <header className="nav">
        <button className="menu-btn" onClick={() => setMenuOpen(true)} aria-label="Open menu">
          <span />
          <span />
          <span />
        </button>
        <button className="brand" onClick={newChat} disabled={busy} title="New chat">
          <Logo />
          <span className="brand-name">Course Tutor</span>
        </button>
        <div className="nav-right">
          {course ? (
            <span className="nav-course">
              <span className="nav-code">{course}</span>
              <span className="nav-name">{courseName}</span>
            </span>
          ) : (
            <span className="nav-course idle">No course yet</span>
          )}
          <span className="nav-chip">NTU</span>
        </div>
      </header>

      <div className="body">
        <Sidebar
          courses={courses}
          current={course}
          busy={busy}
          open={menuOpen}
          onPick={(code) => void send(`/course ${code}`)}
          onNewChat={newChat}
        />
        {menuOpen ? <div className="scrim" onClick={() => setMenuOpen(false)} /> : null}

        <main className="main">
          <div
            className="scroller"
            ref={scroller}
            onScroll={(e) => {
              const el = e.currentTarget
              stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
            }}
          >
            <div className="thread">
              {serverDown ? <div className="note note-error">{serverDown}</div> : null}
              {messages.length === 0 ? (
                <div className="empty">
                  <div className="kicker">Lecture slides &amp; past-year papers · 5 NTU courses</div>
                  <h1>What are you studying today?</h1>
                  <div className="tagline">Explain · Hint · Solve · Practise</div>
                  <p className="lede">
                    Answers come from your course's lecture slides and past-year papers, with the slides they cite. Ask
                    for a hint when you want to work it out yourself.
                  </p>
                  <div className="kicker examples-label">Try one</div>
                  <div className="examples">
                    {EXAMPLES.map((ex) => (
                      <button
                        key={ex.label}
                        className="example"
                        disabled={busy || !!serverDown}
                        onClick={() => (ex.text ? void send(ex.text) : setPickRequest((n) => n + 1))}
                      >
                        <span className="example-label">{ex.label}</span>
                        <span className="example-text">{ex.text || 'Attach a photo or PDF of a question'}</span>
                        <span className="example-go">{ex.text ? 'Ask' : 'Choose file'} →</span>
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                messages.map((m) => <MessageView key={m.id} message={m} actions={actions} />)
              )}
            </div>
          </div>

          <div className="dock">
            <Composer busy={busy} onSend={(t, f) => void send(t, f)} pickRequest={pickRequest} />
          </div>
        </main>
      </div>

      {slide ? <SlideViewer key={`${slide.file}-${slide.page}`} target={slide} onClose={() => setSlide(null)} /> : null}
    </div>
  )
}
