import React from 'react';
import {
  Activity,
  ArrowRight,
  Brain,
  CheckCircle2,
  Crosshair,
  Film,
  Layers3,
  PlayCircle,
  Settings,
  Upload,
} from 'lucide-react';
import { Button } from '@/components/ui/button';

const BADDY_APP_URL =
  process.env.REACT_APP_BADDY_APP_URL || '/create.html#create';
const BADDY_GALLERY_URL =
  process.env.REACT_APP_BADDY_GALLERY_URL || '/create.html#gallery';
const BADDY_STUDIO_IMAGE =
  '/assets/baddy-studio-editor-original.jpg';
const BADDY_TRACKED_RALLY_IMAGE =
  '/assets/baddy-rally-tracked-original.jpg';
const BADDY_UPLOAD_RALLY_IMAGE =
  '/assets/baddy-rally-upload-original.jpg';

function BaddyMark({ className = 'h-5 w-5' }) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      fill="none"
      viewBox="0 0 24 24"
    >
      <path
        d="M12 2 8 10l-4 9c-.4.9.5 1.8 1.4 1.4l9-4 8-4-2.5-2.5L12 2Z"
        stroke="currentColor"
        strokeLinejoin="round"
        strokeWidth="1.6"
      />
      <circle cx="6.5" cy="17.5" fill="currentColor" r="2.2" />
    </svg>
  );
}

