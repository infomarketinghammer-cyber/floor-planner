import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { useAuth } from '../auth/AuthContext.tsx'

/** Public home page for visitors who aren't signed in. Signed-in users get the dashboard at "/". */

const steps = [
  {
    title: 'Upload your plan',
    text: 'PDF, photo, scan, DXF or DWG. Or import a room list from Excel or CSV.',
  },
  {
    title: 'Check the rooms',
    text: 'We read room names and sizes off the plan. You confirm every one before anything is calculated.',
  },
  {
    title: 'Pick your tiles',
    text: 'Set a default tile for the project and change it room by room.',
  },
  {
    title: 'Get your list',
    text: 'Tiles, boxes, waste and cost for every room, ready to order from.',
  },
]

const features = [
  {
    title: 'Reads the plan for you',
    text: 'Room names and sizes are picked up straight from your blueprint, in feet-inches, metres or millimetres. Door tags, notes and wall dimensions are ignored.',
  },
  {
    title: 'You stay in control',
    text: 'Every room comes with a confidence level and is highlighted on the plan. Nothing reaches the calculation until you have checked it.',
  },
  {
    title: 'Counts the way tilers do',
    text: 'Tiles are laid out in a grid for each room, so cut pieces, breakage and full boxes are all included.',
  },
  {
    title: 'Shows where the waste goes',
    text: 'See how much you buy beyond the room area and why: cuts, breakage buffer and box rounding, room by room.',
  },
]

const YEAR = new Date().getFullYear()

const formats = ['PDF', 'JPG', 'PNG', 'DXF', 'DWG', 'Excel', 'CSV']

export function LandingPage() {
  return (
    <div className="min-h-screen bg-white text-slate-900">
      <header className="border-b border-slate-100">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-4">
          <Link to="/" className="flex items-center gap-2 text-lg font-bold">
            <LogoMark />
            <span className="text-brand-gradient">Floor Planner</span>
          </Link>
          <nav className="flex items-center gap-2 text-sm sm:gap-4">
            <a href="#how-it-works" className="hidden text-slate-600 hover:text-slate-900 sm:inline">
              How it works
            </a>
            <Link to="/login" className="rounded-md px-3 py-2 font-medium text-slate-700 hover:bg-slate-100">
              Sign in
            </Link>
            <Link
              to="/register"
              className="whitespace-nowrap rounded-md bg-brand-gradient px-3 py-2 font-medium text-white hover:brightness-110 sm:px-4"
            >
              Get started
            </Link>
          </nav>
        </div>
      </header>

      <main>
        {/* Hero */}
        <section className="bg-gradient-to-b from-brand-50 to-white">
          <div aria-hidden="true" className="h-1 bg-brand-gradient" />
          <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 py-16 md:grid-cols-2 md:py-24">
            <div>
              <p className="mb-3 text-sm font-semibold uppercase tracking-wide text-brand-700">
                Tile estimates for contractors
              </p>
              <h1 className="text-4xl font-bold leading-tight tracking-tight sm:text-5xl">
                From floor plan to tile order in minutes
              </h1>
              <p className="mt-5 max-w-xl text-lg text-slate-600">
                Upload a blueprint and get the tiles, boxes and waste for every room. No measuring, no spreadsheets,
                no guesswork.
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <Link
                  to="/register"
                  className="rounded-md bg-brand-gradient px-5 py-3 font-medium text-white shadow-sm hover:brightness-110"
                >
                  Create a free account
                </Link>
                <a
                  href="#how-it-works"
                  className="rounded-md border border-slate-300 bg-white px-5 py-3 font-medium text-slate-700 hover:bg-slate-50"
                >
                  See how it works
                </a>
              </div>
              <p className="mt-4 text-sm text-slate-500">
                Already have an account?{' '}
                <Link to="/login" className="font-medium text-brand-700 hover:underline">
                  Sign in
                </Link>
                {' · '}
                <TryWithoutAccount />
              </p>
            </div>
            <HeroIllustration />
          </div>
        </section>

        {/* How it works */}
        <section id="how-it-works" className="scroll-mt-8 py-16 md:py-24">
          <div className="mx-auto max-w-6xl px-4">
            <h2 className="text-center text-3xl font-bold tracking-tight">How it works</h2>
            <p className="mx-auto mt-3 max-w-2xl text-center text-slate-600">
              Four steps from a drawing to a shopping list you can trust.
            </p>
            <ol className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
              {steps.map((step, i) => (
                <li key={step.title} className="rounded-xl border border-slate-200 p-6">
                  <span className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-gradient font-semibold text-white">
                    {i + 1}
                  </span>
                  <h3 className="mt-4 font-semibold">{step.title}</h3>
                  <p className="mt-2 text-sm text-slate-600">{step.text}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* Features */}
        <section className="bg-slate-50 py-16 md:py-24">
          <div className="mx-auto max-w-6xl px-4">
            <h2 className="text-3xl font-bold tracking-tight">Built for accurate estimates</h2>
            <div className="mt-10 grid gap-6 md:grid-cols-2">
              {features.map((f) => (
                <div key={f.title} className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
                  <h3 className="font-semibold">{f.title}</h3>
                  <p className="mt-2 text-slate-600">{f.text}</p>
                </div>
              ))}
            </div>
            <div className="mt-10 flex flex-wrap items-center gap-2 text-sm">
              <span className="mr-1 text-slate-500">Works with</span>
              {formats.map((f) => (
                <span key={f} className="rounded-full bg-white px-3 py-1 font-medium text-slate-700 ring-1 ring-slate-200">
                  {f}
                </span>
              ))}
            </div>
          </div>
        </section>

        {/* Call to action */}
        <section className="py-16 md:py-24">
          <div className="mx-auto max-w-4xl px-4">
            <div className="rounded-2xl bg-brand-gradient px-6 py-12 text-center text-white sm:px-12">
              <h2 className="text-3xl font-bold tracking-tight">Estimate your next project today</h2>
              <p className="mx-auto mt-3 max-w-xl text-white/85">
                Create an account and upload your first plan. It takes less than a minute to start.
              </p>
              <Link
                to="/register"
                className="mt-8 inline-block rounded-md bg-white px-6 py-3 font-medium text-brand-700 hover:bg-brand-50"
              >
                Get started
              </Link>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-slate-100">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-8 text-sm text-slate-500 sm:flex-row sm:justify-between">
          <span>© {YEAR} Floor Planner</span>
          <span>Estimates are a guide. Always verify quantities before ordering.</span>
          <Link to="/privacy" className="hover:underline">
            Your plans and data
          </Link>
        </div>
      </footer>
    </div>
  )
}

function LogoMark() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="h-7 w-7">
      <defs>
        <linearGradient id="fp-logo-gradient" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#023b77" />
          <stop offset="1" stopColor="#039583" />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="20" height="20" rx="4" fill="url(#fp-logo-gradient)" />
      <path d="M7 7h4v4H7zM13 7h4v4h-4zM7 13h4v4H7zM13 13h4v4h-4z" fill="white" />
    </svg>
  )
}

