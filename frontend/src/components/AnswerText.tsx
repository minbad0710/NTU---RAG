import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { SlideRef } from '../api'

// Answers cite slides as "(06_ShortestPath.pdf, slide 27)" or "(…pdf, slides 31 and 34)". Citations to decks this
// answer actually retrieved become links that open the slide viewer.
const CITATION = /(?<=\()([^()\n]+?\.pdf),\s*slides?\s*(\d+)/g

// the model sometimes drops a character from the deck name ("M-L4-..." for "M1-L4-..."): compare letters only
const letters = (s: string) => s.toLowerCase().replace(/\.pdf$/, '').replace(/[^a-z]/g, '')

function linkCitations(text: string, slides: SlideRef[]): string {
  const files = [...new Set(slides.map((s) => s.file))]
  return text.replace(CITATION, (match, file: string, page: string) => {
    const name = file.trim()
    const real = files.find((f) => f === name) ?? files.find((f) => letters(f) === letters(name))
    return real ? `[${match}](#slide/${encodeURIComponent(real)}/${page})` : match
  })
}

export function AnswerText({
  text,
  slides = [],
  onOpenSlide,
}: {
  text: string
  slides?: SlideRef[]
  onOpenSlide?: (file: string, page: number) => void
}) {
  return (
    <div className="answer-text">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href = '', children }) => {
            if (href.startsWith('#slide/') && onOpenSlide) {
              const [, file, page] = href.split('/')
              // a link rather than a button: buttons are laid out as inline blocks and can't wrap with the sentence
              return (
                <a
                  className="cite"
                  href={href}
                  role="button"
                  onClick={(e) => {
                    e.preventDefault()
                    onOpenSlide(decodeURIComponent(file), Number(page))
                  }}
                >
                  {children}
                </a>
              )
            }
            return (
              <a href={href} target="_blank" rel="noreferrer">
                {children}
              </a>
            )
          },
          table: ({ children }) => (
            <div className="table-scroll">
              <table>{children}</table>
            </div>
          ),
        }}
      >
        {linkCitations(text, slides)}
      </ReactMarkdown>
    </div>
  )
}
