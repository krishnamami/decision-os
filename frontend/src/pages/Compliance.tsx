import { PublicPage } from './Security'

export default function Compliance() {
  return (
    <PublicPage
      title="Compliance & audit"
      intro="Accord documents every decision so you can answer any examiner question in seconds — not weeks."
      sections={[
        ['Complete audit trail', 'Every AI finding, every human action, and every override is recorded with its reasoning, the data it was based on, and who did it. Decisions are append-only — nothing is silently changed.'],
        ['HMDA reporting', 'Loan-level demographics, actions, and characteristics are captured for Home Mortgage Disclosure Act reporting and exportable on demand.'],
        ['Fair lending', 'Approval rates by segment, geographic analysis, and disparate-impact testing surface potential issues before an examiner does — with clear pass/flag results.'],
        ['Adverse action', 'Denials are tracked with the reason recorded; adverse-action notices are queued to meet the regulatory window. Nothing falls through the cracks.'],
        ['One-click examiner package', 'Export the full decision trail — AI findings, human reviews, overrides, and rationale — as a single package for internal audit or a regulator.'],
        ['Humans decide, on the record', 'AI evaluates and recommends; people make the call. Overrides require a written justification, which is preserved in the trail. The system is designed so a reviewer can always explain why a loan was approved or denied.'],
        ['Designed for SOC 2', 'Our controls and architecture are built toward SOC 2 Type II. We will state our certification status honestly at every step.'],
      ]}
    />
  )
}
