# Changelog

## 1.1.0 (2026-11-24)

- **Lefty layout.** A Dojo checkbox puts the reference on the right and the drawing on the left for
  sight-size copies and figure poses, so a left hand never covers the reference. A swap button in
  lessons 16 and 24 flips an open canvas, moving the drawing with it. Saved per student.
- **Bigger library.** 11 themed sets and 157 searches built from Oscar's wishlist, pruned to artists who
  can actually be public domain (see `docs/library.md` for every set and every cut, with reasons).
  **Find artist** downloads any single name into its own folder.
- **From Photobash CC:** Openverse museum collections (Met, Smithsonian, Rijksmuseum and more) as a
  second source, reusing the Openverse login Photobash CC already stored; a thumbnail grid that loads as
  you scroll; double-click for a sight-size canvas; **Add as layer**; **Copy credit** to the clipboard.
- Thumbnails are cached at download time; Openverse licenses read as plain words ("Public domain
  (Public Domain Mark)"); large files over 25 MB are skipped.

## 1.0.1 (2026-11-23)

- Library downloads no longer trip Wikimedia's HTTP 429: thumbnails use the standard 1280 px width,
  the User-Agent carries the project URL per Wikimedia policy, 429/503 responses back off and retry
  (honoring Retry-After), downloads are paced 2 s apart, and credits are saved after every image so
  a stopped download resumes where it left off.

## 1.0.0 (2026-11-23)

First release.

- 25 lessons, 184 cards: tablet setup and calibration, interface, navigation, brushes, pressure and speed,
  brush hotkeys, hand motion and hatching rhythm, layers, layer hotkeys, alpha lock and clipping,
  value 1 to 5, selections and transform, Bargue sight size, the 7-layer pipeline, brush customization,
  blend modes, filter layers and flats, reference and checking, wrap-around textures, saving and the
  Recorder, and a Bargue master-copy capstone.
- Pen capture at the QApplication level: pressure, speed, taper, steadiness, straightness and reach,
  graded against each student's calibrated range.
- Rhythm drills count marks instead of judging each one, so fast hatching stays responsive.
- The Dojo: scored warm-up drills, a 10-second rhythm drill, timed figure drawing, and a
  public-domain library downloader (Wikimedia Commons, license-checked, credits saved).
- Teaching tool, not assessment tool: every card is open, progress stays on the student's machine.
- Krita 5.3 (PyQt5) primary; Krita 6 (PyQt6) supported through `qt.py`.
