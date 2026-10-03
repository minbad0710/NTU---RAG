import type { Course } from '../api'
import { PlusIcon } from './icons'

const ABILITIES = [
  'Explanations from the lecture slides',
  'Past-year questions on a topic',
  'A hint or a full solution to any exercise',
  'New practice questions',
]

export function Sidebar({
  courses,
  current,
  busy,
  onPick,
  onNewChat,
  open,
}: {
  courses: Course[]
  current: string | null
  busy: boolean
  onPick: (code: string) => void
  onNewChat: () => void
  open: boolean
}) {
  return (
    <aside className={`sidebar${open ? ' open' : ''}`}>
      <button className="new-chat" onClick={onNewChat} disabled={busy}>
        <PlusIcon size={15} /> New chat
      </button>

      <nav aria-label="Courses">
        <div className="kicker">Courses</div>
        <ul className="course-list">
          {courses.map((c) => (
            <li key={c.code}>
              <button
                className={`course${c.code === current ? ' active' : ''}`}
                onClick={() => onPick(c.code)}
                disabled={busy}
                aria-current={c.code === current ? 'true' : undefined}
              >
                <span className="course-code">{c.code}</span>
                <span className="course-name">{c.name}</span>
              </button>
            </li>
          ))}
        </ul>
        <p className="side-note">Or just ask: the course is picked from your question.</p>
      </nav>

      <div className="side-help">
        <div className="kicker">You can ask for</div>
        <ol>
          {ABILITIES.map((a, i) => (
            <li key={a}>
              <span className="side-num">{String(i + 1).padStart(2, '0')}</span>
              {a}
            </li>
          ))}
        </ol>
      </div>
    </aside>
  )
}
