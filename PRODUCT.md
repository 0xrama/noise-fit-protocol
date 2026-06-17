# Product

## Register

product

## Users

A single power-user (the author) on a Mac. Context: morning check-in, glance at
last night's recovery, a periodic sync. The job is a fast, honest readout of what
the NoiseFit Twist watch recorded — no account, no cloud, no app store in between.
The reader understands HRV, SpO₂, sleep architecture, and recovery scoring without
coaching. This is a personal instrument, not a product for a market.

## Product Purpose

A local-first macOS desktop app that connects to a NoiseFit Twist watch over a
reverse-engineered BLE protocol and surfaces today's health signal: steps, heart
rate, sleep (with quality + stages), SpO₂, stress, activity, recovery, and a
biological-age ("whoop age") estimate. It syncs the data onward to Google Fit and
Poke. Everything runs on the machine — the watch speaks directly to this app, the
data never leaves unless the user pushes it. Success is: open the app, see the
truth of last night and today in a few seconds, close it. Calm, precise, owned.

## Brand Personality

**Quiet · expert · confident.**

The feel of reading a precise gauge, not being coached. Calm by default, sharp on
inspection. The interface trusts the reader, shows the number, and stays out of the
way. North-star references:

- **Whoop** — dark, near-monochrome, data-dense but restful; recovery-as-a-score;
  a single restrained accent; the "anti-fitness-app" register where data replaces
  cheerleading. The thing to take: the *instrument* composure, the typographic
  hierarchy of big readouts over quiet detail.
- **Bevel** — sophisticated, editorial restraint, refined dark surface, wellness
  without softness. The thing to take: the *quiet confidence* of a tool that
  respects a literate reader.

It is explicitly fine to live in this Whoop/Bevel aesthetic family — that is the
intended home, not a coincidence to avoid.

## Anti-references

- **The NoiseFit phone app itself** — busy, ad-promotional, gamified streaks and
  badges, iOS-fitness-app cliché. The desktop app is the quiet opposite of it.
- **Gamified fitness UIs** (Apple Fitness rings, Fitbit celebrations, achievement
  badges, "you crushed it!" copy, streak pressure). No rings-as-reward, no
  cheerleading, no manufactured urgency.
- **Generic SaaS analytics dashboards** — cream/beige canvas, the big-number +
  tiny-uplift-cards hero template, emoji icons, gradient accents.
- **Cold clinical / medical-chart sterility** that sacrifices calm. Precision
  without warmth is a failure mode here.

## Design Principles

1. **Show the signal, not the noise.** The product wears the brand name
   ironically: the job is to filter the watch's raw output down to the meaningful
   readout. Data over decoration; one number that matters beats five that don't.
2. **Calm by default, precise on inspection.** The at-a-glance state is restful;
   every detail surface (a card → its page) should reward a reader who looks
   closer. Never anxious, never celebratory.
3. **Expert, not explanatory.** The reader knows what SpO₂ and sleep architecture
   mean. No hand-holding tooltips, no "what does this mean?" coaching, no
   dictionary popovers. State the value, trust the reader.
4. **Local and native by nature.** It runs entirely on the Mac and the interface
   should feel like a tool that belongs to this machine — offline, owned, not a
   web app pretending to be desktop. Native-feeling surfaces (including the
   intended macOS Liquid-Glass vibrancy) are part of the identity, not styling.
5. **Honest about provenance.** This is a reverse-engineered client on a captured
   token. The interface may acknowledge its maker-tool nature where it earns
   something (the "runs entirely on your Mac" footer, the pairing-token panel)
   rather than pretending to be a polished commercial SKU.

## Accessibility & Inclusion

No specific accessibility requirements. Treat as a default desktop product:
target AA contrast (≥4.5:1 body text), keep the existing `prefers-reduced-motion`
paths intact, and rely on the native macOS WebKit host for system-level
accessibility (Dynamic Type, VoiceOver where the markup supports it). Don't
compromise the calm, low-motion aesthetic to chase a checklist.
