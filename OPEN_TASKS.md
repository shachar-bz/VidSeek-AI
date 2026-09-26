# Open tasks

Known gaps left open deliberately. Each entry says where it stands, what actually goes
wrong, and what closing it would take.

Everything listed here is a **known limitation, not a regression**: the download,
transcript, cancel and capture paths were exercised end to end against a running
companion and a real browser before this file was written.

---

## 1. The `<video>` element's MIME type is always empty

**Status:** open, cosmetic. **Problem:** `discoverPage` reads
`video.getAttribute("type")`, but `type` is a `<source>` attribute and is never present on
`<video>`; the call always yields `null`. So a `<video src>` candidate is classified by URL
extension alone, and an extension-less signed CDN URL is dropped entirely.

**To close:** either drop the dead `getAttribute` call, or derive a type from a `<source>`
sibling or `canPlayType`. Dropping it alone changes nothing; it is listed because it reads
as though it does something.
