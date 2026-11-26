---
name: AP Agent
description: Invoice review as a voucher packet on a desk blotter, routed desk to desk and stamped.
colors:
  blotter: "#d3dbd5"
  blotter-deep: "#c3cdc6"
  paper: "#fdfdfb"
  canary: "#f8eeb4"
  pink: "#f7d9df"
  goldenrod: "#efd28c"
  manila: "#ece2c6"
  slip: "#f5e4d6"
  greenbar: "#e7f0e6"
  form: "#2b5c55"
  rule: "#a9c0b9"
  rule-soft: "#d6e2de"
  carbon: "#312c86"
  ink: "#1b2220"
  muted: "#4f5d59"
  stamp-ok: "#17683f"
  stamp-hold: "#b04a06"
  stamp-void: "#b3261e"
typography:
  display:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "28px"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "-0.01em"
    fontVariation: "\"wdth\" 112"
  headline:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "26px"
    fontWeight: 800
    lineHeight: 1.25
    letterSpacing: "-0.01em"
    fontVariation: "\"wdth\" 112"
  title:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 800
    letterSpacing: "-0.01em"
    fontVariation: "\"wdth\" 112"
  body:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.43
    fontVariation: "\"wdth\" 100"
  label:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "10px"
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: "0.08em"
    fontVariation: "\"wdth\" 75"
  typed:
    fontFamily: "Sometype Mono, ui-monospace, monospace"
    fontSize: "15px"
    fontWeight: 400
    fontFeature: "\"tnum\""
rounded:
  none: "0px"
spacing:
  cell-x: "16px"
  cell-y: "10px"
  box-x: "12px"
  section: "28px"
components:
  button-primary:
    backgroundColor: "{colors.carbon}"
    textColor: "{colors.paper}"
    rounded: "{rounded.none}"
    padding: "8px 16px"
  button-quiet:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "8px 12px"
  stamp-button-approve:
    textColor: "{colors.stamp-ok}"
    rounded: "{rounded.none}"
    padding: "6px 16px 8px"
    width: "124px"
  stamp-button-void:
    textColor: "{colors.stamp-void}"
    rounded: "{rounded.none}"
    padding: "6px 16px 8px"
    width: "124px"
  form-box:
    textColor: "{colors.carbon}"
    typography: "{typography.typed}"
    rounded: "{rounded.none}"
    padding: "6px 12px 8px"
  sheet:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.none}"
  copy-tab-active:
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "8px 16px"
  copy-tab-inactive:
    textColor: "{colors.muted}"
    rounded: "{rounded.none}"
    padding: "8px 16px"
---

# Design System: AP Agent

## Overview

**Creative North Star: "The Voucher Packet"**

Every invoice is a paper voucher packet lying on a grey-green desk blotter: an invoice copy, a PO copy and a check sheet stapled behind a voucher cover, routed desk to desk on a salmon routing slip, then rubber-stamped. Surfaces are sheets of multipart form stock, never cards. Printed form furniture (labels, rules, corner boxes) is in drop-out teal; anything the system "typed" onto the form is carbon blue-violet mono; decisions are rubber-stamp ink.

The register is green-bar continuous-form paper with tractor-feed margins; batch totals sit on an adding-machine control tape with a torn right edge; the test batch is manila stock. Density is clerical: hairline rules, tight ruled cells, exact figures. The world refuses the white-card SaaS dashboard with stat tiles.

**Key Characteristics:**
- Paper stocks carry meaning: each packet copy has its own colored stock.
- Three inks with fixed jobs: teal prints the form, carbon fills it in, stamp inks decide.
- Square corners and hairline rules everywhere; depth only as paper lying on paper.
- The decision is a raster rubber-stamp impression, and its one authored motion is the strike.

## Colors

A muted desk-and-paper neutral field with three saturated stamp inks reserved for decisions.

### Primary
- **Carbon Copy Violet** (carbon): Every typed or filled-in value (amounts, IDs, invoice and PO numbers, dates, inputs), the primary button, focus ring, caret and text selection tint, and the "in process" state.

### Secondary
- **Drop-out Form Teal** (form): Printed form labels, corner labels, column heads, "Note" outcome marks, intake border. It is the printer's ink, never data.

