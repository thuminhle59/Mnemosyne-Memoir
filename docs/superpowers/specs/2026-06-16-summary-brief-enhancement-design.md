# Summary Brief Enhancement Design

## Goal

Enhance the Summary section so it becomes a concise, stable executive brief for the selected meeting, instead of a heuristic slice of the raw `summary` text.

The brief must answer: what this meeting was about, what was decided, what risk matters most, and what the next step is.

## Scope

This design covers the selected-meeting Summary shown in the `Summary` tab. It does not change Q&A, Evidence, Actions, audio playback, meeting grouping, or export behavior.

## Summary Limits

The Summary brief has four optional sections:

- `Context`: exactly 1 most important sentence when available.
- `Decisions`: up to 2 most important decision sentences.
- `Risks`: exactly 1 most important risk or blocker sentence when available.
- `Next steps`: exactly 1 most important action or next-step sentence when available.

The maximum visible Summary is 5 sentences. Empty sections are hidden; the UI should not show placeholder text such as "No items yet" inside Summary.

## Backend Design

Keep the existing `summary` field for backward compatibility. Add a structured field to the meeting report payload:

```json
{
  "summary_brief": {
    "context": "string|null",
    "decisions": ["string"],
    "risk": "string|null",
    "next_step": "string|null"
  }
}
```

The backend should normalize arrays and strings after model output:

- `context` is a string or null.
- `decisions` is trimmed to at most 2 non-empty strings.
- `risk` is a string or null.
- `next_step` is a string or null.

Older meetings without `summary_brief` must still load and render using the existing `summary` fallback.

## Extraction Rules

The `analyze.py` extraction prompt should ask for `summary_brief` in addition to the current fields.

Rules for the model:

- Preserve English terms, product names, project names, acronyms, and code terms exactly as they appear.
- Do not invent information outside the transcript or map-reduce notes.
- The `decisions` summary items must align with `decisions[]` whenever possible.
- The `risk` summary item must align with `risks[]` whenever possible.
- The `next_step` summary item must align with `action_items[]` whenever possible.
- Prefer specific business content over generic process language.
- Do not include quotes or timestamps in `summary_brief`.

## Consistency Guard

After parsing the LLM result, the backend should enforce limits and consistency:

- If `summary_brief.decisions` is empty but `decisions[]` has items, use the first 1-2 decision texts.
- If `summary_brief.risk` is empty but `risks[]` has items, use the first risk.
- If `summary_brief.next_step` is empty but `action_items[]` has items, use the first action task.
- If `summary_brief.context` is empty, derive one sentence from the existing `summary`.

This keeps the visible Summary aligned with the detailed sections below it.

## Frontend Design

Replace the current regex-based `executiveSummaryLines()` rendering with a deterministic renderer:

- Prefer `meeting.summary_brief`.
- Fallback to current `meeting.summary` split into up to 3 readable paragraphs for old data.
- Render compact labeled sections:
  - `Context`
  - `Decisions`
  - `Risk`
  - `Next step`
- Hide any empty section.

The Summary card should stay visually compact and above the section jump buttons.

## Terminology Refresh

When the user saves terminology and refreshes a meeting, the backend should regenerate and glossary-normalize `summary_brief` together with:

- transcript
- summary
- decisions
- actions
- risks
- evidence/facts
- contradictions derived from the refreshed meeting data

Glossary normalization should apply to every text field inside `summary_brief`.

## Testing Plan

Add backend tests for:

- New report parsing accepts `summary_brief`.
- Missing `summary_brief` falls back without breaking old meetings.
- Summary limits are enforced: 1 context, 2 decisions, 1 risk, 1 next step.
- Empty brief fields are filled from existing decisions, risks, actions, or summary when available.
- Terminology refresh updates text inside `summary_brief`.

Add frontend tests for:

- `renderExecutiveSummary()` renders structured sections when `summary_brief` exists.
- Empty structured sections are hidden.
- Old meetings without `summary_brief` still render the existing `summary`.
- The old regex-based prioritization is no longer used for structured brief rendering.

## Non-Goals

- No change to contradiction paraphrasing.
- No change to Q&A group scoping.
- No new Summary citations.
- No timestamp display inside Summary.
- No reload unless explicitly requested by the user.
