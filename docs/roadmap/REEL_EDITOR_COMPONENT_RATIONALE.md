# Reel editor component rationale

Date: 2026-06-21
Task: TASK-007 reasoning pass
Surface: `web/` Studio editor

## Principle

Every visible Studio control must satisfy one of three reasons:

1. It changes preview state immediately.
2. It calls an existing backend path.
3. It reveals current AI/reel evidence needed to make an editing decision.

Controls that only implied future capabilities were removed from the live UI.

## Kept components

| Component | Reason | Current path |
|---|---|---|
| Studio brand + filename | Confirms the editor context and source reel. | Read-only metadata from gallery/job result. |
| Reel / Source rallies switch | Lets the user compare the finished edit with every AI-detected source rally. | Switches video source between `reel.mp4` and `proxy.mp4`; timeline rebuilds to reel or source mode. |
| Export | Downloads the currently rendered MP4. | Link to `/media/{job_id}/reel.mp4`. |
| Close | Returns to gallery/upload flow without changing edit state. | Hides Studio and releases video playback. |
| Layer rail: Reel cuts | Selects the supported edit layer: rally inclusion/order. | Inspector shows composition stats; chips and rebuild call current remix API. |
| Layer rail: Shuttle FX | Selects shuttle overlay preview controls. | Updates local `baddy.editor.v1.overlays.shuttle` and canvas preview. |
| Layer rail: Pose skeleton | Selects pose overlay preview controls. | Updates local `baddy.editor.v1.overlays.pose` and canvas preview. |
| Layer rail: Soundtrack | Shows that the current reel has an audio bed but no editable audio contract yet. | Read-only inspector; timeline displays current stitched bed. |
| Rally chips | Let the user include/exclude and reorder rally clips. | Builds the `rallies` array sent to `/api/jobs/{id}/remix`. |
| Rally chip arrows | Move a rally earlier/later in the rebuild order. | Mutates local order and rebuild payload. |
| Mirror checkbox | Previews and submits mirror render option. | `mirror` boolean sent to `/api/jobs/{id}/remix`; preview uses CSS flip. |
| Rebuild cuts | Re-renders the supported backend edit: selected rally order + mirror. | POST `/api/jobs/{id}/remix`. |
| 9:16 canvas | Shows the output frame shape users are editing for. | Plays reel/source video and overlay preview. |
| Canvas zoom out / fit / zoom in | Helps inspect overlay placement and crop without changing export. | CSS zoom only; no render mutation. |
| Coach / vision bar | Provides evidence quality before trusting pose/shuttle overlays. | Read-only compact vision + coach metadata. |
| Inspector: composition | Summarizes current output duration, selected rally count, and AI signal. | Read-only from public result. |
| Inspector: shuttle controls | Lets users test shuttle marker style, size, opacity, and trail. | Mutates local preview state; future render contract will consume it. |
| Inspector: pose controls | Lets users test skeletal style, width, and opacity. | Mutates local preview state; future render contract will consume it. |
| Inspector: soundtrack | Prevents a false music-edit promise while preserving audio context. | Read-only until backend `audio_tracks` exists. |
| Play / pause | Reviews the edit in time. | Native video playback. |
| Scrub range | Seeks to a moment in the reel/source video. | Sets `video.currentTime`. |
| Speed controls | Reviews timing at slow/normal/fast speeds without mutating export. | Sets `video.playbackRate`. |
| Timeline | Shows temporal structure of cuts, overlay spans, pose spans, and audio bed. | Rebuilt from public rally metadata and local overlay state. |
| Timeline zoom slider | Helps inspect dense rally/source timelines. | Changes timeline width only. |
| Timeline segment click | Jumps to a rally/layer moment and selects the relevant layer. | Sets `video.currentTime` and `selectedLayer`. |

## Removed flows

| Removed control | Why removed |
|---|---|
| Top tool ribbon | Duplicated layer rail and contained mostly non-functional tools. |
| Trim tool | No clip-handle model or backend trim payload exists yet. |
| Text tool | No text layer schema or renderer exists yet. |
| Undo / redo | No edit history stack exists yet. |
| Manual save button | State auto-saves locally on each change; a save button implied server persistence. |
| Generic Editor button | It selected the already-visible Reel layer and added no new state. |
| Snap / split timeline buttons | No snapping or split operations exist yet. |
| Editable music choices | The current backend owns soundtrack stitching; choosing tracks would not affect export. |

## Next backend contract

To reintroduce removed flows, add server-side contracts first:
- clip edit payloads for trim/split;
- text/graphic layer schema and renderer;
- persisted edit documents on jobs;
- undoable revision history;
- `audio_tracks` render props for music selection, volume, and ducking;
- final-frame `render_track` and `pose_track` for export-accurate overlays.