export default function LandingPage() {
  return (
    <div className="min-h-screen overflow-x-hidden bg-zinc-950 text-zinc-300 antialiased">
      <div className="fixed inset-0 -z-10 overflow-hidden">
        <div className="absolute left-1/2 top-0 h-[800px] w-[1200px] -translate-x-1/2 rounded-full bg-lime-500/5 blur-[150px]" />
        <div className="absolute bottom-0 right-0 h-[600px] w-[600px] rounded-full bg-emerald-500/5 blur-[120px]" />
      </div>

      <nav className="fixed top-0 z-50 w-full border-b border-white/5 bg-zinc-950/80 backdrop-blur-md">
        <div className="mx-auto flex h-20 max-w-7xl items-center justify-between px-6">
          <a className="flex items-center gap-2" href="#top" aria-label="Baddy home">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-lime-300 to-lime-500 text-zinc-950 shadow-[0_0_15px_rgba(163,230,53,0.3)]">
              <BaddyMark className="h-5 w-5" />
            </div>
            <span className="text-xl font-medium tracking-tight text-white">
              BADDY<span className="text-lime-400"> AI</span>
            </span>
          </a>

          <div className="hidden items-center gap-10 md:flex">
            <a
              className="text-sm transition-colors hover:text-lime-400"
              href="#how-it-works"
            >
              How it Works
            </a>
            <a
              className="text-sm transition-colors hover:text-lime-400"
              href="#features"
            >
              AI Engine
            </a>
            <a
              className="text-sm transition-colors hover:text-lime-400"
              href={BADDY_GALLERY_URL}
            >
              Reels
            </a>
          </div>

          <div className="flex items-center gap-6">
            <a
              className="hidden text-sm transition-colors hover:text-lime-400 sm:block"
              href={BADDY_GALLERY_URL}
            >
              View Reels
            </a>
            <Button
              asChild
              className="rounded-full bg-lime-400 px-5 py-2.5 text-sm font-semibold text-zinc-950 shadow-[0_0_20px_rgba(163,230,53,0.2)] hover:bg-lime-300 hover:shadow-[0_0_30px_rgba(163,230,53,0.4)]"
            >
              <a data-testid="nav-cta-button" href={BADDY_APP_URL}>
                Generate a Reel
              </a>
            </Button>
          </div>
        </div>
      </nav>

      <main id="top">
        <section className="relative overflow-hidden pb-20 pt-32 lg:pb-32 lg:pt-48">
          <div className="relative z-10 mx-auto grid max-w-7xl grid-cols-1 items-center gap-16 px-6 lg:grid-cols-2">
            <div className="max-w-2xl">
              <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-zinc-800 bg-zinc-900 px-4 py-1.5">
                <span className="h-2 w-2 animate-pulse rounded-full bg-lime-400" />
                <span className="text-xs text-zinc-400">
                  Built for full-match recordings
                </span>
              </div>
              <h1
                className="mb-8 text-4xl font-medium leading-[1.1] tracking-tight text-white sm:text-5xl lg:text-7xl"
                data-testid="hero-title"
              >
                Raw game in.
                <br />
                <span className="bg-gradient-to-r from-lime-300 to-emerald-400 bg-clip-text text-transparent">
                  Highlights out.
                </span>
              </h1>
              <p className="mb-10 max-w-lg text-lg font-light leading-relaxed text-zinc-400 lg:text-xl">
                Drop a full badminton recording. Baddy detects the rallies,
                tracks the action, and cuts a beat-synced vertical reel that is
                ready to share.
              </p>
              <div className="flex flex-col gap-4 sm:flex-row">
                <Button
                  asChild
                  className="group rounded-full bg-lime-400 px-8 py-4 text-base font-semibold text-zinc-950 shadow-[0_0_20px_rgba(163,230,53,0.25)] hover:bg-lime-300"
                >
                  <a data-testid="hero-cta-button" href={BADDY_APP_URL}>
                    Generate a Reel
                    <ArrowRight
                      className="h-5 w-5 transition-transform group-hover:translate-x-1"
                      strokeWidth={1.5}
                    />
                  </a>
                </Button>
                <Button
                  asChild
                  className="glass-card rounded-full border border-white/10 px-8 py-4 text-base font-medium text-white hover:bg-white/5"
                  variant="outline"
                >
                  <a data-testid="hero-secondary-button" href="#how-it-works">
                    <PlayCircle className="h-5 w-5" strokeWidth={1.5} />
                    See How It Works
                  </a>
                </Button>
              </div>
            </div>

            <div
              className="relative h-[460px] w-full sm:h-[560px] lg:h-[600px]"
              data-testid="hero-editor-cards"
            >
              <div className="pattern-dots absolute left-10 top-0 h-32 w-32 opacity-50" />
              <div className="pattern-dots absolute bottom-10 right-10 h-32 w-32 opacity-50" />
              <div className="absolute inset-6 rounded-full bg-gradient-to-br from-lime-400/10 via-cyan-400/5 to-transparent blur-3xl sm:inset-10" />

              <div
                className="absolute left-0 top-4 z-10 flex h-[375px] w-[78%] flex-col overflow-hidden rounded-[1.75rem] border border-white/10 bg-[#090b0e] shadow-2xl sm:left-4 sm:top-8 sm:h-[475px] sm:w-[74%] lg:h-[505px] lg:w-[72%]"
                style={{ transform: 'rotate(-2deg)' }}
              >
                <div className="flex h-11 flex-shrink-0 items-center justify-between border-b border-white/10 bg-zinc-900/95 px-4">
                  <div className="flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full bg-red-400/80" />
                    <span className="h-2 w-2 rounded-full bg-amber-300/80" />
                    <span className="h-2 w-2 rounded-full bg-lime-400" />
                  </div>
                  <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-zinc-400">
                    Baddy Studio
                  </span>
                </div>
                <div className="min-h-0 flex-1 bg-[#080a0c] p-2">
                  <img
                    alt="Original Baddy Studio editor showing IMG_0674 with pose tracking, shuttle effects, playback controls, and a four-track timeline"
                    className="h-full w-full object-contain object-top"
                    src={BADDY_STUDIO_IMAGE}
                  />
                </div>
              </div>

              <div
                className="glass-card absolute bottom-0 right-0 z-20 w-[72%] overflow-hidden rounded-[1.5rem] border border-white/10 shadow-2xl sm:bottom-3 sm:w-[66%] lg:w-[62%]"
                style={{ transform: 'rotate(2deg)' }}
              >
                <div className="relative aspect-video overflow-hidden">
                  <img
                    alt="Original tracked rally frame with player pose and shuttle trajectory"
                    className="h-full w-full object-cover"
                    src={BADDY_TRACKED_RALLY_IMAGE}
                  />
                  <div className="absolute inset-0 bg-gradient-to-t from-zinc-950/85 via-transparent to-transparent" />
                  <div className="absolute left-3 top-3 flex items-center gap-2 rounded-full border border-lime-300/20 bg-zinc-950/75 px-3 py-1.5 backdrop-blur">
                    <span className="h-1.5 w-1.5 rounded-full bg-lime-400 shadow-[0_0_10px_rgba(163,230,53,0.85)]" />
                    <span className="text-[9px] font-semibold uppercase tracking-[0.16em] text-lime-300 sm:text-[10px]">
                      Rally 03 tracked
                    </span>
                  </div>
                </div>
                <div className="flex items-center justify-between gap-3 px-4 py-3 sm:px-5 sm:py-4">
                  <div>
                    <div className="text-xs font-medium text-white sm:text-sm">
                      Pose + shuttle locked
                    </div>
                    <div className="mt-1 text-[10px] text-zinc-500 sm:text-xs">
                      Original frame • IMG_0674.mov
                    </div>
                  </div>
                  <span className="rounded-full bg-lime-400/10 px-2.5 py-1 text-[9px] font-semibold uppercase tracking-wider text-lime-300 sm:text-[10px]">
                    Editor
                  </span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section id="features" className="relative bg-zinc-950 py-24">
          <div className="mx-auto max-w-7xl px-6">
            <div className="mx-auto mb-20 max-w-3xl text-center">
              <h2 className="mb-6 text-3xl font-medium tracking-tight text-white lg:text-5xl">
                Your Match, Cut by AI
              </h2>
              <p className="text-lg font-light leading-relaxed text-zinc-400">
                Baddy watches the full recording, detects rally windows, follows
                the players, then turns the strongest moments into one polished
                vertical reel.
              </p>
            </div>

            <div className="relative mx-auto w-full max-w-5xl">
              <div className="absolute -inset-1 rounded-[2.5rem] bg-gradient-to-b from-lime-400/25 to-transparent opacity-60 blur-lg" />
              <div
                aria-label="Baddy Studio editor interface"
                className="relative overflow-hidden rounded-[2rem] border border-zinc-800 bg-[#090b0e] shadow-2xl"
                data-testid="interface-mockup"
              >
                <div className="flex min-h-16 flex-col justify-between gap-4 border-b border-zinc-800 bg-zinc-900/90 px-5 py-4 sm:flex-row sm:items-center sm:px-6">
                  <div className="flex items-center gap-3">
                    <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-lime-300 to-cyan-300 text-zinc-950">
                      <BaddyMark className="h-5 w-5" />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-semibold tracking-[0.2em] text-white">
                          STUDIO
                        </span>
                        <span className="text-xs text-zinc-500">
                          IMG_0674.mov
                        </span>
                      </div>
                      <div className="mt-1 text-[11px] text-zinc-600">
                        badminton • original match
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="inline-flex items-center gap-2 rounded-full border border-lime-400/20 bg-lime-400/10 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-lime-300">
                      <CheckCircle2 className="h-3.5 w-3.5" strokeWidth={1.8} />
                      Analysis complete
                    </span>
                    <Settings
                      className="hidden h-4 w-4 text-zinc-500 sm:block"
                      strokeWidth={1.5}
                    />
                  </div>
                </div>

                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-800 bg-[#0c0f12] px-4 py-3 sm:px-6">
                  <div className="flex items-center gap-1 rounded-xl border border-zinc-800 bg-zinc-950 p-1">
                    <span className="rounded-lg bg-gradient-to-r from-lime-300 to-cyan-300 px-4 py-2 text-xs font-semibold text-zinc-950">
                      Reel
                    </span>
                    <span className="px-3 py-2 text-xs text-zinc-500">
                      Source rallies
                    </span>
                    <span className="hidden px-3 py-2 text-xs text-zinc-500 sm:inline">
                      Compose
                    </span>
                  </div>
                  <a
                    className="inline-flex items-center gap-2 rounded-xl bg-lime-400 px-4 py-2 text-xs font-semibold text-zinc-950 transition-colors hover:bg-lime-300"
                    href={BADDY_APP_URL}
                  >
                    Open editor
                    <ArrowRight className="h-3.5 w-3.5" strokeWidth={1.8} />
                  </a>
                </div>

                <div className="grid lg:grid-cols-[minmax(0,1fr)_240px]">
                  <div className="min-w-0 bg-[#07090b] p-3 sm:p-5">
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-[10px] text-zinc-500 sm:text-xs">
                      <span>854 × 480 • landscape • source time</span>
                      <span className="rounded-full border border-zinc-800 bg-zinc-900 px-3 py-1 text-zinc-400">
                        Landscape
                      </span>
                    </div>

                    <div className="relative aspect-video overflow-hidden rounded-xl border border-zinc-800 bg-black">
                      <img
                        alt="Original Baddy match frame in the editor with pose skeletons and a tracked shuttle trajectory"
                        className="h-full w-full object-cover"
                        src={BADDY_TRACKED_RALLY_IMAGE}
                      />
                      <div className="absolute left-3 top-3 flex items-center gap-2 rounded-full border border-black/20 bg-zinc-950/75 px-3 py-1.5 backdrop-blur">
                        <Crosshair
                          className="h-3.5 w-3.5 text-lime-300"
                          strokeWidth={1.7}
                        />
                        <span className="text-[10px] font-medium text-white">
                          Shuttle + pose
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center gap-3 border-b border-zinc-800 py-4">
                      <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-lime-300 text-zinc-950">
                        <PlayCircle className="h-4 w-4" strokeWidth={1.8} />
                      </div>
                      <span className="whitespace-nowrap text-xs text-zinc-400">
                        2:02 / 8:44
                      </span>
                      <div className="relative h-1 flex-1 rounded-full bg-zinc-700">
                        <div className="h-full w-[38%] rounded-full bg-gradient-to-r from-lime-300 to-cyan-300" />
                        <span className="absolute left-[38%] top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-zinc-950 bg-lime-300" />
                      </div>
                      <span className="rounded-md border border-zinc-800 px-2 py-1 text-[10px] text-zinc-400">
                        1×
                      </span>
                    </div>

                    <div className="pt-4">
                      <div className="mb-3 flex items-center justify-between">
                        <div>
                          <span className="text-xs font-medium text-white">
                            Timeline
                          </span>
                          <span className="ml-2 text-[10px] text-zinc-600">
                            8:44 • 4 tracks
                          </span>
                        </div>
                        <span className="text-[10px] text-zinc-600">100%</span>
                      </div>
                      <div className="space-y-2 rounded-xl border border-zinc-800 bg-zinc-950/70 p-3">
                        <div className="grid grid-cols-[72px_1fr] items-center gap-3">
                          <span className="text-[9px] font-semibold uppercase tracking-wider text-zinc-500">
                            Rallies
                          </span>
                          <div className="flex h-5 gap-1">
                            {[20, 12, 28, 16, 24].map((width, index) => (
                              <span
                                className="rounded bg-zinc-600/80"
                                key={`rally-track-${index}`}
                                style={{ width: `${width}%` }}
                              />
                            ))}
                          </div>
                        </div>
                        <div className="grid grid-cols-[72px_1fr] items-center gap-3">
                          <span className="text-[9px] font-semibold uppercase tracking-wider text-zinc-500">
                            Captions
                          </span>
                          <div className="relative h-3 rounded bg-zinc-900">
                            <span className="absolute left-[8%] h-full w-[22%] rounded bg-cyan-300/70" />
                            <span className="absolute left-[48%] h-full w-[16%] rounded bg-cyan-300/70" />
                            <span className="absolute right-[6%] h-full w-[20%] rounded bg-cyan-300/70" />
                          </div>
                        </div>
                        <div className="grid grid-cols-[72px_1fr] items-center gap-3">
                          <span className="text-[9px] font-semibold uppercase tracking-wider text-zinc-500">
                            Shuttle FX
                          </span>
                          <div className="relative h-3 rounded bg-zinc-900">
                            <span className="absolute left-[3%] h-full w-[35%] rounded bg-lime-300 shadow-[0_0_10px_rgba(190,242,100,0.5)]" />
                            <span className="absolute left-[67%] h-full w-[8%] rounded bg-lime-300" />
                            <span className="absolute right-[4%] h-full w-[6%] rounded bg-lime-300" />
                          </div>
                        </div>
                        <div className="grid grid-cols-[72px_1fr] items-center gap-3">
                          <span className="text-[9px] font-semibold uppercase tracking-wider text-zinc-500">
                            Pose
                          </span>
                          <div className="relative h-3 rounded bg-zinc-900">
                            <span className="absolute left-[10%] h-full w-[18%] rounded bg-fuchsia-400/80" />
                            <span className="absolute left-[31%] h-full w-[10%] rounded bg-cyan-300/80" />
                            <span className="absolute right-[21%] h-full w-[12%] rounded bg-fuchsia-400/80" />
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="border-t border-zinc-800 bg-zinc-900/40 p-5 lg:border-l lg:border-t-0">
                    <div className="mb-5 flex items-center gap-2">
                      <Activity
                        className="h-4 w-4 text-lime-300"
                        strokeWidth={1.7}
                      />
                      <span className="text-xs font-semibold uppercase tracking-[0.14em] text-zinc-300">
                        Tracking layers
                      </span>
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
                      {[
                        ['Rally detection', '10 found', '100%'],
                        ['Player pose', 'Skeletons on', '80%'],
                        ['Shuttle tracking', 'Trajectory on', '89%'],
                        ['Auto captions', '5 moments', '85%'],
                      ].map(([label, detail, score]) => (
                        <div
                          className="rounded-xl border border-zinc-800 bg-zinc-950/70 p-3"
                          key={label}
                        >
                          <div className="mb-2 flex items-center justify-between gap-2">
                            <span className="text-[11px] font-medium text-white">
                              {label}
                            </span>
                            <span className="text-[10px] font-semibold text-lime-300">
                              {score}
                            </span>
                          </div>
                          <div className="flex items-center justify-between">
                            <span className="text-[10px] text-zinc-600">
                              {detail}
                            </span>
                            <span className="h-4 w-7 rounded-full bg-lime-300 p-0.5">
                              <span className="ml-auto block h-3 w-3 rounded-full bg-zinc-950" />
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                    <div className="mt-5 rounded-xl border border-lime-400/15 bg-lime-400/5 p-4">
                      <div className="mb-2 flex items-center gap-2 text-xs font-medium text-white">
                        <Film className="h-4 w-4 text-lime-300" strokeWidth={1.7} />
                        Reel composition
                      </div>
                      <p className="text-[11px] leading-relaxed text-zinc-500">
                        Five rallies selected for a 9:16, beat-synced export.
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section id="how-it-works" className="relative overflow-hidden py-24">
          <div className="mx-auto max-w-7xl px-6">
            <div className="glass-card relative rounded-[3rem] border border-white/5 p-8 lg:p-12">
              <div className="grid grid-cols-1 items-center gap-16 lg:grid-cols-2">
                <div className="group relative order-2 lg:order-1">
                  <div className="absolute -inset-2 rounded-[2.5rem] bg-gradient-to-r from-lime-400 to-emerald-500 opacity-20 blur-lg transition-opacity duration-500 group-hover:opacity-30" />
                  <div className="relative aspect-[4/3] overflow-hidden rounded-[2rem]">
                    <img
                      alt="Original Baddy rally frame with player pose and shuttle trajectory tracking"
                      className="h-full w-full object-cover transition-transform duration-700 group-hover:scale-105"
                      loading="lazy"
                      src={BADDY_UPLOAD_RALLY_IMAGE}
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-zinc-950/70 via-transparent to-transparent" />
                    <div className="absolute bottom-6 left-6 flex items-center gap-3 rounded-2xl border border-white/10 bg-zinc-900/90 px-5 py-3 backdrop-blur">
                      <div className="flex items-center gap-2">
                        <div className="h-2 w-2 animate-pulse rounded-full bg-lime-400" />
                        <span className="text-xs font-medium text-white">
                          Original rally • pose + shuttle tracked
                        </span>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="order-1 lg:order-2">
                  <h2 className="mb-6 text-3xl font-medium leading-tight tracking-tight text-white lg:text-5xl">
                    Upload. Track.
                    <br />
                    <span className="text-lime-400">Share the Rally.</span>
                  </h2>
                  <p className="mb-10 text-lg font-light leading-relaxed text-zinc-400">
                    Upload the whole game, not hand-picked clips. Baddy handles
                    the search, crop, tracking, and edit so you can go straight
                    from the court to a reel.
                  </p>

                  <div className="mb-10 space-y-6">
                    <div className="flex items-start gap-4">
                      <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-lime-400/10">
                        <Upload
                          className="h-5 w-5 text-lime-400"
                          strokeWidth={1.5}
                        />
                      </div>
                      <div>
                        <div className="mb-1 font-medium text-white">
                          Upload the Full Match
                        </div>
                        <div className="text-sm text-zinc-500">
                          One recording or multiple clips, including 4K footage
                        </div>
                      </div>
                    </div>
                    <div className="flex items-start gap-4">
                      <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-lime-400/10">
                        <Brain
                          className="h-5 w-5 text-lime-400"
                          strokeWidth={1.5}
                        />
                      </div>
                      <div>
                        <div className="mb-1 font-medium text-white">
                          AI Finds the Rallies
                        </div>
                        <div className="text-sm text-zinc-500">
                          Rally detection ranks the strongest exchanges
                          automatically
                        </div>
                      </div>
                    </div>
                    <div className="flex items-start gap-4">
                      <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-lime-400/10">
                        <Layers3
                          className="h-5 w-5 text-lime-400"
                          strokeWidth={1.5}
                        />
                      </div>
                      <div>
                        <div className="mb-1 font-medium text-white">
                          Track, Crop, and Beat-Sync
                        </div>
                        <div className="text-sm text-zinc-500">
                          Optional shuttle tracking and a virtual camera help
                          keep the action in frame
                        </div>
                      </div>
                    </div>
                  </div>

                  <Button
                    asChild
                    className="rounded-full bg-lime-400 px-8 py-3.5 font-semibold text-zinc-950 shadow-[0_0_20px_rgba(163,230,53,0.2)] hover:bg-lime-300"
                  >
                    <a data-testid="how-cta-button" href={BADDY_APP_URL}>
                      Generate a Reel
                      <ArrowRight className="h-4 w-4" strokeWidth={1.5} />
                    </a>
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-zinc-900 bg-black pb-10 pt-20">
        <div className="mx-auto max-w-7xl px-6">
          <div className="mb-16 grid grid-cols-2 gap-10 md:grid-cols-4 lg:grid-cols-5">
            <div className="col-span-2 pr-10 lg:col-span-2">
              <div className="mb-6 flex items-center gap-2">
                <div className="flex h-6 w-6 items-center justify-center rounded-md bg-lime-400 text-zinc-950">
                  <BaddyMark className="h-4 w-4" />
                </div>
                <span className="text-lg font-semibold text-white">
                  BADDY<span className="text-lime-400"> AI</span>
                </span>
              </div>
              <p className="mb-6 max-w-xs text-sm leading-relaxed text-zinc-500">
                Turn full badminton matches into story-ready highlight reels
                with AI rally detection, tracking, and virtual camera edits.
              </p>
            </div>

            <div>
              <h4 className="mb-6 font-medium text-white">Product</h4>
              <ul className="space-y-4 text-sm text-zinc-500">
                <li>
                  <a
                    className="transition-colors hover:text-lime-400"
                    href={BADDY_APP_URL}
                  >
                    Create a Reel
                  </a>
                </li>
                <li>
                  <a
                    className="transition-colors hover:text-lime-400"
                    href={BADDY_GALLERY_URL}
                  >
                    Latest Reels
                  </a>
                </li>
                <li>
                  <a
                    className="transition-colors hover:text-lime-400"
                    href="#features"
                  >
                    AI Engine
                  </a>
                </li>
              </ul>
            </div>

            <div>
              <h4 className="mb-6 font-medium text-white">Teams</h4>
              <ul className="space-y-4 text-sm text-zinc-500">
                <li>
                  <a
                    className="transition-colors hover:text-lime-400"
                    href="#how-it-works"
                  >
                    Players
                  </a>
                </li>
                <li>
                  <a
                    className="transition-colors hover:text-lime-400"
                    href="#how-it-works"
                  >
                    Coaches
                  </a>
                </li>
                <li>
                  <a
                    className="transition-colors hover:text-lime-400"
                    href="https://baddyai.com/login.html"
                  >
                    Schools
                  </a>
                </li>
              </ul>
            </div>

            <div>
              <h4 className="mb-6 font-medium text-white">Explore</h4>
              <ul className="space-y-4 text-sm text-zinc-500">
                <li>
                  <a
                    className="transition-colors hover:text-lime-400"
                    href="#how-it-works"
                  >
                    How It Works
                  </a>
                </li>
                <li>
                  <a
                    className="transition-colors hover:text-lime-400"
                    href="https://baddyai.com/architecture"
                  >
                    Architecture
                  </a>
                </li>
                <li>
                  <a
                    className="transition-colors hover:text-lime-400"
                    href="https://baddyai.com/api/health"
                  >
                    Service Status
                  </a>
                </li>
              </ul>
            </div>
          </div>

          <div className="flex flex-col items-center justify-between gap-4 border-t border-zinc-900 pt-8 md:flex-row">
            <p className="text-xs text-zinc-600">
              © {new Date().getFullYear()} Baddy AI. Built for the rally.
            </p>
            <div className="flex items-center gap-2 text-xs text-zinc-600">
              <CheckCircle2 className="h-4 w-4 text-lime-400" strokeWidth={1.5} />
              Full-match AI highlights
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
