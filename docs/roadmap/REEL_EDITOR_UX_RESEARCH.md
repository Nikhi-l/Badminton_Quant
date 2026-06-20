# Reel editor UX research and schema

Date: 2026-06-20  
Task: TASK-007  
PRD: §8a reel editor UI

## References reviewed

- Remotion `template-prompt-to-motion-graphics-saas`
  - Useful pattern: prompt/validation/code generation/live preview architecture.
  - Baddy takeaway: keep generated/AI edit state explicit and previewable before
    render. Do not add prompt-to-code generation in this slice.
- Remotion Editor Starter and Remotion Timeline
  - Useful pattern: top tool ribbon, central canvas, right inspector, layer-based
    timeline, and Remotion-backed rendering.
  - Constraint: Editor Starter and Timeline are paid/license-bound components;
    do not copy their source into this public project without buying and checking
    license terms.
- Remotion timeline docs
  - Useful pattern: model the editor as multiple tracks with items placed by
    time, then synchronize player time with playhead/timeline state.
- React Video Editor open-source edition and designcombo/react-video-editor
  - Useful pattern: browser editor primitives for clips/text overlays, multi
    track editing, preview, and export.
  - Baddy takeaway: good future migration references if `web/` becomes React, but
    too heavy for the current no-build static SPA slice.
- Twick
  - Useful pattern: timeline-based React SDK with captions, overlays, effects,
    and AI-oriented editing packages.
  - Baddy takeaway: evaluate later if the app moves to a React SDK architecture.

## UX direction for Baddy

The editor should feel like a production tool for a completed AI reel, not a
generic upload/gallery page.

Primary regions:
- Top actions: switch Reel/Source view, export current MP4, close Studio.
- Left layer rail: Reel cuts, Shuttle FX, Pose skeleton, Soundtrack.
- Center canvas: 9:16 preview with Baddy AI overlays.
- Right inspector: context controls for selected layer.
- Bottom timeline: labeled tracks for Reel cuts, Shuttle FX, Pose, Soundtrack,
  with a playhead synchronized to the video.

Removed from the current UI until the backend supports them:
- Trim/split/snap tools: no clip-handle edit model exists yet.
- Text tools: no text layer schema or renderer exists yet.
- Undo/redo: no edit history exists yet.
- Manual save: editor state auto-saves to local storage on changes.
- Music track/volume/ducking choices: the stitcher owns the soundtrack today;
  show the Soundtrack as read-only until audio-track render props exist.

## `baddy.editor.v1`

Client-side state used by the Studio editor:

```json
{
  "schema": "baddy.editor.v1",
  "canvas": {
    "width": 1080,
    "height": 1920,
    "fps": 30,
    "format": "vertical-reel"
  },
  "remix": {
    "order": [1, 3, 2],
    "mirror": false
  },
  "overlays": {
    "shuttle": {
      "enabled": true,
      "style": "ring",
      "size": 54,
      "opacity": 0.92,
      "trail": true
    },
    "pose": {
      "enabled": false,
      "style": "glow",
      "lineWidth": 3,
      "opacity": 0.82
    }
  },
  "audio": {
    "bed": "current-stitch",
    "editable": false
  }
}
```

## Time-level data contract

Current public API now exposes a bounded, normalized shuttle sample list on each
public rally vision object:

```json
{
  "vision": {
    "status": "ok",
    "shuttle_quality": 0.88,
    "shuttle_track": [
      { "t": 12.433, "x": 0.56123, "y": 0.31877, "confidence": 0.91 }
    ]
  }
}
```

Notes:
- `t` is source-video time in seconds.
- `x` and `y` are normalized source-frame coordinates.
- The response is downsampled to at most 180 points per rally.
- Vendor fields are stripped.

Future backend/render contract should add:
- `render_track`: shuttle points mapped into final 1080x1920 reel coordinates.
- `pose_track`: per-time keypoints with normalized coordinates, confidence, and
  player id.
- `audio_tracks`: chosen music id, beat grid, volume automation, and ducking.
- `overlay_style`: serialized shuttle/pose style choices consumed by
  `render.render_rally()`.

## Implementation decision

For TASK-007, keep the static SPA and implement the editor shell in
`web/index.html`, `web/style.css`, and `web/app.js`. This avoids introducing
React/Remotion build complexity while the backend tracking/render contract is
still moving. A future React/Remotion migration can reuse the `baddy.editor.v1`
schema and the track/layer mental model.
