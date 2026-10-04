// Absolute seconds in the edit. The recordings already contain their cursor rings.
export const uiSoundMoments: { at: number; kind: "click" | "pop"; scene: string }[] = [
  // Visible extension presses in the supported-sites montage (30 fps).
  { at: 19.533, kind: "click", scene: "findVideo" }, // YouTube: Scan ring is already present as the tile enters
  { at: 20.733, kind: "click", scene: "findVideo" }, // Internet Archive: Find video
  { at: 21.867, kind: "click", scene: "findVideo" }, // TED: Scan video ring first appears at source 37.567
  { at: 22.867, kind: "click", scene: "findVideo" },
  { at: 23.458, kind: "click", scene: "findVideo" },
  { at: 24.533, kind: "click", scene: "findVideo" }, // Moodle / Panopto: Scan ring is present as the tile enters
  { at: 31.5, kind: "pop", scene: "jumpToMoment" },
  { at: 32.779, kind: "click", scene: "jumpToMoment" },
  { at: 41.132, kind: "pop", scene: "followUps" },
  { at: 41.4695, kind: "click", scene: "followUps" },
  { at: 44.6825, kind: "pop", scene: "followUps" },
  { at: 54.017, kind: "click", scene: "itReads" },
];
