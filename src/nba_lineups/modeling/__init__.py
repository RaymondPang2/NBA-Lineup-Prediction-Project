"""Phase 5+: leak-free features, chronological validation and baselines.

Two stages keep fitted information out of validation folds:

  Stage 1 (`raw`)       deterministic pre-break aggregates, each a function of ONE season's pre-break
                        data. Nothing is learned, so they can be computed once for all seasons.
  Stage 2 (`features`)  `FeatureBuilder.fit(tables, train_seasons)` learns shrinkage hyperparameters and
                        fallbacks from the TRAINING seasons only; `.transform` applies them to any season.

The target (post-break net rating) is read by exactly one function, `raw.load_targets`.
Only the development seasons (2018-19 .. 2023-24) can be read; the held-out seasons raise HeldOutDataError.
"""