### Tertiary (stamp inks)
- **Approved Green** (stamp-ok): Approved stamp, cleared checks, "sure" confidence, approved vendors.
- **Hold Orange** (stamp-hold): Hold stamp, held checks, "leaning" confidence, held totals.
- **Void Red** (stamp-void): Void stamp, rejected checks, "torn" confidence, error notes, blocked vendors.

### Neutral
- **Desk Blotter** (blotter) and **Deep Blotter** (blotter-deep): Page ground and header rule; the in-tray well tints from blotter-deep.
- **Bond White** (paper): Default sheet and voucher cover.
- **Canary**, **Pink**, **Goldenrod**, **Manila**, **Salmon Slip** (canary, pink, goldenrod, manila, slip): Multipart stocks. Canary = invoice copy and POs; pink = PO match; goldenrod = source; manila = audit file and test batch; slip = routing slip. Canary at 60% is also the register row hover.
- **Green-bar** (greenbar): Alternating two-row bands on the register.
- **Form Rule** (rule) and **Soft Rule** (rule-soft): Hairline borders and dividers; soft rule for in-list dividers, skeletons and empty confidence ticks.
- **Desk Ink** (ink) and **Muted Ink** (muted): Body text and secondary text; muted is also the "Error" stamp ink.

### Named Rules
**The Three Inks Rule.** Teal is printed, carbon is typed, stamp inks decide. A value the system extracted or computed is never teal; a label is never carbon; green, orange and red appear only where a decision, check outcome or confidence is being stated.

**The Stock Means Copy Rule.** A sheet's paper color says which copy of the packet it is. Don't recolor a stock for decoration or reuse it for a different copy.

## Typography

**Display Font:** Archivo (variable width and weight, with ui-sans-serif, system-ui)
**Label/Mono Font:** Sometype Mono (with ui-monospace)

**Character:** Archivo's width axis does the hierarchy: wide extra-bold for sheet titles, condensed semibold caps for printed labels, normal width for reading. Sometype Mono is the typewriter on the form.

### Hierarchy
- **Display** (800, 28px, wdth 112): Page title ("Voucher register").
- **Headline** (800, 26px, wdth 112): Vendor name on the voucher cover; the in-tray title runs at 24px.
- **Title** (800, 18px, wdth 112): Sheet headers (Register, Test batch, Routing slip, copy headings).
- **Body** (400 / 600 for names, 14px; 12px for secondary lines): Reasons, check detail, table text.
- **Label** (600, 10px, 0.08em, uppercase, wdth 75, form teal): Printed form labels and column heads only.
- **Typed** (Sometype Mono 400, 15px in form boxes, 22px for tape tallies, 12-14px in tables, tabular numerals): Every value.

### Named Rules
**The Typed Value Rule.** Money, identifiers, dates and counts are set in the mono with tabular numerals, exactly as printed. Amounts right-align in tables.

**The Label Is Furniture Rule.** The condensed caps label names a box, column or field on the form. It never sits above a heading as a section tag.

## Layout

Centered column, max 1240px, 16px gutters (32px from md). Pages stack sections at 24-28px. Sheets open with a header strip (16px x 10px padding, bottom rule) and hold ruled cells at the same 16px x 10px rhythm; form boxes use 12px horizontal padding. The register sits between two 22px tractor-feed margins with dashed inner rules. The run view puts a 300px routing slip left of the tabbed packet copies from lg; the voucher cover splits into a field grid and a 260px stamp column from md; field grids go 2 to 4 columns. Wide tables scroll horizontally inside their sheet rather than reflowing.

## Elevation & Depth

Depth is paper on a desk, nothing else. A sheet carries a near-contact shadow plus a soft long falloff, so it reads as lying flat on the blotter. Stacked carbon copies are offset sheets (pink 10px, canary 5px up-right) behind the voucher cover, held by a drawn staple. Copy tabs carry a small upper-left falloff so they read as overlapping tab stock.

### Shadow Vocabulary
- **Sheet on blotter** (`box-shadow: 0 1px 1px rgb(27 34 32 / .06), 0 10px 24px -14px rgb(27 34 32 / .35)`): Every sheet.
- **Control tape** (`box-shadow: 0 1px 1px rgb(27 34 32 / .06), 0 8px 18px -12px rgb(27 34 32 / .4)`): The batch control strip.
- **Tab stock** (`box-shadow: 2px -1px 3px -2px rgb(27 34 32 / .25)`): Packet copy tabs.

