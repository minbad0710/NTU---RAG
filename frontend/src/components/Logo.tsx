/** The app mark: the same drawing as the favicon (public/favicon.svg). */
export function Logo({ size = 28 }: { size?: number }) {
  return <img className="logo" src="/favicon.svg" width={size} height={size} alt="" />
}
