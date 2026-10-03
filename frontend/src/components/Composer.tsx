import { useEffect, useRef, useState } from 'react'
import { CloseIcon, PaperclipIcon, SendIcon } from './icons'

const ACCEPT = 'image/png,image/jpeg,image/webp,image/gif,.pdf'
const MAX_BYTES = 20 * 1024 * 1024

function acceptable(file: File) {
  return /\.(png|jpe?g|webp|gif|pdf)$/i.test(file.name) || file.type.startsWith('image/')
}

export function Composer({
  busy,
  onSend,
  pickRequest,
}: {
  busy: boolean
  onSend: (text: string, file: File | null) => void
  pickRequest: number // bumped by the "attach a photo" example to open the file picker
}) {
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [problem, setProblem] = useState('')
  const [dragging, setDragging] = useState(false)
  const area = useRef<HTMLTextAreaElement>(null)
  const picker = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (pickRequest) picker.current?.click()
  }, [pickRequest])

  useEffect(() => {
    const el = area.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 220) + 'px'
  }, [text])

  // dropping a file anywhere on the page attaches it
  useEffect(() => {
    const over = (e: DragEvent) => {
      if (e.dataTransfer?.types.includes('Files')) {
        e.preventDefault()
        setDragging(true)
      }
    }
    const leave = (e: DragEvent) => {
      if (!e.relatedTarget) setDragging(false)
    }
    const drop = (e: DragEvent) => {
      e.preventDefault()
      setDragging(false)
      const f = e.dataTransfer?.files[0]
      if (f) attach(f)
    }
    window.addEventListener('dragover', over)
    window.addEventListener('dragleave', leave)
    window.addEventListener('drop', drop)
    return () => {
      window.removeEventListener('dragover', over)
      window.removeEventListener('dragleave', leave)
      window.removeEventListener('drop', drop)
    }
  }, [])

  function attach(f: File) {
    if (!acceptable(f)) return setProblem('Attach an image (PNG, JPG, WebP, GIF) or a PDF.')
    if (f.size > MAX_BYTES) return setProblem('That file is over 20 MB.')
    setProblem('')
    setFile(f)
    area.current?.focus()
  }

  function submit() {
    if (busy || (!text.trim() && !file)) return
    onSend(text.trim(), file)
    setText('')
    setFile(null)
    setProblem('')
  }

  return (
    <div className={`composer-wrap${dragging ? ' dragging' : ''}`}>
      {dragging ? <div className="drop-hint">Drop the image or PDF to attach it</div> : null}
      <div className="composer">
        {file ? (
          <div className="file-chip">
            <PaperclipIcon size={14} />
            <span className="file-name">{file.name}</span>
            <button className="icon-btn small" onClick={() => setFile(null)} aria-label="Remove attachment">
              <CloseIcon size={14} />
            </button>
          </div>
        ) : null}
        <div className="composer-row">
          <button className="icon-btn" onClick={() => picker.current?.click()} aria-label="Attach an image or PDF" title="Attach an image or PDF">
            <PaperclipIcon />
          </button>
          <input
            ref={picker}
            type="file"
            accept={ACCEPT}
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) attach(f)
              e.target.value = ''
            }}
          />
          <textarea
            ref={area}
            rows={1}
            value={text}
            placeholder={file ? 'Add a note, e.g. "give me a hint" (optional)' : 'Ask about the course, a past paper, or paste an exercise...'}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault()
                submit()
              }
            }}
            onPaste={(e) => {
              const f = Array.from(e.clipboardData.files)[0]
              if (f) {
                e.preventDefault()
                attach(f)
              }
            }}
            aria-label="Message"
          />
          <button className="send-btn" onClick={submit} disabled={busy || (!text.trim() && !file)} aria-label="Send">
            <SendIcon />
          </button>
        </div>
      </div>
      <div className="composer-foot">
        {problem ? <span className="problem">{problem}</span> : <span>Enter to send · Shift+Enter for a new line · paste or drop a screenshot</span>}
      </div>
    </div>
  )
}
