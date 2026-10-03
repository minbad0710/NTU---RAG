import { useEffect, useState } from 'react'
import { slideUrl } from '../api'
import { ChevronIcon, CloseIcon } from './icons'

export type SlideTarget = { course: string; file: string; first: number; last: number; page: number }

/** Modal that shows a cited lecture slide; arrows step through the cited range and beyond. */
export function SlideViewer({ target, onClose }: { target: SlideTarget; onClose: () => void }) {
  const [page, setPage] = useState(target.page)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowRight') setPage((p) => p + 1)
      if (e.key === 'ArrowLeft') setPage((p) => Math.max(1, p - 1))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  useEffect(() => setFailed(false), [page])

  const inRange = page >= target.first && page <= target.last
  return (
    <div className="viewer-backdrop" onClick={onClose} role="presentation">
      <div className="viewer" role="dialog" aria-modal="true" aria-label="Lecture slide" onClick={(e) => e.stopPropagation()}>
        <header className="viewer-head">
          <div>
            <div className="viewer-file">{target.file.replace(/\.pdf$/i, '')}</div>
            <div className="viewer-meta">
              {target.course} · slide {page}
              {inRange ? <span className="viewer-cited">cited</span> : null}
            </div>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close slide">
            <CloseIcon />
          </button>
        </header>
        <div className="viewer-stage">
          {failed ? (
            <p className="viewer-missing">There is no slide {page} in this deck.</p>
          ) : (
            <img src={slideUrl(target.course, target.file, page)} alt={`Slide ${page} of ${target.file}`} onError={() => setFailed(true)} />
          )}
        </div>
        <footer className="viewer-foot">
          <button className="ghost-btn" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}>
            <ChevronIcon dir="left" size={16} /> Previous
          </button>
          <span className="viewer-hint">← → to move, Esc to close</span>
          <button className="ghost-btn" onClick={() => setPage((p) => p + 1)} disabled={failed}>
            Next <ChevronIcon size={16} />
          </button>
        </footer>
      </div>
    </div>
  )
}
