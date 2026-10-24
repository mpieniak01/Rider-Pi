# Vision policy parameters

The operator selects an immutable preset (Cautious, Balanced, Fluid) or custom corrections based on one preset. Selecting a preset restores its versioned values. Editing an advanced value displays **Custom based on: Fluid**, rather than silently changing the meaning of Fluid. Legacy remains a separate compatibility policy with no corrections.

## Revisions and ownership

Rider-Pi persists the selection, corrections and configuration revision. Venom executes the same definition and includes its policy digest in each decision. Revision 1 settings retain their original parameter values and digest. Revision 2 must be selected explicitly; saved revision 1 configurations are never migrated on startup.

The wire selection is `{version: 1, profile_id: "fluid", profile_revision: 2, overrides: {obstacle_support_frames: 3}}`. Omit `overrides` to restore the preset. Only changed fields need to be stored. The existing `/api/navigation/config` transaction checks the expected configuration revision, stopped/idle conditions and model identity; changes invalidate prior drive approval and preserve observation-only mode until operator acceptance. Saving does not start observation, load a model, arm or drive.

`behavior_catalog.parameter_editing_version = 1` advertises support. `parameter_schema` provides the authoritative types, ranges, steps and groups. Older peers expose only their existing preset controls. `active_parameters` reports the resolved policy, and `active_base_parameters` reports the same model settings without custom corrections.

## Model stage

The existing selected-model panel controls:

- DA2: `residual_limit` initially 0.06, `outlier_limit` 0.005, `slope_min` 2.0. Residual 0.06 is relative depth deviation, not centimetres. Outlier 0.005 is 0.5 percent.
- ADE20K semantic models: pixel confidence, floor coverage, uncertainty and component fraction, plus the explicit `floor_only` / `floor_rug` surface selection. Pixel confidence is a model score, not collision probability.

Resolution order is preset, selected-model tuning, then explicit custom profile corrections. The model interpreter, navigation aggregation and displayed effective semantic settings use the same final correction. Depth model thresholds remain separate selected-model settings. Changing a behavior preset does not replace model weights, change transport or invent camera calibration.

## Initial Fluid revision 2 values

Fluid revision 2 starts with component support in 2 of the last 3 observations. Unconfirmed obstacle predictions become **uncertain**, never confirmed floor. Existing coverage and uncertainty tests still decide whether the route is supported. A persistent region can still trigger the near guard. Independent critical support and 3D collision evidence are preserved.

Cautious and Balanced revision 2 use one-observation support by default. The same expert controls are available for every non-Legacy revision 2 preset; any corrections are labelled Custom.

| Parameter | Fluid r2 default | Allowed | Group |
|---|---:|---|---|
| `pixel_confidence` | `0.7` | 0.05 … 1.0 (float) | evidence |
| `min_region_fraction` | `0.003` | 0.0 … 0.02 (float) | evidence |
| `thin_span_fraction` | `0.15` | 0.01 … 1.0 (float) | evidence |
| `near_zone_fraction` | `0.35` | 0.05 … 1.0 (float) | evidence |
| `min_floor_fraction` | `0.92` | 0.5 … 1.0 (float) | evidence |
| `min_near_floor_fraction` | `0.95` | 0.5 … 1.0 (float) | evidence |
| `max_uncertain_fraction` | `0.06` | 0.0 … 0.5 (float) | evidence |
| `enter_frames` | `3` | 1 … 8 (int) | temporal |
| `enter_ms` | `100` | 0 … 1000 (int) | temporal |
| `release_frames` | `3` | 1 … 8 (int) | temporal |
| `release_ms` | `100` | 0 … 1000 (int) | temporal |
| `history_ms` | `500` | 100 … 2000 (int) | temporal |
| `max_gap_ms` | `300` | 50 … 1000 (int) | temporal |
| `max_uncertain_ms` | `200` | 0 … 1000 (int) | temporal |
| `min_tracking_ratio` | `0.5` | 0.1 … 1.0 (float) | temporal |
| `slow_speed_factor` | `0.6` | 0.1 … 1.0 (float) | temporal |
| `obstacle_support_frames` | `2` | 1 … 5 (int) | persistence |
| `obstacle_window_frames` | `3` | 2 … 5 (int) | persistence |
| `obstacle_match_overlap` | `0.1` | 0.01 … 1.0 (float) | persistence |
| `obstacle_match_tolerance_px` | `1` | 0 … 3 (int) | persistence |
| `obstacle_min_previous_coverage` | `0.9` | 0.5 … 1.0 (float) | persistence |
| `object_tracking_enabled` | `False` | boolean | objects |
| `object_min_area_px` | `80` | 8 … 4096 (int) | objects |
| `object_match_iou` | `0.1` | 0.01 … 0.9 (float) | objects |
| `object_appearance_min` | `0.2` | 0.0 … 1.0 (float) | objects |
| `object_area_ratio_min` | `0.5` | 0.1 … 1.0 (float) | objects |
| `object_area_ratio_max` | `2.0` | 1.0 … 5.0 (float) | objects |
| `object_max_gap_frames` | `2` | 0 … 3 (int) | objects |
| `object_trend_frames` | `3` | 2 … 5 (int) | objects |
| `object_growth_min` | `1.1` | 1.0 … 3.0 (float) | objects |
| `object_lower_min_px` | `2` | 0 … 40 (int) | objects |

Fractions use 0–1. Millisecond and pixel units are part of the field names. Confirmation counts must not exceed the observation window. Timing limits must fit the history duration. Invalid values, non-finite numbers, unknown fields and stale revisions are rejected without persistence.

## Object diagnostics

Object tracking is **disabled by default** and is diagnostic only. It uses the current model maps; it does not load another model. Semantic maps can supply full-frame proposals. DA2 exposes a wider relative-depth context using the same fitted plane while keeping its scoring region unchanged. Object proposals are not guaranteed instance masks.

When enabled, diagnostic frames show purple boxes with track ID, growth and downward displacement. The source capture and annotation are the same frame. Returned `temporal.objects` includes size, route intersection, clipping and available semantic confidence. Neither enabling diagnostics nor any object-growth parameter changes GO/SLOW/STOP.

The matching controls reject implausible area changes, retain a bounded missed-detection history and use approximate shared image motion. Growth uses the available proposal boundary; camera motion, clipped objects and segmentation merges can still distort it. It is not physical distance, time to collision or navigation qualification.

## Operator flow

Open **Caution level → Profile parameters**, select a revision 2 preset, edit values and explicitly Apply. The current device revision and custom label remain visible. Restore preset removes corrections; Refresh discards an unsaved draft. Another panel's save invalidates an old draft rather than overwriting it. The selected-model thresholds remain in their existing model-tuning section.

Calibration, known-room assumptions, transport freshness and physical acceptance remain independent from these adjustable interpretation values. No centimetre geometry is inferred from confidence or residual thresholds.