/** A plan with labelled rooms and the estimate for one of them (real engine numbers). */
function HeroIllustration() {
  return (
    <div className="relative mx-auto w-full max-w-md md:max-w-none">
      <svg
        viewBox="0 0 400 300"
        role="img"
        aria-label="A floor plan with four labelled rooms"
        className="w-full rounded-2xl bg-white shadow-xl ring-1 ring-slate-200"
      >
        <g fill="none" stroke="#0f172a" strokeWidth="4">
          <rect x="30" y="30" width="340" height="240" />
          <line x1="190" y1="30" x2="190" y2="160" />
          <line x1="30" y1="160" x2="370" y2="160" />
          <line x1="260" y1="160" x2="260" y2="270" />
        </g>
        {/* Highlighted room with tile grid */}
        <rect x="32" y="32" width="156" height="126" fill="#e3f3f1" />
        <g stroke="#7cc6bd" strokeWidth="1">
          {[58, 84, 110, 136, 162].map((x) => (
            <line key={`v${x}`} x1={x} y1="32" x2={x} y2="158" />
          ))}
          {[58, 84, 110, 136].map((y) => (
            <line key={`h${y}`} x1="32" y1={y} x2="188" y2={y} />
          ))}
        </g>
        <g fontFamily="ui-sans-serif, system-ui" textAnchor="middle" fill="#0f172a">
          <text x="110" y="90" fontSize="13" fontWeight="700">BEDROOM 1</text>
          <text x="110" y="107" fontSize="11">11'0" x 9'6"</text>
          <text x="280" y="90" fontSize="13" fontWeight="700">LIVING</text>
          <text x="280" y="107" fontSize="11">15'0" x 12'0"</text>
          <text x="145" y="215" fontSize="13" fontWeight="700">KITCHEN</text>
          <text x="145" y="232" fontSize="11">10'0" x 8'0"</text>
          <text x="315" y="215" fontSize="13" fontWeight="700">TOILET</text>
          <text x="315" y="232" fontSize="11">7'0" x 5'0"</text>
        </g>
      </svg>

      <div className="absolute -bottom-8 right-2 w-60 rounded-xl bg-white p-4 text-sm shadow-lg ring-1 ring-slate-200 sm:-right-4">
        <div className="flex items-center justify-between">
          <span className="font-semibold">Bedroom 1</span>
          <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800">Confirmed</span>
        </div>
        <p className="text-xs text-slate-500">2×2 ft tiles · 4 per box · 5% breakage</p>
        <dl className="mt-3 grid grid-cols-2 gap-y-1">
          <dt className="text-slate-500">Room area</dt>
          <dd className="text-right tabular-nums">104.5 sq ft</dd>
          <dt className="text-slate-500">Tiles in grid</dt>
          <dd className="text-right tabular-nums">30</dd>
          <dt className="text-slate-500">Cut waste</dt>
          <dd className="text-right tabular-nums">15.5 sq ft</dd>
          <dt className="font-medium">Boxes to buy</dt>
          <dd className="text-right font-semibold tabular-nums">8</dd>
        </dl>
      </div>
    </div>
  )
}

/** Start in guest mode: projects kept in this browser, no account (PRD 4.12). */
function TryWithoutAccount() {
  const { startGuest } = useAuth()
  const navigate = useNavigate()
  const [error, setError] = useState('')
  return (
    <>
      <button
        type="button"
        onClick={async () => {
          try {
            await startGuest()
            navigate('/', { replace: true })
          } catch {
            setError("This browser can't store projects (a private window?). Create an account instead.")
          }
        }}
        className="font-medium text-brand-700 hover:underline"
      >
        Try it without an account
      </button>
      {error && <span className="block text-red-700">{error}</span>}
    </>
  )
}