### Named Rules
**The Paper Only Rule.** Only things that are paper cast shadows, and only soft ones. Buttons, inputs and marks are flat ink.

## Shapes

Square corners throughout (0px). Borders are 1px hairlines in form rule; dashed rules mark perforations, tear lines and drop zones; dotted rules divide tape tallies. Silhouettes come from paper: the control tape's torn chevron right edge, tractor-feed hole columns, overlapping tab tops, offset carbon copies. Stamps are slightly rotated (-7deg on the cover, -3deg in the register, -4deg while in process).

## Components

### Buttons
- **Shape:** Square (0px).
- **Primary:** Carbon fill, paper text, 14px semibold, 8px x 16px.
- **Quiet:** Paper fill, 1px rule border, ink text; border turns form teal on hover.
- **Text action:** Muted 12px semibold with a 14px line icon, darkening to ink on hover (Clear demo history, back link).
- **Disabled:** 50% opacity.

### Stamp Button (signature)
The commit gesture is a rubber-stamp face. 2px border and word in the stamp ink (Approved green or Void red), extra-bold caps at wdth 118 with 0.08em tracking, a 11px ink sub-label naming the consequence ("Pay this invoice", "Do not pay"). Lifts 2px on hover, presses 2px on active, 150ms.

### Stamp Impression (signature)
Raster PNG with real ink texture (uneven pressure, speckle voids), double-ruled box, condensed caps word plus sub-line, multiplied onto the paper. 96px tall on the voucher cover, 28px in the register. Words: APPROVED / for payment, HOLD / for review, VOID / do not pay, IN PROCESS, ERROR / run failed. Assets are generated, not hand-drawn in CSS.

### Sheets / Containers
- **Corner Style:** Square.
- **Background:** One stock per role (see Colors).
- **Shadow Strategy:** Sheet on blotter.
- **Border:** 1px form rule.
- **Internal Padding:** Header strip 16px x 10px; body 16-20px.

### Form Box
A ruled cell on a printed form: teal corner label on top, carbon mono value 15px beneath, truncating. Grids of form boxes share borders (right and bottom only) so they read as one printed grid.

### Inputs / Fields
- **Style:** Underline only (1px rule bottom border), transparent ground, carbon mono text, carbon caret.
- **Focus:** Underline turns carbon; global focus ring is 2px carbon outline at 2px offset.

### Navigation
File-folder tabs on the header rule: 14px semibold, active tab is paper with rule border and no bottom border so it joins the page; inactive is muted with transparent border. Packet copy tabs use the same idea in each copy's stock, overlapping by 8px, inactive ones dropped 4px and rising on hover.

### Register (signature)
Green-bar continuous form: rows banded in pairs, tractor-feed margins each side, label-style column heads, canary hover. Each row shows the small stamp, a two-line reason, and typed money and IDs.

### Routing Slip and Marks
- **Routing slip:** Salmon stock list of desks; done desks show a typed time and duration that punch in (180ms), the current desk pulses "at desk" in carbon, unreached desks are a blank signature line.
- **Outcome mark:** 11px bold condensed caps with a line icon: Clear (green), Note (teal), Hold (orange), Void (red).
- **Confidence:** Three 3px pencil ticks, filled to the level in the matching stamp ink.

### States
Skeletons are soft-rule blocks with pulse; empty states are a dashed rule box with a title and one plain sentence; errors are a paper strip with a red hairline, red text and a "Try again" action.

## Do's and Don'ts

### Do:
- **Do** set every value the system produced in carbon Sometype Mono with tabular numerals, exactly as printed.
- **Do** give each packet copy its own paper stock and keep the mapping fixed.
- **Do** express a decision as a stamp impression or stamp-face button, in the stamp ink for that decision.
- **Do** keep corners square and borders 1px hairlines in form rule.
- **Do** use the stamp strike (380ms, overshoot settle) only when a decision lands while the reviewer is watching, and drop it under reduced motion.

### Don't:
- **Don't** build white rounded cards, stat tiles or dashboard KPI blocks; totals belong on the control tape.
- **Don't** use stamp green, orange or red for decoration, links or headings.
- **Don't** put the condensed caps label above a heading as a section tag.
- **Don't** give buttons, inputs or marks a shadow; only paper casts one.
