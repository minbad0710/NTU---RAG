type P = { size?: number }

const base = (size = 18) => ({
  width: size,
  height: size,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
})

export const PaperclipIcon = ({ size }: P) => (
  <svg {...base(size)}>
    <path d="M21 11.5l-8.6 8.6a5.5 5.5 0 0 1-7.8-7.8l8.9-8.9a3.7 3.7 0 0 1 5.2 5.2l-8.9 8.9a1.8 1.8 0 0 1-2.6-2.6l8.2-8.2" />
  </svg>
)
export const SendIcon = ({ size }: P) => (
  <svg {...base(size)}>
    <path d="M5 12h13M13 6l6 6-6 6" />
  </svg>
)
export const PlusIcon = ({ size }: P) => (
  <svg {...base(size)}>
    <path d="M12 5v14M5 12h14" />
  </svg>
)
export const CloseIcon = ({ size }: P) => (
  <svg {...base(size)}>
    <path d="M6 6l12 12M18 6L6 18" />
  </svg>
)
export const ChevronIcon = ({ size, dir = 'right' }: P & { dir?: 'left' | 'right' }) => (
  <svg {...base(size)} style={{ transform: dir === 'left' ? 'scaleX(-1)' : undefined }}>
    <path d="M9 6l6 6-6 6" />
  </svg>
)
export const SlideIcon = ({ size }: P) => (
  <svg {...base(size)}>
    <rect x="3" y="5" width="18" height="12" rx="2" />
    <path d="M12 17v3M8 20h8" />
  </svg>
)
